"""
fh2agg.project — the stateful "mod project" that the GUI operates on.

This class is the single source of truth for:
  - which AGG file is open
  - which entries exist and what type they are
  - pending replacements (changes not yet written to disk)
  - saving a patched AGG to disk

It is designed for extension: new asset type handlers can be registered via
``AssetHandler`` subclasses without touching the GUI code, so this naturally
becomes the foundation of a larger modding engine.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Callable, ClassVar

from .aggfile import AggFormatError, build_agg, parse_agg
from .music import MUSIC_CATALOGUE, ICN_SECTIONS, MusicTrack
from .sound import SOUND_AGG_NAMES, SOUND_INFO


# ---------------------------------------------------------------------------
# Asset type system
# ---------------------------------------------------------------------------

class AssetType(Enum):
    SPRITE  = auto()   # .ICN  — indexed sprite sheet
    SOUND   = auto()   # .82M  — raw PCM sound effect
    MUSIC   = auto()   # virtual entry (file on disk, not in AGG)
    PALETTE = auto()   # .PAL  — VGA palette
    OTHER   = auto()   # everything else


@dataclass
class AssetEntry:
    """One entry as seen by the GUI."""
    name: str               # AGG entry name, e.g. "TROLL.ICN"
    atype: AssetType
    section: str            # human-readable group, e.g. "Creatures (Combat)"
    friendly: str           # e.g. "Troll (ICN)"
    size: int               # current byte size (original or replacement)
    replaced: bool = False  # True if the user has staged a replacement
    replacement_path: str = ""  # path to the replacement file


@dataclass
class MusicEntry:
    """One music track slot — may or may not have a file on disk."""
    track: MusicTrack
    installed_path: str | None   # absolute path if file found, else None
    replaced: bool = False
    replacement_path: str = ""


# ---------------------------------------------------------------------------
# The project
# ---------------------------------------------------------------------------

class Project:
    """
    Open an AGG file and expose its contents as a list of AssetEntry objects.

    Usage::

        proj = Project()
        proj.open("/path/to/HEROES2.AGG", music_dir="/path/to/music")
        # browse proj.assets / proj.music_tracks
        proj.stage_sprite_replacement("TROLL.ICN", "/tmp/TROLL_new.ICN")
        proj.save("/path/to/HEROES2_modded.AGG")
    """

    def __init__(self) -> None:
        self._agg_path: str = ""
        self._music_dir: str = ""
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._palette: list[tuple[int, int, int]] = []

        self.assets: list[AssetEntry] = []
        self.music_tracks: list[MusicEntry] = []

        # Pending replacements keyed by AGG entry name
        self._pending: dict[str, bytes] = {}

    # ------------------------------------------------------------------
    # Open / close
    # ------------------------------------------------------------------

    def open(self, agg_path: str, music_dir: str = "") -> None:
        """Load an AGG archive and index all its assets."""
        with open(agg_path, "rb") as f:
            data = f.read()

        self._entries = parse_agg(data, verify_hashes=True)
        self._agg_path = agg_path
        self._music_dir = music_dir
        self._pending = {}

        # Load the palette so the GUI can render sprites
        pal_raw = self._entries.get("KB.PAL", b"")
        if pal_raw:
            from .palette import load_palette
            try:
                self._palette = load_palette(pal_raw)
            except Exception:
                self._palette = []

        self._index_assets()
        self._index_music(music_dir)

    def is_open(self) -> bool:
        return bool(self._agg_path)

    def close(self) -> None:
        self._agg_path = ""
        self._entries = OrderedDict()
        self._pending = {}
        self.assets = []
        self.music_tracks = []
        self._palette = []

    # ------------------------------------------------------------------
    # Palette access
    # ------------------------------------------------------------------

    @property
    def palette(self) -> list[tuple[int, int, int]]:
        return self._palette

    # ------------------------------------------------------------------
    # Raw data access
    # ------------------------------------------------------------------

    def raw_bytes(self, entry_name: str) -> bytes:
        """Return current bytes for an AGG entry (replacement if staged)."""
        if entry_name in self._pending:
            return self._pending[entry_name]
        return self._entries.get(entry_name, b"")

    # ------------------------------------------------------------------
    # Staging replacements
    # ------------------------------------------------------------------

    def stage_sprite_replacement(self, entry_name: str, new_icn_bytes: bytes) -> None:
        """Stage new ICN bytes for ``entry_name`` (not written to disk yet)."""
        self._pending[entry_name] = new_icn_bytes
        self._refresh_asset(entry_name)

    def stage_sound_replacement(self, entry_name: str, new_m82_bytes: bytes) -> None:
        """Stage new .82M PCM bytes for ``entry_name``."""
        self._pending[entry_name] = new_m82_bytes
        self._refresh_asset(entry_name)

    def stage_music_replacement(self, track: MusicTrack, new_audio_path: str) -> None:
        """Record that this music track should be replaced on save."""
        for mt in self.music_tracks:
            if mt.track.track_id == track.track_id:
                mt.replaced = True
                mt.replacement_path = new_audio_path
                break

    def clear_replacement(self, entry_name: str) -> None:
        """Un-stage a pending sprite/sound replacement."""
        self._pending.pop(entry_name, None)
        self._refresh_asset(entry_name)

    @property
    def has_pending_changes(self) -> bool:
        if self._pending:
            return True
        return any(mt.replaced for mt in self.music_tracks)

    @property
    def has_pending_agg_changes(self) -> bool:
        """True if any sprite/sound (AGG-packed) replacement is staged.

        Distinct from ``has_pending_changes``, which also counts staged
        music replacements — those never go into an AGG at all (music is
        loose files on disk), so callers building a HEROES2X.AGG overlay
        need this narrower check.
        """
        return bool(self._pending)

    def build_overlay_bytes(self, existing_entries: "OrderedDict[str, bytes] | None" = None) -> bytes:
        """Build raw AGG bytes for a minimal HEROES2X.AGG-style overlay.

        Contains ONLY this project's pending sprite/sound replacements,
        merged on top of ``existing_entries`` (e.g. the current contents of
        a real Price of Loyalty heroes2x.agg, or a previous fh2_studio
        overlay) so nothing already present is lost. If ``existing_entries``
        is None, the result contains just the pending replacements — no
        original-game data is duplicated into it.
        """
        merged: "OrderedDict[str, bytes]" = OrderedDict(existing_entries) if existing_entries else OrderedDict()
        for name, data in self._pending.items():
            merged[name] = data
        return build_agg(merged.items())

    # ------------------------------------------------------------------
    # Mod packages (.fh2mod) — portable, shareable, re-editable bundles
    #
    # Distinct from build_overlay_bytes()/save(): those produce game-ready
    # AGG bytes for ONE install. A .fh2mod is just the staged *changes*
    # themselves (raw entry bytes + replacement music + a manifest), meant
    # to be reopened later, handed to someone else, or kept under version
    # control — independent of any particular fheroes2 install.
    # ------------------------------------------------------------------

    MOD_PACKAGE_FORMAT_VERSION: ClassVar[int] = 1

    def export_mod_package(self, out_path: str, name: str,
                            author: str = "", description: str = "") -> list[str]:
        """Write every currently staged replacement to a single .fh2mod zip."""
        log: list[str] = []
        manifest: dict = {
            "format_version": self.MOD_PACKAGE_FORMAT_VERSION,
            "name": name,
            "author": author,
            "description": description,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "agg_entries": [],
            "music_tracks": [],
        }

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry_name, data in self._pending.items():
                arc_name = f"assets/agg/{entry_name}"
                zf.writestr(arc_name, data)
                manifest["agg_entries"].append({"name": entry_name, "asset_file": arc_name})
                log.append(f"  + {entry_name} ({len(data):,} bytes)")

            for mt in self.music_tracks:
                if mt.replaced and mt.replacement_path and os.path.isfile(mt.replacement_path):
                    ext = os.path.splitext(mt.replacement_path)[1] or ".ogg"
                    safe_name = f"track_{mt.track.track_id}{ext}"
                    arc_name = f"assets/music/{safe_name}"
                    zf.write(mt.replacement_path, arc_name)
                    manifest["music_tracks"].append({
                        "track_id": mt.track.track_id,
                        "enum_name": mt.track.enum_name,
                        "asset_file": arc_name,
                    })
                    log.append(f"  + music: {mt.track.friendly_name} ({safe_name})")

            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        total = len(manifest["agg_entries"]) + len(manifest["music_tracks"])
        log.append(f"Wrote {out_path} — {total} staged change(s) packaged")
        return log

    def import_mod_package(self, in_path: str) -> list[str]:
        """Load a .fh2mod package and stage all its replacements onto this
        (already-open) project. Writes nothing to disk by itself — follow up
        with build_overlay_bytes()/save() as usual once you're ready to apply.
        """
        log: list[str] = []
        if not self.is_open():
            log.append("ERROR: open an AGG before importing a mod package.")
            return log

        with zipfile.ZipFile(in_path, "r") as zf:
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except KeyError:
                log.append("ERROR: not a valid .fh2mod file (missing manifest.json).")
                return log

            fmt = manifest.get("format_version", 0)
            if fmt > self.MOD_PACKAGE_FORMAT_VERSION:
                log.append(
                    f"WARNING: package format v{fmt} is newer than this tool's "
                    f"v{self.MOD_PACKAGE_FORMAT_VERSION}; some data may be skipped."
                )

            mod_name = manifest.get("name") or "(unnamed)"
            log.append(f'Importing mod "{mod_name}" by {manifest.get("author") or "unknown"}')

            for entry in manifest.get("agg_entries", []):
                name = entry.get("name", "")
                arc_name = entry.get("asset_file", "")
                if not name or not arc_name:
                    continue
                try:
                    data = zf.read(arc_name)
                except KeyError:
                    log.append(f"  ! missing asset for {name}, skipped")
                    continue
                self._pending[name] = data
                self._refresh_asset(name)
                note = "" if name in self._entries else "  [not present in the currently open AGG]"
                log.append(f"  + staged {name} ({len(data):,} bytes){note}")

            music_entries = manifest.get("music_tracks", [])
            if music_entries:
                cache_dir = tempfile.mkdtemp(prefix="fh2studio_import_")
                for entry in music_entries:
                    track_id = entry.get("track_id")
                    arc_name = entry.get("asset_file", "")
                    if track_id is None or not arc_name:
                        continue
                    match = next((mt for mt in self.music_tracks
                                  if mt.track.track_id == track_id), None)
                    if match is None:
                        log.append(f"  ! unknown music track_id={track_id}, skipped")
                        continue
                    try:
                        data = zf.read(arc_name)
                    except KeyError:
                        log.append(f"  ! missing music asset for track {track_id}, skipped")
                        continue
                    dest = os.path.join(cache_dir, os.path.basename(arc_name))
                    with open(dest, "wb") as f:
                        f.write(data)
                    self.stage_music_replacement(match.track, dest)
                    log.append(f"  + staged music: {match.track.friendly_name}")

        return log

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, out_path: str, music_out_dir: str = "") -> list[str]:
        """Write a patched AGG to ``out_path`` and copy music replacements.

        Returns a list of human-readable status lines for the GUI log.
        """
        log: list[str] = []

        # Build patched entry dict
        patched = OrderedDict(self._entries)
        for name, data in self._pending.items():
            patched[name] = data
            log.append(f"  Replaced {name} ({len(self._entries.get(name,b''))} → {len(data)} bytes)")

        new_agg = build_agg(patched.items())
        with open(out_path, "wb") as f:
            f.write(new_agg)
        log.append(f"Wrote {out_path} ({len(new_agg):,} bytes, {len(patched)} entries)")

        log.extend(self.save_music(music_out_dir))
        return log

    def save_music(self, music_out_dir: str) -> list[str]:
        """Copy any staged music replacements into ``music_out_dir``.

        Split out from ``save()`` so callers that build a HEROES2X.AGG
        overlay (rather than a full patched AGG) can still perform the
        music-copy step on its own.
        """
        log: list[str] = []
        if not music_out_dir:
            return log
        os.makedirs(music_out_dir, exist_ok=True)
        for mt in self.music_tracks:
            if mt.replaced and mt.replacement_path:
                ext = os.path.splitext(mt.replacement_path)[1]
                dest_name = mt.track.mapped_name(ext)
                dest = os.path.join(music_out_dir, dest_name)
                shutil.copy2(mt.replacement_path, dest)
                mt.installed_path = dest
                mt.replaced = False
                log.append(f"  Music: copied {dest_name}")
        return log

    # ------------------------------------------------------------------
    # Internal indexing
    # ------------------------------------------------------------------

    def _section_for_icn(self, icn_name: str) -> str:
        base = icn_name.upper().replace(".ICN", "")
        for section, prefixes in ICN_SECTIONS.items():
            if section == "Other":
                continue
            for prefix in prefixes:
                if base.startswith(prefix.upper()):
                    return section
        return "Other"

    def _friendly_for_icn(self, icn_name: str) -> str:
        return icn_name  # can be enriched later

    def _index_assets(self) -> None:
        self.assets = []
        for name, data in self._entries.items():
            upper = name.upper()
            if upper == "KB.PAL":
                atype = AssetType.PALETTE
                section = "Palette"
                friendly = "Game Palette (KB.PAL)"
            elif upper.endswith(".ICN"):
                atype = AssetType.SPRITE
                section = self._section_for_icn(name)
                friendly = name
            elif upper.endswith(".82M"):
                atype = AssetType.SOUND
                info = SOUND_INFO.get(name.upper(), (name, "Other"))
                section = f"Sound / {info[1]}"
                friendly = f"{info[0]} ({name})"
            else:
                atype = AssetType.OTHER
                section = "Other"
                friendly = name

            self.assets.append(AssetEntry(
                name=name,
                atype=atype,
                section=section,
                friendly=friendly,
                size=len(data),
                replaced=False,
            ))

    def _index_music(self, music_dir: str) -> None:
        self.music_tracks = []
        for track in MUSIC_CATALOGUE:
            installed = track.find_in_dir(music_dir) if music_dir else None
            self.music_tracks.append(MusicEntry(track=track, installed_path=installed))

    def _refresh_asset(self, entry_name: str) -> None:
        for a in self.assets:
            if a.name == entry_name:
                a.replaced = entry_name in self._pending
                a.replacement_path = self._pending.get(entry_name, "")  # type: ignore[arg-type]
                a.size = len(self.raw_bytes(entry_name))
                break
