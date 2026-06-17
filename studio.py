#!/usr/bin/env python3
"""
fh2 Studio — a mod tool for Heroes of Might & Magic II / fheroes2.

Run this file directly:   python3 studio.py
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ── make sure the sibling fh2agg package is importable ─────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageTk                                   # noqa: E402
from fh2agg.aggfile import AggFormatError, build_agg, parse_agg     # noqa: E402
from fh2agg.icn import (ICNHeader, build_icn, decode_sprite,    # noqa: E402
                          encode_sprite, parse_icn)
from fh2agg.palette import NearestColorMatcher, load_palette     # noqa: E402
from fh2agg.pngconvert import images_to_sprite, sprite_to_images # noqa: E402
from fh2agg.project import AssetType, Project                    # noqa: E402
from fh2agg.sound import m82_to_wav_bytes, wav_bytes_to_m82      # noqa: E402

# ── optional pygame for audio playback ─────────────────────────────────────
try:
    import pygame
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
    _AUDIO_OK = True
except Exception:
    _AUDIO_OK = False

# ── colours ────────────────────────────────────────────────────────────────
C_BG        = "#1a1a2e"
C_PANEL     = "#16213e"
C_ACCENT    = "#e94560"
C_ACCENT2   = "#0f3460"
C_TEXT      = "#eaeaea"
C_SUBTEXT   = "#8888aa"
C_REPLACED  = "#2ecc71"
C_HOVER     = "#253060"
C_BORDER    = "#2a2a4a"
C_BTN       = "#0f3460"
C_BTN_ACT   = "#e94560"

FONT_TITLE  = ("Helvetica", 14, "bold")
FONT_BODY   = ("Helvetica", 10)
FONT_SMALL  = ("Helvetica", 9)
FONT_MONO   = ("Courier", 9)

CHECKER_DARK  = (100, 100, 120)
CHECKER_LIGHT = (140, 140, 160)
CHECKER_SIZE  = 8
PREVIEW_SIZE  = 256      # preview panel size in pixels

# ── fheroes2 install auto-detection ────────────────────────────────────────

def _fheroes2_candidates() -> list[str]:
    """Return an ordered list of directories where fheroes2 might be installed."""
    import platform
    dirs: list[str] = []
    sys_name = platform.system()

    if sys_name == "Windows":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(env, "")
            if base:
                dirs.append(os.path.join(base, "fheroes2"))
        appdata = os.environ.get("LOCALAPPDATA", "")
        if appdata:
            dirs.append(os.path.join(appdata, "fheroes2"))
        # GOG / Steam installs
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env, "")
            if base:
                dirs.append(os.path.join(base, "GOG Games", "HoMM 2 Gold", "fheroes2"))
                dirs.append(os.path.join(base, "Steam", "steamapps", "common", "fheroes2"))
    elif sys_name == "Darwin":
        dirs += [
            os.path.expanduser("~/Library/Application Support/fheroes2"),
            "/Applications/fheroes2.app/Contents/Resources",
        ]
    else:  # Linux / BSD / etc.
        dirs += [
            os.path.expanduser("~/.local/share/fheroes2"),
            "/usr/local/share/fheroes2",
            "/usr/share/fheroes2",
            "/opt/fheroes2",
        ]

    # Also check next to the studio script itself (portable layout)
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    return dirs


def _find_fheroes2_dir() -> str | None:
    """Return the first fheroes2 install directory that contains data/HEROES2.AGG, or None."""
    for d in _fheroes2_candidates():
        if os.path.isfile(os.path.join(d, "data", "HEROES2.AGG")):
            return d
    return None


def _music_dir_for_agg(agg_path: str) -> str:
    """Find the music directory for a given AGG path.

    Checks (in order):
      1. <agg_dir>/music/          — when AGG is at the install root
      2. <parent_of_agg_dir>/music/ — when AGG is inside a data/ sub-folder (fheroes2 layout)
      3. <agg_dir>/Music/          — case-variant
      4. <parent_of_agg_dir>/Music/
    """
    agg_dir = os.path.dirname(agg_path)
    parent   = os.path.dirname(agg_dir)
    for candidate in (
        os.path.join(agg_dir, "music"),
        os.path.join(parent,  "music"),
        os.path.join(agg_dir, "Music"),
        os.path.join(parent,  "Music"),
    ):
        if os.path.isdir(candidate):
            return candidate
    return ""


# ── HEROES2X.AGG overlay helpers ────────────────────────────────────────────
# fheroes2 looks for a second AGG file next to the main one: it lowercases
# the main AGG's path, replaces the trailing ".agg" with "x.agg", and looks
# for any other .agg file in the same folder whose lowercased path matches
# exactly. If found AND it opens successfully, the engine treats Price of
# Loyalty as installed (Settings::EnablePriceOfLoyaltySupport(true)) and
# checks this file FIRST for every asset lookup, falling back to the main
# AGG only if an entry isn't there. Verified directly against fheroes2's
# AGG::AGGInitializer::init() in src/fheroes2/agg/agg.cpp.

def _overlay_filename_for(base_agg_path: str) -> str:
    """Return the conventional overlay filename for a given base AGG path,
    e.g. 'HEROES2.AGG' -> 'HEROES2X.AGG' (case pattern preserved)."""
    base = os.path.basename(base_agg_path)
    stem, ext = os.path.splitext(base)
    suffix = "X" if stem == stem.upper() else "x"
    return f"{stem}{suffix}{ext}"


def _find_existing_overlay(data_dir: str, base_agg_path: str) -> str | None:
    """Search data_dir for an existing overlay AGG using fheroes2's exact
    case-insensitive matching rule. Returns the real on-disk path (with its
    real casing) if found, else None."""
    if not os.path.isdir(data_dir):
        return None
    base_lower = os.path.basename(base_agg_path).lower()
    if not base_lower.endswith(".agg"):
        return None
    target_lower = base_lower[: -len(".agg")] + "x.agg"
    try:
        for fname in os.listdir(data_dir):
            if fname.lower() == target_lower:
                return os.path.join(data_dir, fname)
    except OSError:
        pass
    return None


def _ask_three_way(parent: tk.Tk, title: str, message: str,
                    opt1: str, opt2: str, cancel: str = "Cancel") -> str | None:
    """Modal dialog with three clearly-labelled buttons.

    Returns "opt1", "opt2", or None if cancelled / closed.
    Used instead of messagebox.askyesnocancel because its generic
    Yes/No/Cancel labels are too easy to misread for a risky choice.
    """
    result: dict[str, str | None] = {"value": None}

    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=C_BG)
    win.transient(parent)
    win.resizable(False, False)

    body = tk.Frame(win, bg=C_BG, padx=20, pady=16)
    body.pack(fill="both", expand=True)

    tk.Label(body, text=title, bg=C_BG, fg=C_TEXT, font=FONT_TITLE,
              anchor="w", justify="left").pack(fill="x", pady=(0, 8))
    tk.Label(body, text=message, bg=C_BG, fg=C_SUBTEXT, font=FONT_BODY,
              anchor="w", justify="left", wraplength=420).pack(fill="x", pady=(0, 16))

    btn_row = tk.Frame(body, bg=C_BG)
    btn_row.pack(fill="x")

    def choose(value: str | None) -> None:
        result["value"] = value
        win.destroy()

    tk.Button(btn_row, text=opt1, command=lambda: choose("opt1"),
               bg=C_ACCENT2, fg=C_TEXT, activebackground=C_ACCENT,
               relief="flat", padx=10, pady=6).pack(fill="x", pady=2)
    tk.Button(btn_row, text=opt2, command=lambda: choose("opt2"),
               bg=C_PANEL, fg=C_TEXT, activebackground=C_BORDER,
               relief="flat", padx=10, pady=6).pack(fill="x", pady=2)
    tk.Button(btn_row, text=cancel, command=lambda: choose(None),
               bg=C_PANEL, fg=C_SUBTEXT, activebackground=C_BORDER,
               relief="flat", padx=10, pady=6).pack(fill="x", pady=(2, 0))

    win.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    win.update_idletasks()
    # Centre over the parent window
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    ww, wh = win.winfo_width(), win.winfo_height()
    win.geometry(f"+{px + (pw - ww)//2}+{py + (ph - wh)//2}")

    win.grab_set()
    win.wait_window()
    return result["value"]


def _checker_bg(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    pix = img.load()
    for y in range(size):
        for x in range(size):
            c = CHECKER_LIGHT if (x // CHECKER_SIZE + y // CHECKER_SIZE) % 2 == 0 else CHECKER_DARK
            pix[x, y] = c
    return img


def _composite_on_checker(rgba: Image.Image, max_size: int = PREVIEW_SIZE) -> Image.Image:
    """Scale RGBA to fit max_size×max_size, composite on a checker background."""
    w, h = rgba.size
    scale = min(max_size / max(w, 1), max_size / max(h, 1), 8.0)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    scaled = rgba.resize((new_w, new_h), Image.NEAREST)
    bg = _checker_bg(max_size)
    ox = (max_size - new_w) // 2
    oy = (max_size - new_h) // 2
    bg.paste(scaled, (ox, oy), scaled)
    return bg


def _composite_on_solid(rgba: Image.Image, color: str,
                        max_size: int = PREVIEW_SIZE) -> Image.Image:
    """Scale RGBA to fit max_size×max_size and composite on a solid colour background.

    ``color`` may be ``'black'``, ``'white'``, ``'green'`` (terrain-like), or any
    PIL colour string.
    """
    bg_colours = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "green": (82, 154, 76),   # typical HOMM2 grass colour
    }
    rgb = bg_colours.get(color, (0, 0, 0))
    w, h = rgba.size
    scale = min(max_size / max(w, 1), max_size / max(h, 1), 8.0)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    scaled = rgba.resize((new_w, new_h), Image.NEAREST)
    bg = Image.new("RGB", (max_size, max_size), rgb)
    ox = (max_size - new_w) // 2
    oy = (max_size - new_h) // 2
    bg.paste(scaled, (ox, oy), scaled)
    return bg


def _fit_user_image(user_rgba: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Scale user image to target dimensions using high-quality resampling,
    preserving aspect ratio with transparent padding."""
    user_rgba = user_rgba.convert("RGBA")
    scale = min(target_w / max(user_rgba.width, 1), target_h / max(user_rgba.height, 1))
    new_w = max(1, int(user_rgba.width * scale))
    new_h = max(1, int(user_rgba.height * scale))
    resized = user_rgba.resize((new_w, new_h), Image.LANCZOS)
    out = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ox = (target_w - new_w) // 2
    oy = (target_h - new_h) // 2
    out.paste(resized, (ox, oy))
    return out


# ════════════════════════════════════════════════════════════════════════════
# Main application window
# ════════════════════════════════════════════════════════════════════════════

class Studio(tk.Tk):

    def __init__(self) -> None:
        super().__init__()

        self.title("fh2 Studio — HoMM2 Mod Tool")
        self.configure(bg=C_BG)
        self.geometry("1280x820")
        self.minsize(960, 640)

        self.project = Project()
        self._fheroes2_dir: str = ""
        self._music_playing  = False
        self._music_paused   = False
        self._music_duration = 0.0
        self._sel_asset = None
        self._sel_music = None
        self._sel_sprite_idx = 0
        self._bg_mode        = "checker"   # cycles: checker → black → white → green
        self._frame_rgba_cache: dict = {}   # idx -> decoded RGBA, cleared per ICN load
        self._anim_playing   = False
        self._anim_after_id  = None
        self._anim_range     = (0, 0)
        self._anim_loop      = True
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._import_photo:  ImageTk.PhotoImage | None = None
        self._audio_thread: threading.Thread | None = None

        self._build_ui()
        self._apply_styles()
        self.after(200, self._tick)   # start music progress heartbeat

    # ────────────────────────────────────────────────────────────────────────
    # UI construction
    # ────────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── top bar ─────────────────────────────────────────────────────────
        top = tk.Frame(self, bg=C_ACCENT2, height=48)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        tk.Label(top, text="⚔  fh2 Studio", bg=C_ACCENT2, fg=C_TEXT,
                 font=FONT_TITLE).pack(side="left", padx=14, pady=8)

        btn_frame = tk.Frame(top, bg=C_ACCENT2)
        btn_frame.pack(side="right", padx=8)
        self._btn("Connect fheroes2", self._connect_fheroes2, btn_frame, accent=True)
        self._btn("Open AGG…",        self._open_agg,         btn_frame, accent=False)
        self._btn("Apply Mod",        self._apply_mod,        btn_frame, accent=True)
        self._btn("Restore…",         self._restore_mods,     btn_frame, accent=False)
        self._btn("Save Mod…",        self._save_mod,         btn_frame, accent=False)

        # ── status bar ──────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="No file open — use 'Open AGG…' to load HEROES2.AGG")
        status = tk.Label(self, textvariable=self._status_var, bg=C_PANEL,
                          fg=C_SUBTEXT, font=FONT_SMALL, anchor="w", padx=8, pady=3)
        status.pack(fill="x", side="bottom")

        # ── main paned layout ───────────────────────────────────────────────
        paned = tk.PanedWindow(self, orient="horizontal", bg=C_BG,
                               sashwidth=4, sashrelief="flat", bd=0)
        paned.pack(fill="both", expand=True)

        # Left: asset browser
        left = tk.Frame(paned, bg=C_PANEL, width=310)
        paned.add(left, minsize=220)
        self._build_browser(left)

        # Centre: detail / edit panel
        centre = tk.Frame(paned, bg=C_BG)
        paned.add(centre, minsize=400)
        self._build_detail(centre)

        # Right: log
        right = tk.Frame(paned, bg=C_PANEL, width=220)
        paned.add(right, minsize=160)
        self._build_log(right)

    def _btn(self, text: str, cmd, parent: tk.Widget, accent: bool = False) -> tk.Button:
        bg = C_BTN_ACT if accent else C_BTN
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=C_TEXT,
                      font=FONT_SMALL, relief="flat", padx=10, pady=4,
                      activebackground=C_ACCENT, activeforeground=C_TEXT,
                      cursor="hand2", bd=0)
        b.pack(side="left", padx=4, pady=6)
        return b

    # ── asset browser ────────────────────────────────────────────────────────

    def _build_browser(self, parent: tk.Frame) -> None:
        hdr = tk.Frame(parent, bg=C_PANEL)
        hdr.pack(fill="x", padx=6, pady=(8, 2))
        tk.Label(hdr, text="Assets", bg=C_PANEL, fg=C_TEXT,
                 font=FONT_TITLE).pack(side="left")

        # Search
        sf = tk.Frame(parent, bg=C_PANEL)
        sf.pack(fill="x", padx=6, pady=(0, 4))
        tk.Label(sf, text="🔍", bg=C_PANEL, fg=C_SUBTEXT).pack(side="left")
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._filter_tree())
        entry = tk.Entry(sf, textvariable=self._search_var, bg=C_ACCENT2, fg=C_TEXT,
                         insertbackground=C_TEXT, relief="flat", font=FONT_SMALL)
        entry.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Tab switcher
        tab_frame = tk.Frame(parent, bg=C_PANEL)
        tab_frame.pack(fill="x", padx=6, pady=(0, 2))
        self._browser_tab = tk.StringVar(value="sprites")
        for val, label in [("sprites", "Graphics"), ("sounds", "Sounds"), ("music", "Music")]:
            tk.Radiobutton(tab_frame, text=label, variable=self._browser_tab,
                           value=val, command=self._switch_browser_tab,
                           bg=C_PANEL, fg=C_TEXT, selectcolor=C_ACCENT2,
                           activebackground=C_PANEL, activeforeground=C_ACCENT,
                           font=FONT_SMALL, indicatoron=False, relief="flat",
                           padx=8, pady=2).pack(side="left", padx=1)

        # Treeview for sprites/sounds
        tree_frame = tk.Frame(parent, bg=C_PANEL)
        tree_frame.pack(fill="both", expand=True, padx=4, pady=2)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
                         background=C_BG, fieldbackground=C_BG,
                         foreground=C_TEXT, font=FONT_SMALL,
                         rowheight=22, borderwidth=0)
        style.configure("Dark.Treeview.Heading",
                         background=C_ACCENT2, foreground=C_TEXT,
                         font=FONT_SMALL, borderwidth=0)
        style.map("Dark.Treeview",
                  background=[("selected", C_HOVER)],
                  foreground=[("selected", C_ACCENT)])

        self._tree = ttk.Treeview(tree_frame, style="Dark.Treeview",
                                   selectmode="browse", show="tree")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.tag_configure("replaced", foreground=C_REPLACED)

        # Music list (shown when music tab active)
        mf = tk.Frame(parent, bg=C_PANEL)
        self._music_list_frame = mf
        self._music_listbox = tk.Listbox(mf, bg=C_BG, fg=C_TEXT,
                                          selectbackground=C_HOVER,
                                          selectforeground=C_ACCENT,
                                          font=FONT_SMALL, relief="flat",
                                          activestyle="none")
        ml_vsb = ttk.Scrollbar(mf, orient="vertical",
                                 command=self._music_listbox.yview)
        self._music_listbox.configure(yscrollcommand=ml_vsb.set)
        ml_vsb.pack(side="right", fill="y")
        self._music_listbox.pack(fill="both", expand=True)
        self._music_listbox.bind("<<ListboxSelect>>", self._on_music_select)

    # ── detail / edit panel ──────────────────────────────────────────────────

    def _build_detail(self, parent: tk.Frame) -> None:
        # Title
        self._detail_title = tk.Label(parent, text="Select an asset to begin",
                                       bg=C_BG, fg=C_TEXT, font=FONT_TITLE,
                                       anchor="w")
        self._detail_title.pack(fill="x", padx=12, pady=(10, 0))
        self._detail_sub = tk.Label(parent, text="",
                                     bg=C_BG, fg=C_SUBTEXT, font=FONT_SMALL,
                                     anchor="w")
        self._detail_sub.pack(fill="x", padx=12, pady=(0, 6))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=8, pady=2)

        # Main content area (notebook for sprite / sound / music views)
        self._nb = ttk.Notebook(parent, style="Dark.TNotebook")
        style = ttk.Style()
        style.configure("Dark.TNotebook", background=C_BG, borderwidth=0)
        style.configure("Dark.TNotebook.Tab", background=C_ACCENT2,
                         foreground=C_TEXT, padding=[10, 4])
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", C_ACCENT)],
                  foreground=[("selected", "white")])
        self._nb.pack(fill="both", expand=True, padx=8, pady=4)

        self._build_sprite_tab()
        self._build_sound_tab()
        self._build_music_tab()
        self._build_info_tab()

    def _build_sprite_tab(self) -> None:
        f = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(f, text="  Sprite  ")
        self._sprite_tab = f

        # Two-column layout: original left, import right
        cols = tk.Frame(f, bg=C_BG)
        cols.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Original preview ---
        orig = tk.LabelFrame(cols, text=" Original ", bg=C_BG, fg=C_SUBTEXT,
                              font=FONT_SMALL, relief="flat", bd=1,
                              highlightbackground=C_BORDER)
        orig.pack(side="left", fill="both", expand=True, padx=(0, 4))

        # Dimensions shown large and prominently at the top
        self._dim_label = tk.Label(orig, text="—",
                                    bg=C_BG, fg=C_ACCENT,
                                    font=("Courier New", 13, "bold"),
                                    anchor="center")
        self._dim_label.pack(fill="x", padx=8, pady=(6, 2))

        self._orig_canvas = tk.Canvas(orig, width=PREVIEW_SIZE, height=PREVIEW_SIZE,
                                       bg="#0d0d1a", highlightthickness=0)
        self._orig_canvas.pack(padx=8, pady=8)

        # Frame navigator
        fnav = tk.Frame(orig, bg=C_BG)
        fnav.pack(pady=(0, 6))
        tk.Button(fnav, text="◀", command=self._prev_sprite,
                  bg=C_BTN, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=8, cursor="hand2").pack(side="left")
        self._frame_label = tk.Label(fnav, text="Frame 0/0", bg=C_BG,
                                      fg=C_SUBTEXT, font=FONT_SMALL, width=14)
        self._frame_label.pack(side="left", padx=6)
        tk.Button(fnav, text="▶", command=self._next_sprite,
                  bg=C_BTN, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=8, cursor="hand2").pack(side="left")

        self._sprite_info = tk.Label(orig, text="", bg=C_BG, fg=C_SUBTEXT,
                                      font=FONT_MONO, justify="left")
        self._sprite_info.pack(padx=8, pady=(0, 4), anchor="w")

        self._btn("Export frame as PNG…", self._export_sprite_png, orig)
        self._bg_btn = self._btn("BG: Checker", self._cycle_bg, orig)

        # --- Animation playback ---
        anim = tk.LabelFrame(orig, text=" Animate ", bg=C_BG, fg=C_SUBTEXT,
                              font=FONT_SMALL, relief="flat", bd=1,
                              highlightbackground=C_BORDER)
        anim.pack(fill="x", padx=8, pady=(4, 8))

        range_row = tk.Frame(anim, bg=C_BG)
        range_row.pack(fill="x", padx=6, pady=(6, 3))
        tk.Label(range_row, text="From", bg=C_BG, fg=C_SUBTEXT,
                 font=FONT_SMALL).pack(side="left")
        self._anim_from_var = tk.IntVar(value=0)
        self._anim_from_spin = tk.Spinbox(
            range_row, from_=0, to=0, width=4, textvariable=self._anim_from_var,
            bg=C_ACCENT2, fg=C_TEXT, insertbackground=C_TEXT, buttonbackground=C_PANEL,
            relief="flat", font=FONT_SMALL, justify="center")
        self._anim_from_spin.pack(side="left", padx=(4, 12))

        tk.Label(range_row, text="To", bg=C_BG, fg=C_SUBTEXT,
                 font=FONT_SMALL).pack(side="left")
        self._anim_to_var = tk.IntVar(value=0)
        self._anim_to_spin = tk.Spinbox(
            range_row, from_=0, to=0, width=4, textvariable=self._anim_to_var,
            bg=C_ACCENT2, fg=C_TEXT, insertbackground=C_TEXT, buttonbackground=C_PANEL,
            relief="flat", font=FONT_SMALL, justify="center")
        self._anim_to_spin.pack(side="left", padx=(4, 12))

        tk.Button(range_row, text="All Frames", command=self._anim_select_all,
                  bg=C_BTN, fg=C_TEXT, relief="flat", font=FONT_SMALL,
                  padx=8, cursor="hand2").pack(side="left")

        opt_row = tk.Frame(anim, bg=C_BG)
        opt_row.pack(fill="x", padx=6, pady=(0, 6))
        tk.Label(opt_row, text="FPS", bg=C_BG, fg=C_SUBTEXT,
                 font=FONT_SMALL).pack(side="left")
        self._anim_fps_var = tk.IntVar(value=8)
        self._anim_fps_spin = tk.Spinbox(
            opt_row, from_=1, to=60, width=4, textvariable=self._anim_fps_var,
            bg=C_ACCENT2, fg=C_TEXT, insertbackground=C_TEXT, buttonbackground=C_PANEL,
            relief="flat", font=FONT_SMALL, justify="center")
        self._anim_fps_spin.pack(side="left", padx=(4, 14))

        self._anim_loop_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt_row, text="Loop", variable=self._anim_loop_var,
                        bg=C_BG, fg=C_TEXT, selectcolor=C_PANEL,
                        activebackground=C_BG, activeforeground=C_TEXT,
                        font=FONT_SMALL).pack(side="left")

        self._anim_play_btn = self._btn("▶  Play Animation", self._toggle_anim_play,
                                         anim, accent=True)

        # --- Import / replace side ---
        imp = tk.LabelFrame(cols, text=" Replace With ", bg=C_BG, fg=C_SUBTEXT,
                             font=FONT_SMALL, relief="flat", bd=1,
                             highlightbackground=C_BORDER)
        imp.pack(side="left", fill="both", expand=True, padx=(4, 0))

        self._import_canvas = tk.Canvas(imp, width=PREVIEW_SIZE, height=PREVIEW_SIZE,
                                         bg="#0d0d1a", highlightthickness=0)
        self._import_canvas.pack(padx=8, pady=8)

        self._import_label = tk.Label(imp, text="No file selected",
                                       bg=C_BG, fg=C_SUBTEXT, font=FONT_SMALL)
        self._import_label.pack()

        btn_row = tk.Frame(imp, bg=C_BG)
        btn_row.pack(pady=8)
        self._btn("Browse Image…", self._browse_sprite_import, btn_row)
        self._btn("Apply to This Frame", self._apply_sprite_frame, btn_row, accent=True)

        self._apply_all_btn = self._btn("Apply to ALL Frames", self._apply_sprite_all, btn_row)
        self._import_image: Image.Image | None = None

    def _build_sound_tab(self) -> None:
        f = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(f, text="  Sound  ")
        self._sound_tab = f

        inner = tk.Frame(f, bg=C_BG)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        self._sound_icon = tk.Label(inner, text="🔊", bg=C_BG, fg=C_TEXT,
                                     font=("Helvetica", 48))
        self._sound_icon.pack(pady=(0, 8))

        self._sound_name_label = tk.Label(inner, text="—", bg=C_BG, fg=C_TEXT,
                                           font=FONT_TITLE)
        self._sound_name_label.pack()
        self._sound_size_label = tk.Label(inner, text="", bg=C_BG, fg=C_SUBTEXT,
                                           font=FONT_SMALL)
        self._sound_size_label.pack(pady=2)

        play_row = tk.Frame(inner, bg=C_BG)
        play_row.pack(pady=12)
        self._btn("▶  Play Original", self._play_sound_original, play_row)
        self._btn("▶  Play Replacement", self._play_sound_replacement, play_row)

        self._btn("Browse WAV…", self._browse_sound_import, inner)

        self._sound_import_label = tk.Label(inner, text="No replacement selected",
                                             bg=C_BG, fg=C_SUBTEXT, font=FONT_SMALL)
        self._sound_import_label.pack(pady=4)
        self._btn("Apply Sound Replacement", self._apply_sound, inner, accent=True)

        self._sound_replacement_path: str = ""

    def _build_music_tab(self) -> None:
        f = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(f, text="  Music  ")
        self._music_detail_tab = f

        # ── Track info ──────────────────────────────────────────────────────
        info_frame = tk.Frame(f, bg=C_BG)
        info_frame.pack(fill="x", padx=16, pady=(16, 4))

        tk.Label(info_frame, text="🎵", bg=C_BG, fg=C_TEXT,
                 font=("Helvetica", 32)).pack(side="left", padx=(0, 12))

        text_col = tk.Frame(info_frame, bg=C_BG)
        text_col.pack(side="left", fill="x", expand=True)
        self._music_title_label = tk.Label(text_col, text="Select a track",
                                            bg=C_BG, fg=C_TEXT, font=FONT_TITLE,
                                            anchor="w")
        self._music_title_label.pack(fill="x")
        self._music_status_label = tk.Label(text_col, text="",
                                             bg=C_BG, fg=C_SUBTEXT, font=FONT_SMALL,
                                             anchor="w")
        self._music_status_label.pack(fill="x")

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=12, pady=8)

        # ── Transport controls ──────────────────────────────────────────────
        transport = tk.Frame(f, bg=C_BG)
        transport.pack(pady=4)

        self._play_btn  = self._btn("▶  Play",  self._play_music,  transport, accent=True)
        self._pause_btn = self._btn("⏸  Pause", self._pause_music, transport)
        self._stop_btn  = self._btn("⏹  Stop",  self._stop_music,  transport)

        # ── Progress bar ────────────────────────────────────────────────────
        prog_frame = tk.Frame(f, bg=C_BG)
        prog_frame.pack(fill="x", padx=16, pady=8)

        self._prog_time = tk.Label(prog_frame, text="0:00 / —:——",
                                    bg=C_BG, fg=C_SUBTEXT, font=FONT_MONO,
                                    anchor="w", width=14)
        self._prog_time.pack(side="left")

        # Canvas-based progress bar (works on all tk versions)
        self._prog_canvas = tk.Canvas(prog_frame, bg=C_PANEL, height=8,
                                       highlightthickness=0, bd=0)
        self._prog_canvas.pack(side="left", fill="x", expand=True, padx=8)
        self._prog_canvas.bind("<Button-1>", self._on_prog_click)

        self._prog_fill = self._prog_canvas.create_rectangle(
            0, 0, 0, 8, fill=C_ACCENT, outline=""
        )

        # ── File name info ──────────────────────────────────────────────────
        self._music_names_info = tk.Label(f, text="",
                                           bg=C_BG, fg=C_SUBTEXT,
                                           font=FONT_MONO, justify="left")
        self._music_names_info.pack(padx=16, pady=(0, 8), anchor="w")

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # ── Replace section ─────────────────────────────────────────────────
        rep = tk.Frame(f, bg=C_BG)
        rep.pack(fill="x", padx=16, pady=8)

        tk.Label(rep, text="Replace track:", bg=C_BG, fg=C_SUBTEXT,
                 font=FONT_SMALL).pack(anchor="w")
        self._music_import_label = tk.Label(rep, text="No replacement selected",
                                             bg=C_BG, fg=C_SUBTEXT, font=FONT_SMALL)
        self._music_import_label.pack(anchor="w", pady=2)

        rep_btn = tk.Frame(rep, bg=C_BG)
        rep_btn.pack(anchor="w", pady=4)
        self._btn("Browse Audio…",       self._browse_music_import, rep_btn)
        self._btn("★ Stage Replacement", self._apply_music,         rep_btn, accent=True)

        self._music_replacement_path: str = ""

        # Internal state for the player
        self._music_playing  = False
        self._music_paused   = False
        self._music_duration = 0.0   # seconds; 0 = unknown

    def _build_info_tab(self) -> None:
        f = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(f, text="  Info  ")

        self._info_text = tk.Text(f, bg=C_PANEL, fg=C_TEXT, font=FONT_MONO,
                                   relief="flat", wrap="word", padx=10, pady=10,
                                   state="disabled", insertbackground=C_TEXT)
        vsb = ttk.Scrollbar(f, orient="vertical", command=self._info_text.yview)
        self._info_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._info_text.pack(fill="both", expand=True)

    def _build_log(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Log", bg=C_PANEL, fg=C_TEXT,
                 font=FONT_TITLE).pack(anchor="w", padx=8, pady=(8, 2))
        self._log_text = tk.Text(parent, bg=C_BG, fg=C_SUBTEXT, font=FONT_MONO,
                                  relief="flat", wrap="word", padx=6, pady=6,
                                  state="disabled")
        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _apply_styles(self) -> None:
        style = ttk.Style()
        style.configure("TScrollbar", background=C_ACCENT2, troughcolor=C_BG,
                         borderwidth=0, arrowcolor=C_TEXT)

    # ────────────────────────────────────────────────────────────────────────
    # File operations
    # ────────────────────────────────────────────────────────────────────────

    def _open_agg(self) -> None:
        path = filedialog.askopenfilename(
            title="Open AGG archive",
            filetypes=[("AGG archives", "*.AGG *.agg"), ("All files", "*.*")]
        )
        if not path:
            return
        # Detect music dir relative to the AGG (handles both flat and data/ layouts)
        music_dir = _music_dir_for_agg(path)
        # If AGG lives inside a data/ folder, the parent might be the fheroes2 root
        parent = os.path.dirname(os.path.dirname(path))
        if os.path.isfile(os.path.join(parent, "data", "HEROES2.AGG")):
            self._fheroes2_dir = parent
        try:
            self.project.open(path, music_dir=music_dir)
        except AggFormatError as e:
            messagebox.showerror("Cannot open AGG", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self._log(f"Opened {path}")
        self._log(f"  {len(self.project.assets)} assets indexed")
        if music_dir:
            self._log(f"  Music dir: {music_dir}")
        else:
            self._log("  No music folder found — use 'Set Music Dir…' to locate it")
        self._status_var.set(f"{os.path.basename(path)}  —  {len(self.project.assets)} assets")
        self._populate_browser()

    def _set_music_dir(self) -> None:
        d = filedialog.askdirectory(title="Select music folder (contains .ogg/.mp3 files)")
        if not d:
            return
        if self.project.is_open():
            self.project._music_dir = d
            self.project._index_music(d)
            self._populate_music_list()
            self._log(f"Music dir: {d}")
        self._status_var.set(f"Music folder: {d}")

    def _connect_fheroes2(self) -> None:
        """Auto-detect (or let the user browse for) a fheroes2 install dir,
        then open its HEROES2.AGG and point the music dir at its music/ folder."""
        found = _find_fheroes2_dir()
        if found:
            use = messagebox.askyesno(
                "fheroes2 found",
                f"Found fheroes2 install at:\n{found}\n\nLoad data from here?"
            )
            if not use:
                found = None

        if not found:
            found = filedialog.askdirectory(
                title="Select fheroes2 install folder (the one that contains 'data' and 'music')"
            )
            if not found:
                return
            agg_check = os.path.join(found, "data", "HEROES2.AGG")
            if not os.path.isfile(agg_check):
                messagebox.showerror(
                    "Not found",
                    f"Could not find data/HEROES2.AGG inside:\n{found}"
                )
                return

        self._fheroes2_dir = found
        agg_path  = os.path.join(found, "data", "HEROES2.AGG")
        music_dir = _music_dir_for_agg(agg_path)

        try:
            self.project.open(agg_path, music_dir=music_dir)
        except AggFormatError as e:
            messagebox.showerror("Cannot open AGG", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self._log(f"Connected to fheroes2: {found}")
        self._log(f"  Opened {agg_path}")
        self._log(f"  {len(self.project.assets)} assets indexed")
        if music_dir:
            self._log(f"  Music dir: {music_dir}")
        else:
            self._log("  No music/ folder found inside the install — use 'Set Music Dir…'")
        self._status_var.set(
            f"fheroes2: {os.path.basename(found)}  —  {len(self.project.assets)} assets"
        )
        self._populate_browser()

    def _apply_mod(self) -> None:
        """Apply staged sprite/sound/music changes to the connected fheroes2
        install, preferring a non-destructive HEROES2X.AGG overlay whenever
        it's safe to do so.

        Why not always create an overlay: fheroes2 treats the mere presence
        of a working HEROES2X.AGG as proof Price of Loyalty is installed
        (it flips Settings::EnablePriceOfLoyaltySupport(true), which enables
        the PoL campaign button, PoL-only heroes/artifacts in scenario
        dialogs, etc.) A minimal overlay with just a few replaced sprites
        would trip that flag without having the real expansion's assets
        behind it, breaking those other features for anyone who doesn't
        actually own Price of Loyalty. So: if a real HEROES2X.AGG already
        exists, merging into it is fully safe (that flag was already on).
        If none exists, the user gets an explicit, informed choice instead
        of fh2_studio silently doing something that could break their game.
        """
        if not self.project.is_open():
            messagebox.showinfo("Nothing to apply", "Open or connect an AGG file first.")
            return
        if not self.project.has_pending_changes:
            messagebox.showinfo("Nothing to apply", "No pending changes staged yet.")
            return

        # Resolve the install's data directory from whatever AGG is open.
        base_agg_path = self.project._agg_path
        data_dir = os.path.dirname(base_agg_path)
        if not os.path.isdir(data_dir):
            messagebox.showerror("Error", f"Data folder not found:\n{data_dir}")
            return

        music_dir = self.project._music_dir or _music_dir_for_agg(base_agg_path) \
            or os.path.join(os.path.dirname(data_dir), "music")

        existing_overlay = _find_existing_overlay(data_dir, base_agg_path)
        log_lines: list[str] = []

        if self.project.has_pending_agg_changes:
            if existing_overlay:
                # ---- Safe path: a real overlay (almost certainly Price of
                #      Loyalty) already exists — merge into it. ----
                try:
                    with open(existing_overlay, "rb") as f:
                        existing_bytes = f.read()
                    existing_entries = parse_agg(existing_bytes, verify_hashes=True)
                except Exception as e:
                    messagebox.showerror(
                        "Cannot read existing overlay",
                        f"{existing_overlay}\n\n{e}\n\n"
                        "Fix or remove this file and try again."
                    )
                    return

                if not messagebox.askyesno(
                    "Apply mod",
                    f"Found an existing overlay:\n{existing_overlay}\n"
                    f"({len(existing_entries)} entries — likely Price of Loyalty data)\n\n"
                    f"Your {len(self.project._pending)} change(s) will be merged into it. "
                    "Everything else in that file is left untouched.\n\n"
                    "A one-time backup will be made before the first change. Continue?"
                ):
                    return

                backup_path = existing_overlay + ".bak"
                if not os.path.isfile(backup_path):
                    shutil.copy2(existing_overlay, backup_path)
                    log_lines.append(f"Backup: {backup_path}")

                new_bytes = self.project.build_overlay_bytes(existing_entries)
                with open(existing_overlay, "wb") as f:
                    f.write(new_bytes)
                log_lines.append(
                    f"Merged into overlay: {existing_overlay} "
                    f"({len(existing_entries)} → {len(parse_agg(new_bytes, verify_hashes=False))} entries)"
                )

            else:
                # ---- No overlay exists yet — ask, don't assume. ----
                choice = _ask_three_way(
                    self,
                    "No Price of Loyalty data found",
                    "fheroes2 has no HEROES2X.AGG in this install. Creating one "
                    "makes the game think Price of Loyalty is installed, which can "
                    "break the PoL campaign menu and PoL-only heroes/artifacts if "
                    "you don't actually own the expansion.\n\n"
                    "Patching HEROES2.AGG directly is the safe default — a backup "
                    "is made automatically and it never touches this PoL-detection flag.",
                    opt1="Patch HEROES2.AGG  (safe, recommended)",
                    opt2="Create HEROES2X.AGG anyway  (advanced)",
                )
                if choice is None:
                    return

                if choice == "opt1":
                    backup_path = base_agg_path + ".bak"
                    if not os.path.isfile(backup_path):
                        shutil.copy2(base_agg_path, backup_path)
                        log_lines.append(f"Backup: {backup_path}")
                    try:
                        save_lines = self.project.save(base_agg_path, music_out_dir="")
                    except Exception as e:
                        messagebox.showerror("Apply failed", str(e))
                        return
                    log_lines.extend(save_lines)

                else:  # opt2 — create overlay from scratch
                    overlay_name = _overlay_filename_for(base_agg_path)
                    overlay_path = os.path.join(data_dir, overlay_name)
                    new_bytes = self.project.build_overlay_bytes(None)
                    with open(overlay_path, "wb") as f:
                        f.write(new_bytes)
                    # Marker so _restore_mods knows WE created this from
                    # nothing and it's safe to delete on revert.
                    open(overlay_path + ".fh2studio_created", "w").close()
                    log_lines.append(
                        f"Created experimental overlay: {overlay_path} "
                        f"({len(self.project._pending)} entries)"
                    )
                    log_lines.append(
                        "  Note: avoid the in-game Price of Loyalty campaign "
                        "option unless you actually own the expansion."
                    )

        # Music is always handled the same way regardless of which AGG path
        # was used above — it's loose files, never packed into an overlay.
        log_lines.extend(self.project.save_music(music_dir))

        for line in log_lines:
            self._log(line)
        messagebox.showinfo("Applied", "Mod changes applied.\nSee the log for details.")

    def _restore_mods(self) -> None:
        """Undo fh2_studio's changes in the connected install: restore any
        *.bak backups, and delete any overlay this tool created from scratch
        (tracked via a .fh2studio_created marker — never deletes a file we
        didn't create ourselves)."""
        if self.project.is_open():
            data_dir = os.path.dirname(self.project._agg_path)
        elif self._fheroes2_dir:
            data_dir = os.path.join(self._fheroes2_dir, "data")
        else:
            messagebox.showinfo("Nothing to restore", "Connect to a fheroes2 install first.")
            return

        if not os.path.isdir(data_dir):
            messagebox.showinfo("Nothing to restore", f"Folder not found:\n{data_dir}")
            return

        restores: list[tuple[str, str]] = []   # (backup_path, target_path)
        deletes:  list[str] = []                # overlay paths to delete

        for fname in os.listdir(data_dir):
            full = os.path.join(data_dir, fname)
            if fname.lower().endswith(".agg.bak"):
                restores.append((full, full[: -len(".bak")]))
            elif fname.endswith(".fh2studio_created"):
                overlay_path = full[: -len(".fh2studio_created")]
                if os.path.isfile(overlay_path):
                    deletes.append(overlay_path)

        if not restores and not deletes:
            messagebox.showinfo("Nothing to restore", f"No fh2_studio backups or created files found in:\n{data_dir}")
            return

        preview = "\n".join(
            [f"Restore:  {os.path.basename(t)}  (from {os.path.basename(b)})" for b, t in restores]
            + [f"Delete:   {os.path.basename(p)}  (created by fh2_studio)" for p in deletes]
        )
        if not messagebox.askyesno("Confirm restore", f"This will:\n\n{preview}\n\nContinue?"):
            return

        for backup_path, target_path in restores:
            shutil.copy2(backup_path, target_path)
            self._log(f"Restored {target_path} from {os.path.basename(backup_path)}")
        for overlay_path in deletes:
            os.remove(overlay_path)
            marker = overlay_path + ".fh2studio_created"
            if os.path.isfile(marker):
                os.remove(marker)
            self._log(f"Deleted {overlay_path} (was created by fh2_studio)")

        messagebox.showinfo("Restored", "Original files restored.")

    def _save_mod(self) -> None:
        if not self.project.is_open():
            messagebox.showinfo("Nothing to save", "Open an AGG file first.")
            return
        out = filedialog.asksaveasfilename(
            title="Save patched AGG as…",
            defaultextension=".AGG",
            filetypes=[("AGG archives", "*.AGG"), ("All files", "*.*")],
            initialfile="HEROES2_modded.AGG"
        )
        if not out:
            return
        music_out = self.project._music_dir or os.path.join(os.path.dirname(out), "music")
        try:
            lines = self.project.save(out, music_out_dir=music_out)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return
        for l in lines:
            self._log(l)
        messagebox.showinfo("Saved", f"Saved to:\n{out}")

    # ────────────────────────────────────────────────────────────────────────
    # Browser population
    # ────────────────────────────────────────────────────────────────────────

    def _populate_browser(self) -> None:
        self._switch_browser_tab()

    def _switch_browser_tab(self) -> None:
        tab = self._browser_tab.get()
        if tab == "music":
            self._tree.pack_forget()
            self._music_list_frame.pack(fill="both", expand=True, padx=4, pady=2)
            self._populate_music_list()
        else:
            self._music_list_frame.pack_forget()
            self._tree.pack(fill="both", expand=True)
            self._populate_tree(tab)

    def _populate_tree(self, tab: str) -> None:
        self._tree.delete(*self._tree.get_children())
        if not self.project.is_open():
            return

        want_type = AssetType.SPRITE if tab == "sprites" else AssetType.SOUND
        sections: dict[str, str] = {}  # section -> tree iid

        q = self._search_var.get().lower()

        for asset in self.project.assets:
            if asset.atype != want_type:
                continue
            if q and q not in asset.name.lower() and q not in asset.friendly.lower():
                continue
            sec = asset.section
            if sec not in sections:
                iid = self._tree.insert("", "end", text=f"  {sec}",
                                         open=True, tags=("section",))
                sections[sec] = iid
                self._tree.tag_configure("section", foreground=C_SUBTEXT,
                                          font=(*FONT_SMALL[:2], "bold"))
            tags = ("replaced",) if asset.replaced else ()
            disp = f"  {'★ ' if asset.replaced else ''}{asset.name}"
            self._tree.insert(sections[sec], "end", iid=asset.name,
                               text=disp, tags=tags)

    def _populate_music_list(self) -> None:
        self._music_listbox.delete(0, tk.END)
        for mt in self.project.music_tracks:
            mark = "★ " if mt.replaced else ("✓ " if mt.installed_path else "  ")
            self._music_listbox.insert(tk.END, f"{mark}{mt.track.friendly_name}")

    def _filter_tree(self) -> None:
        tab = self._browser_tab.get()
        if tab != "music":
            self._populate_tree(tab)

    # ────────────────────────────────────────────────────────────────────────
    # Selection handlers
    # ────────────────────────────────────────────────────────────────────────

    def _on_tree_select(self, _evt=None) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        asset = next((a for a in self.project.assets if a.name == iid), None)
        if asset is None:
            return
        self._sel_asset = asset
        self._sel_music = None
        self._detail_title.config(text=asset.friendly)
        self._detail_sub.config(text=f"{asset.section}  ·  {asset.size:,} bytes"
                                     + ("  ·  REPLACED ★" if asset.replaced else ""))

        if asset.atype == AssetType.SPRITE:
            self._nb.select(0)
            self._load_sprite(asset)
            self._update_info_sprite(asset)
        elif asset.atype == AssetType.SOUND:
            self._nb.select(1)
            self._load_sound(asset)

    def _on_music_select(self, _evt=None) -> None:
        sel = self._music_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        mt = self.project.music_tracks[idx]
        self._sel_music = mt
        self._sel_asset = None
        self._nb.select(2)
        self._show_music_detail(mt)

    # ────────────────────────────────────────────────────────────────────────
    # Sprite display
    # ────────────────────────────────────────────────────────────────────────

    def _load_sprite(self, asset) -> None:
        self._stop_anim()
        self._sel_sprite_idx = 0
        self._frame_rgba_cache = {}
        raw = self.project.raw_bytes(asset.name)
        try:
            self._icn_headers, self._icn_data = parse_icn(raw)
        except Exception as e:
            self._log(f"Cannot parse {asset.name}: {e}")
            self._icn_headers, self._icn_data = [], []

        last = max(0, len(self._icn_headers) - 1)
        self._anim_from_var.set(0)
        self._anim_to_var.set(last)
        self._anim_from_spin.config(to=last)
        self._anim_to_spin.config(to=last)

        self._show_sprite_frame()

    def _decode_frame_rgba(self, idx: int) -> "Image.Image | None":
        """Decode one sprite frame to RGBA, cached per-frame for the currently
        loaded ICN. Cache is cleared in `_load_sprite` whenever a new asset opens."""
        cached = self._frame_rgba_cache.get(idx)
        if cached is not None:
            return cached

        hdr = self._icn_headers[idx]
        if not self.project.palette or hdr.width <= 0 or hdr.height <= 0:
            return None
        try:
            sprite_bytes = self._icn_data[idx]
            image, transform = decode_sprite(sprite_bytes, hdr)
            rgba, _ = sprite_to_images(image, transform, hdr.width, hdr.height,
                                       self.project.palette)
        except Exception as e:
            self._log(f"Sprite render error (frame {idx}): {e}")
            return None

        self._frame_rgba_cache[idx] = rgba
        return rgba

    def _show_sprite_frame(self, idx: int | None = None) -> None:
        headers = getattr(self, "_icn_headers", [])
        n = len(headers)
        if n == 0:
            self._orig_canvas.delete("all")
            self._frame_label.config(text="No frames")
            return

        if idx is None:
            idx = self._sel_sprite_idx
        idx = max(0, min(idx, n - 1))
        self._sel_sprite_idx = idx
        hdr = headers[idx]

        suffix = "  (playing)" if self._anim_playing else ""
        self._frame_label.config(text=f"Frame {idx + 1} / {n}{suffix}")

        mono_flag = "  [MONO]" if hdr.animationFrames & 0x20 else ""
        self._dim_label.config(
            text=f"{hdr.width} × {hdr.height} px{mono_flag}  |  "
                 f"offset ({hdr.offsetX:+d}, {hdr.offsetY:+d})"
        )
        self._sprite_info.config(
            text=f"Size: {hdr.width} × {hdr.height}\n"
                 f"Offset: ({hdr.offsetX}, {hdr.offsetY})\n"
                 f"animFlags: 0x{hdr.animationFrames:02X}")

        rgba = self._decode_frame_rgba(idx)
        if rgba is not None:
            display = _composite_on_checker(rgba) if self._bg_mode == "checker" \
                else _composite_on_solid(rgba, self._bg_mode)
            self._last_rgba = rgba
        else:
            if not self.project.palette:
                self._log("No palette loaded — open an AGG that contains KB.PAL")
            display = Image.new("RGB", (PREVIEW_SIZE, PREVIEW_SIZE), (30, 0, 50))
            self._last_rgba = None

        photo = ImageTk.PhotoImage(display)
        self._orig_canvas.delete("all")
        self._orig_canvas.create_image(0, 0, anchor="nw", image=photo)
        self._preview_photo = photo  # keep reference

    def _cycle_bg(self) -> None:
        """Cycle the preview background: checker → black → white → green → checker."""
        order = ["checker", "black", "white", "green"]
        labels = {
            "checker": "BG: Checker",
            "black":   "BG: Black",
            "white":   "BG: White",
            "green":   "BG: Green (terrain)",
        }
        idx = order.index(self._bg_mode)
        self._bg_mode = order[(idx + 1) % len(order)]
        self._bg_btn.config(text=labels[self._bg_mode])
        self._show_sprite_frame()   # re-render with new background

    def _prev_sprite(self) -> None:
        if not getattr(self, "_icn_headers", []):
            return
        self._stop_anim()
        self._sel_sprite_idx = (self._sel_sprite_idx - 1) % len(self._icn_headers)
        self._show_sprite_frame()

    def _next_sprite(self) -> None:
        if not getattr(self, "_icn_headers", []):
            return
        self._stop_anim()
        self._sel_sprite_idx = (self._sel_sprite_idx + 1) % len(self._icn_headers)
        self._show_sprite_frame()

    # ── animation playback ──────────────────────────────────────────────────

    def _anim_select_all(self) -> None:
        n = len(getattr(self, "_icn_headers", []))
        if n == 0:
            return
        self._anim_from_var.set(0)
        self._anim_to_var.set(n - 1)

    def _toggle_anim_play(self) -> None:
        if self._anim_playing:
            self._stop_anim()
            return

        n = len(getattr(self, "_icn_headers", []))
        if n == 0:
            messagebox.showinfo("Nothing to animate", "Select a sprite with at least one frame first.")
            return

        try:
            frm = int(self._anim_from_var.get())
            to  = int(self._anim_to_var.get())
            fps = int(self._anim_fps_var.get())
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid input", "From / To / FPS must be whole numbers.")
            return

        frm = max(0, min(frm, n - 1))
        to  = max(0, min(to,  n - 1))
        if to < frm:
            frm, to = to, frm
        fps = max(1, min(fps, 60))

        # Reflect any clamping back into the UI
        self._anim_from_var.set(frm)
        self._anim_to_var.set(to)
        self._anim_fps_var.set(fps)

        self._anim_range = (frm, to)
        self._anim_interval_ms = max(1, round(1000 / fps))
        self._anim_loop = bool(self._anim_loop_var.get())
        self._anim_cur = frm
        self._anim_playing = True

        self._anim_from_spin.config(state="disabled")
        self._anim_to_spin.config(state="disabled")
        self._anim_fps_spin.config(state="disabled")
        self._anim_play_btn.config(text="⏹  Stop Animation", bg=C_ACCENT)

        self._anim_tick()

    def _anim_tick(self) -> None:
        if not self._anim_playing:
            return

        frm, to = self._anim_range
        self._show_sprite_frame(self._anim_cur)

        nxt = self._anim_cur + 1
        if nxt > to:
            if self._anim_loop:
                nxt = frm
            else:
                self._stop_anim()
                return
        self._anim_cur = nxt
        self._anim_after_id = self.after(self._anim_interval_ms, self._anim_tick)

    def _stop_anim(self) -> None:
        if not self._anim_playing:
            return
        if self._anim_after_id is not None:
            try:
                self.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None
        self._anim_playing = False
        self._anim_play_btn.config(text="▶  Play Animation", bg=C_BTN_ACT)
        self._anim_from_spin.config(state="normal")
        self._anim_to_spin.config(state="normal")
        self._anim_fps_spin.config(state="normal")
        self._show_sprite_frame()   # restore the manually-selected static frame

    def _export_sprite_png(self) -> None:
        """Save the current sprite frame as a full-resolution RGBA PNG."""
        rgba = getattr(self, "_last_rgba", None)
        if rgba is None:
            messagebox.showinfo("Nothing to export", "Select a sprite frame first.")
            return
        asset = self._sel_asset
        name = asset.name.replace(".", "_") if asset else "sprite"
        idx  = self._sel_sprite_idx
        default = f"{name}_frame{idx}.png"
        path = filedialog.asksaveasfilename(
            title="Export frame as PNG",
            defaultextension=".png",
            initialfile=default,
            filetypes=[("PNG images", "*.png"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            rgba.save(path)
            self._log(f"Exported {rgba.width}×{rgba.height} PNG → {path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _update_info_sprite(self, asset) -> None:
        raw = self.project.raw_bytes(asset.name)
        try:
            hdrs, _ = parse_icn(raw)
        except Exception:
            hdrs = []
        info = (
            f"Entry:       {asset.name}\n"
            f"Type:        ICN sprite sheet\n"
            f"Section:     {asset.section}\n"
            f"Total size:  {asset.size:,} bytes\n"
            f"Frames:      {len(hdrs)}\n"
            f"Replaced:    {'Yes ★' if asset.replaced else 'No'}\n"
        )
        if hdrs:
            info += "\nFrame sizes:\n"
            for i, h in enumerate(hdrs[:20]):
                info += f"  [{i:3d}] {h.width:4d} × {h.height:<4d}  off ({h.offsetX:+d},{h.offsetY:+d})\n"
            if len(hdrs) > 20:
                info += f"  ... and {len(hdrs)-20} more\n"
        self._set_info_text(info)

    # ────────────────────────────────────────────────────────────────────────
    # Sprite replacement
    # ────────────────────────────────────────────────────────────────────────

    def _browse_sprite_import(self) -> None:
        path = filedialog.askopenfilename(
            title="Select replacement image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tga *.webp"),
                       ("All files", "*.*")]
        )
        if not path:
            return
        try:
            self._import_image = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Cannot open image", str(e))
            return

        self._import_label.config(text=os.path.basename(path))
        self._update_import_preview()
        self._log(f"Loaded: {path}")

    def _update_import_preview(self) -> None:
        if self._import_image is None:
            return
        headers = getattr(self, "_icn_headers", [])
        if headers and self._sel_sprite_idx < len(headers):
            hdr = headers[self._sel_sprite_idx]
            if hdr.width > 0 and hdr.height > 0:
                fitted = _fit_user_image(self._import_image, hdr.width, hdr.height)
            else:
                fitted = self._import_image.copy()
        else:
            fitted = self._import_image.copy()
        display = _composite_on_checker(fitted.convert("RGBA"))
        photo = ImageTk.PhotoImage(display)
        self._import_canvas.delete("all")
        self._import_canvas.create_image(0, 0, anchor="nw", image=photo)
        self._import_photo = photo

    def _apply_sprite_frame(self) -> None:
        self._do_sprite_replace(frames="current")

    def _apply_sprite_all(self) -> None:
        self._do_sprite_replace(frames="all")

    def _do_sprite_replace(self, frames: str) -> None:
        if self._sel_asset is None or self._import_image is None:
            messagebox.showinfo("Nothing to do",
                                "Select an asset in the browser and browse an image first.")
            return
        if not self.project.palette:
            messagebox.showerror("No palette", "Palette (KB.PAL) not found in this AGG.")
            return
        headers = getattr(self, "_icn_headers", [])
        datas   = getattr(self, "_icn_data",    [])
        if not headers:
            return

        matcher = NearestColorMatcher(self.project.palette)
        new_headers = list(headers)
        new_datas   = list(datas)

        target_indices = (range(len(headers)) if frames == "all"
                          else [self._sel_sprite_idx])

        for idx in target_indices:
            hdr = headers[idx]
            tw = hdr.width if hdr.width > 0 else self._import_image.width
            th = hdr.height if hdr.height > 0 else self._import_image.height
            fitted = _fit_user_image(self._import_image, tw, th)
            img_arr, trf_arr, nw, nh = images_to_sprite(fitted, None, matcher)
            new_datas[idx] = encode_sprite(img_arr, trf_arr, nw, nh)
            new_headers[idx] = ICNHeader(hdr.offsetX, hdr.offsetY, nw, nh,
                                          hdr.animationFrames & ~0x20, 0)

        new_blob = build_icn(new_headers, new_datas)
        self.project.stage_sprite_replacement(self._sel_asset.name, new_blob)
        self._icn_headers = new_headers
        self._icn_data    = new_datas
        self._show_sprite_frame()
        self._refresh_asset_display()
        self._log(f"★ Staged replacement: {self._sel_asset.name} "
                  f"({len(target_indices)} frame(s))")

    # ────────────────────────────────────────────────────────────────────────
    # Sound display and replacement
    # ────────────────────────────────────────────────────────────────────────

    def _load_sound(self, asset) -> None:
        from fh2agg.sound import SOUND_INFO
        info = SOUND_INFO.get(asset.name.upper(), (asset.name, "Unknown"))
        self._sound_name_label.config(text=info[0])
        raw = self.project.raw_bytes(asset.name)
        dur_ms = int(len(raw) / 22.050)
        self._sound_size_label.config(
            text=f"{len(raw):,} bytes  ·  ~{dur_ms} ms  ·  "
                 f"{'REPLACED ★' if asset.replaced else 'Original'}")
        self._sound_replacement_path = ""
        self._sound_import_label.config(text="No replacement selected")

    def _browse_sound_import(self) -> None:
        path = filedialog.askopenfilename(
            title="Select replacement WAV",
            filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")]
        )
        if not path:
            return
        self._sound_replacement_path = path
        self._sound_import_label.config(text=os.path.basename(path))
        self._log(f"Sound replacement selected: {path}")

    def _apply_sound(self) -> None:
        if not self._sel_asset or not self._sound_replacement_path:
            messagebox.showinfo("Nothing to do", "Select a sound asset and a WAV file first.")
            return
        try:
            with open(self._sound_replacement_path, "rb") as f:
                wav_bytes = f.read()
            m82 = wav_bytes_to_m82(wav_bytes)
        except Exception as e:
            messagebox.showerror("Conversion error",
                                  f"Cannot convert WAV: {e}\n\nMake sure it's 8-bit mono 22050 Hz.\n"
                                  "You can convert with: ffmpeg -i input.wav -ar 22050 -ac 1 -sample_fmt u8 out.wav")
            return
        self.project.stage_sound_replacement(self._sel_asset.name, m82)
        self._refresh_asset_display()
        self._log(f"★ Staged sound: {self._sel_asset.name}")

    def _play_sound_original(self) -> None:
        if not self._sel_asset:
            return
        raw = self.project._entries.get(self._sel_asset.name, b"")
        self._play_pcm(raw)

    def _play_sound_replacement(self) -> None:
        if not self._sel_asset:
            return
        raw = self.project._pending.get(self._sel_asset.name, b"")
        if not raw:
            self._log("No replacement staged yet")
            return
        self._play_pcm(raw)

    def _play_pcm(self, pcm: bytes) -> None:
        if not _AUDIO_OK:
            messagebox.showinfo("Audio unavailable", "pygame.mixer failed to initialise.")
            return
        try:
            wav = m82_to_wav_bytes(pcm)
            sound = pygame.mixer.Sound(io.BytesIO(wav))
            sound.play()
        except Exception as e:
            self._log(f"Playback error: {e}")

    # ────────────────────────────────────────────────────────────────────────
    # Music display and replacement
    # ────────────────────────────────────────────────────────────────────────

    def _show_music_detail(self, mt) -> None:
        self._music_title_label.config(text=mt.track.friendly_name)
        if mt.replaced:
            status = f"★ Replacement staged: {os.path.basename(mt.replacement_path)}"
            fg = C_REPLACED
        elif mt.installed_path:
            status = f"✓ Installed: {os.path.basename(mt.installed_path)}"
            fg = C_TEXT
        else:
            status = "Not installed — no matching file found in music folder"
            fg = C_SUBTEXT
        self._music_status_label.config(text=status, fg=fg)
        self._music_replacement_path = mt.replacement_path if mt.replaced else ""
        self._music_import_label.config(
            text=(os.path.basename(mt.replacement_path) if mt.replaced
                  else "No replacement selected")
        )
        names = "\n".join([
            f"MAPPED:    {mt.track.mapped_name()}",
            f"DOS/GOG:   {mt.track.dos_name()}",
            f"Win/CD:    {mt.track.win_name()}",
        ])
        self._music_names_info.config(text=names)
        self._detail_title.config(text=f"🎵  {mt.track.friendly_name}")
        self._detail_sub.config(text=f"Track {mt.track.track_id}  ·  {mt.track.enum_name}")
        # Reset progress display for the new track
        self._update_progress_display(0.0)

    def _browse_music_import(self) -> None:
        path = filedialog.askopenfilename(
            title="Select replacement audio file",
            filetypes=[("Audio", "*.ogg *.mp3 *.flac *.wav"), ("All files", "*.*")]
        )
        if not path:
            return
        self._music_replacement_path = path
        self._music_import_label.config(text=os.path.basename(path))
        self._log(f"Music replacement: {path}")

    def _apply_music(self) -> None:
        if not self._sel_music or not self._music_replacement_path:
            messagebox.showinfo("Nothing to do", "Select a track and browse an audio file first.")
            return
        self.project.stage_music_replacement(self._sel_music.track, self._music_replacement_path)
        self._sel_music.replaced = True
        self._sel_music.replacement_path = self._music_replacement_path
        self._populate_music_list()
        self._show_music_detail(self._sel_music)
        self._log(f"★ Staged music: {self._sel_music.track.friendly_name}")

    def _play_music_installed(self) -> None:
        if self._sel_music and self._sel_music.installed_path:
            self._play_audio_file(self._sel_music.installed_path)
        else:
            self._log("No installed file for this track")

    def _play_music_replacement(self) -> None:
        if self._sel_music and self._sel_music.replacement_path:
            self._play_audio_file(self._sel_music.replacement_path)
        else:
            self._log("No replacement selected")

    # New unified transport methods ──────────────────────────────────────────

    def _play_music(self) -> None:
        """Play the currently selected track (installed file preferred)."""
        if not self._sel_music:
            return
        path = (self._sel_music.installed_path or
                (self._sel_music.replacement_path if self._sel_music.replaced else ""))
        if not path:
            self._log("No installed file for this track")
            return
        if self._music_paused and _AUDIO_OK:
            pygame.mixer.music.unpause()
            self._music_paused   = False
            self._music_playing  = True
            return
        self._play_audio_file(path)

    def _pause_music(self) -> None:
        if not _AUDIO_OK:
            return
        if self._music_playing and not self._music_paused:
            pygame.mixer.music.pause()
            self._music_paused  = True
            self._music_playing = False
        elif self._music_paused:
            pygame.mixer.music.unpause()
            self._music_paused  = False
            self._music_playing = True

    def _stop_music(self) -> None:
        if _AUDIO_OK:
            pygame.mixer.music.stop()
        self._music_playing = False
        self._music_paused  = False
        self._update_progress_display(0.0)

    def _play_audio_file(self, path: str) -> None:
        if not _AUDIO_OK:
            messagebox.showinfo("Audio unavailable", "pygame.mixer failed to initialise.")
            return
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self._music_playing = True
            self._music_paused  = False
            # Try to find duration via a temporary Sound object (works for short files)
            try:
                tmp = pygame.mixer.Sound(path)
                self._music_duration = tmp.get_length()
                del tmp
            except Exception:
                self._music_duration = 0.0
        except Exception as e:
            self._log(f"Playback error: {e}")

    def _on_prog_click(self, event: tk.Event) -> None:
        """Seek to the clicked position on the progress bar (requires duration)."""
        if not _AUDIO_OK or not self._music_playing and not self._music_paused:
            return
        if self._music_duration <= 0:
            return
        w = self._prog_canvas.winfo_width()
        if w <= 0:
            return
        frac = max(0.0, min(event.x / w, 1.0))
        target_s = frac * self._music_duration
        pygame.mixer.music.set_pos(target_s)

    def _update_progress_display(self, elapsed: float) -> None:
        dur = self._music_duration
        e_str = f"{int(elapsed//60)}:{int(elapsed%60):02d}"
        d_str = (f"{int(dur//60)}:{int(dur%60):02d}" if dur > 0 else "—:——")
        self._prog_time.config(text=f"{e_str} / {d_str}")
        w = self._prog_canvas.winfo_width()
        if w > 0 and dur > 0:
            fill_w = int(w * min(elapsed / dur, 1.0))
            self._prog_canvas.coords(self._prog_fill, 0, 0, fill_w, 8)

    def _tick(self) -> None:
        """200 ms heartbeat: update music progress bar."""
        if _AUDIO_OK and self._music_playing:
            if pygame.mixer.music.get_busy():
                ms = pygame.mixer.music.get_pos()
                if ms >= 0:
                    self._update_progress_display(ms / 1000.0)
            else:
                # Track finished naturally
                self._music_playing = False
                self._music_paused  = False
                dur = self._music_duration
                self._update_progress_display(dur if dur > 0 else 0.0)
        self.after(200, self._tick)

    # ────────────────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────────────────

    def _refresh_asset_display(self) -> None:
        """Refresh the browser and detail panel after a replacement."""
        tab = self._browser_tab.get()
        if tab != "music":
            self._populate_tree(tab)
        if self._sel_asset:
            self._detail_sub.config(
                text=f"{self._sel_asset.section}  ·  {self._sel_asset.size:,} bytes"
                     + ("  ·  REPLACED ★" if self._sel_asset.replaced else ""))

    def _set_info_text(self, text: str) -> None:
        self._info_text.config(state="normal")
        self._info_text.delete("1.0", tk.END)
        self._info_text.insert(tk.END, text)
        self._info_text.config(state="disabled")

    def _log(self, msg: str) -> None:
        self._log_text.config(state="normal")
        self._log_text.insert(tk.END, msg + "\n")
        self._log_text.see(tk.END)
        self._log_text.config(state="disabled")


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    app = Studio()
    app.mainloop()


if __name__ == "__main__":
    main()
