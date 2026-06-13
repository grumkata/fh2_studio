"""
fh2agg.music — music track catalogue and filename helpers.

Track data ported verbatim from fheroes2's mus.cpp musmap[] array.
The engine looks for music files in <data_dir>/music/ under three naming
schemes (tried in priority order):

  MAPPED      "02 Battle 1.ogg"        (track_num + space + friendly_name)
  DOS_VERSION "homm2_01.ogg"           (trackId-1, zero-padded)
  WIN_VERSION "Track02.ogg"            (trackId, zero-padded)

Any of .ogg / .mp3 / .flac / .wav works.  fheroes2 accepts whatever SDL_mixer
is compiled with — usually ogg and mp3 at minimum.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MusicTrack:
    track_id: int           # 1-based track number as stored in the enum
    enum_name: str          # C++ enum name, e.g. "BATTLE1"
    friendly_name: str      # from musmap[], e.g. "Battle 1"

    # ---- filename helpers ----

    def mapped_name(self, ext: str = ".ogg") -> str:
        """E.g. '02 Battle 1.ogg'"""
        return f"{self.track_id:02d} {self.friendly_name}{ext}"

    def dos_name(self, ext: str = ".ogg") -> str:
        """E.g. 'homm2_01.ogg'"""
        return f"homm2_{self.track_id - 1:02d}{ext}"

    def win_name(self, ext: str = ".ogg") -> str:
        """E.g. 'Track02.ogg'"""
        return f"Track{self.track_id:02d}{ext}"

    def all_candidate_names(self, exts: tuple[str, ...] = (".ogg", ".mp3", ".flac", ".wav")) -> list[str]:
        """All filenames the engine might accept for this track."""
        names = []
        for ext in exts:
            names.append(self.mapped_name(ext))
            names.append(self.dos_name(ext))
            names.append(self.win_name(ext))
        return names

    def find_in_dir(self, music_dir: str, exts: tuple[str, ...] = (".ogg", ".mp3", ".flac", ".wav")) -> str | None:
        """Return the absolute path to this track's file if it exists in
        ``music_dir``, or None if it isn't there (not yet installed)."""
        for name in self.all_candidate_names(exts):
            path = os.path.join(music_dir, name)
            if os.path.isfile(path):
                return path
        return None


# Full catalogue — track_id matches the C++ enum value (1-based, skipping 0=UNUSED)
MUSIC_CATALOGUE: list[MusicTrack] = [
    MusicTrack(2,  "BATTLE1",                  "Battle 1"),
    MusicTrack(3,  "BATTLE2",                  "Battle 2"),
    MusicTrack(4,  "BATTLE3",                  "Battle 3"),
    MusicTrack(5,  "SORCERESS_CASTLE",         "Sorceress Castle"),
    MusicTrack(6,  "WARLOCK_CASTLE",           "Warlock Castle"),
    MusicTrack(7,  "NECROMANCER_CASTLE",       "Necromancer Castle"),
    MusicTrack(8,  "KNIGHT_CASTLE",            "Knight Castle"),
    MusicTrack(9,  "BARBARIAN_CASTLE",         "Barbarian Castle"),
    MusicTrack(10, "WIZARD_CASTLE",            "Wizard Castle"),
    MusicTrack(11, "LAVA",                     "Lava Theme"),
    MusicTrack(12, "WASTELAND",                "Wasteland Theme"),
    MusicTrack(13, "DESERT",                   "Desert Theme"),
    MusicTrack(14, "SNOW",                     "Snow Theme"),
    MusicTrack(15, "SWAMP",                    "Swamp Theme"),
    MusicTrack(16, "OCEAN",                    "Ocean Theme"),
    MusicTrack(17, "DIRT",                     "Dirt Theme"),
    MusicTrack(18, "GRASS",                    "Grass Theme"),
    MusicTrack(19, "LOSTGAME",                 "Lost Game"),
    MusicTrack(20, "NEW_WEEK",                 "New Week"),
    MusicTrack(21, "NEW_MONTH",                "New Month"),
    MusicTrack(22, "ARCHIBALD_CAMPAIGN_SCREEN","Archibald Campaign"),
    MusicTrack(23, "PUZZLE",                   "Map Puzzle"),
    MusicTrack(24, "ROLAND_CAMPAIGN_SCREEN",   "Roland Campaign"),
    MusicTrack(28, "COMPUTER_TURN",            "AI Turn"),
    MusicTrack(29, "BATTLEWIN",                "Battle Won"),
    MusicTrack(30, "BATTLELOSE",               "Battle Lost"),
    MusicTrack(31, "DUNGEON",                  "Dungeon"),
    MusicTrack(32, "WATERSPRING",              "Waterspring"),
    MusicTrack(33, "ARABIAN",                  "Arabian"),
    MusicTrack(34, "HILLFORT",                 "Hillfort"),
    MusicTrack(35, "TREEHOUSE",                "Treehouse"),
    MusicTrack(36, "DEMONCAVE",                "Demoncave"),
    MusicTrack(37, "EXPERIENCE",               "Experience"),
    MusicTrack(38, "SKILL",                    "Skill"),
    MusicTrack(39, "WATCHTOWER",               "Watchtower"),
    MusicTrack(40, "XANADU",                   "Xanadu"),
    MusicTrack(41, "ULTIMATE_ARTIFACT",        "Ultimate Artifact"),
    MusicTrack(42, "MAINMENU",                 "Main Menu"),
    MusicTrack(43, "VICTORY",                  "Scenario Victory"),
]

# ICN sprite sheet groups — maps a friendly "section" name to ICN prefixes
# Used by the GUI to group the asset browser by type
ICN_SECTIONS: dict[str, list[str]] = {
    "Creatures (Combat)": [
        "TROLL", "CYCLOPS", "GRIFFIN", "SKELETON", "VAMPIRE", "UNICORN",
        "DRAGON", "PHOENIX", "HYDRA", "GOLEM", "GENIE", "GHOST", "ZOMBIE",
        "LICH", "MUMMY", "MEDUSA", "MINOTAUR", "NOMAD", "GOBLIN", "ELF",
        "DWARF", "PEASANT", "ARCHER", "PIKEMAN", "SWORDSMN", "MONK",
        "CAVALRYD", "PALADIN", "MAGE", "ARCHMAGE", "TITAN", "ROC", "TROLL2",
        "BOAR", "CENTAUR", "GARGOYLE", "HALFLNG", "WOLF", "SCORP",
        "HALFDRG", "BDRAGON", "GRDRAGON",
    ],
    "Hero Portraits (Large)": ["PORT"],
    "Hero Portraits (Small)": ["MINIPORT", "MINIHERO"],
    "Adventure Map Creature Icons": ["MONH"],
    "Town Screens": ["TWNB", "TWNK", "TWNN", "TWNS", "TWNW", "TWNZ"],
    "Castle Backgrounds": ["CASTBKG", "CASTLEB", "CASTLEK", "CASTLEN",
                            "CASTLES", "CASTLEW", "CASTLEZ"],
    "UI / Buttons": ["ADVBORD", "ADVBTNS", "ADVMCO", "HSICONS", "BUTTON",
                     "SMALLBAR", "SWAPBTN", "SCROLL"],
    "Artifacts": ["ARTIFACT", "ARTFX", "ART32"],
    "Spells": ["SPELLS", "SPELLINL"],
    "Combat Backgrounds": ["CBKG"],
    "Flags & Colors": ["FLAG32", "CREST32"],
    "Other": [],   # catch-all
}
