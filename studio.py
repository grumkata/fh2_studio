#!/usr/bin/env python3
"""
fh2 Studio — a mod tool for Heroes of Might & Magic II / fheroes2.

Run this file directly:   python3 studio.py
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ── make sure the sibling fh2agg package is importable ─────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image, ImageTk                                   # noqa: E402
from fh2agg.aggfile import AggFormatError                        # noqa: E402
from fh2agg.icn import (ICNHeader, build_icn, decode_sprite,    # noqa: E402
                          encode_sprite, parse_icn)
from fh2agg.palette import NearestColorMatcher, load_palette     # noqa: E402
from fh2agg.pngconvert import images_to_sprite, sprite_to_images # noqa: E402
from fh2agg.project import AssetType, Project                    # noqa: E402
from fh2agg.sound import m82_to_wav_bytes, wav_bytes_to_m82      # noqa: E402

# ── optional pygame for audio playback ─────────────────────────────────────
try:
    import pygame
    pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
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
        self._sel_asset = None          # currently selected AssetEntry
        self._sel_music = None          # currently selected MusicEntry
        self._sel_sprite_idx = 0        # sprite frame index within ICN
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._import_photo:  ImageTk.PhotoImage | None = None
        self._audio_thread: threading.Thread | None = None

        self._build_ui()
        self._apply_styles()

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
        self._btn("Open AGG…",    self._open_agg,   btn_frame, accent=False)
        self._btn("Set Music Dir…",self._set_music_dir, btn_frame, accent=False)
        self._btn("Save Mod…",    self._save_mod,   btn_frame, accent=True)

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
        self._sprite_info.pack(padx=8, pady=(0, 8), anchor="w")

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

        inner = tk.Frame(f, bg=C_BG)
        inner.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(inner, text="🎵", bg=C_BG, fg=C_TEXT,
                 font=("Helvetica", 48)).pack(pady=(0, 8))
        self._music_title_label = tk.Label(inner, text="Select a track", bg=C_BG,
                                            fg=C_TEXT, font=FONT_TITLE)
        self._music_title_label.pack()
        self._music_status_label = tk.Label(inner, text="", bg=C_BG,
                                             fg=C_SUBTEXT, font=FONT_SMALL)
        self._music_status_label.pack(pady=4)

        play_row = tk.Frame(inner, bg=C_BG)
        play_row.pack(pady=8)
        self._btn("▶  Play Installed", self._play_music_installed, play_row)
        self._btn("▶  Play Replacement", self._play_music_replacement, play_row)

        self._btn("Browse Audio…", self._browse_music_import, inner)
        self._music_import_label = tk.Label(inner, text="No replacement selected",
                                             bg=C_BG, fg=C_SUBTEXT, font=FONT_SMALL)
        self._music_import_label.pack(pady=4)
        self._btn("Stage Music Replacement", self._apply_music, inner, accent=True)

        self._music_replacement_path: str = ""

        self._music_names_info = tk.Label(inner, text="",
                                           bg=C_BG, fg=C_SUBTEXT,
                                           font=FONT_MONO, justify="left")
        self._music_names_info.pack(pady=(12, 0))

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
        # Guess music dir: same folder / music subfolder
        music_dir = os.path.join(os.path.dirname(path), "music")
        if not os.path.isdir(music_dir):
            music_dir = ""
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
        self._sel_sprite_idx = 0
        raw = self.project.raw_bytes(asset.name)
        try:
            self._icn_headers, self._icn_data = parse_icn(raw)
        except Exception as e:
            self._log(f"Cannot parse {asset.name}: {e}")
            self._icn_headers, self._icn_data = [], []
        self._show_sprite_frame()

    def _show_sprite_frame(self) -> None:
        headers = getattr(self, "_icn_headers", [])
        datas   = getattr(self, "_icn_data",    [])
        n = len(headers)
        if n == 0:
            self._orig_canvas.delete("all")
            self._frame_label.config(text="No frames")
            return

        idx = max(0, min(self._sel_sprite_idx, n - 1))
        self._sel_sprite_idx = idx
        hdr = headers[idx]
        self._frame_label.config(text=f"Frame {idx + 1} / {n}")
        self._sprite_info.config(
            text=f"Size: {hdr.width} × {hdr.height}\n"
                 f"Offset: ({hdr.offsetX}, {hdr.offsetY})\n"
                 f"animFlags: 0x{hdr.animationFrames:02X}")

        if self.project.palette and hdr.width > 0 and hdr.height > 0:
            try:
                image, transform = decode_sprite(datas[idx], hdr)
                rgba, _ = sprite_to_images(image, transform, hdr.width, hdr.height,
                                           self.project.palette)
                display = _composite_on_checker(rgba)
            except Exception:
                display = Image.new("RGB", (PREVIEW_SIZE, PREVIEW_SIZE), (30, 0, 50))
        else:
            display = Image.new("RGB", (PREVIEW_SIZE, PREVIEW_SIZE), (30, 0, 50))

        photo = ImageTk.PhotoImage(display)
        self._orig_canvas.delete("all")
        self._orig_canvas.create_image(0, 0, anchor="nw", image=photo)
        self._preview_photo = photo  # keep reference

    def _prev_sprite(self) -> None:
        if not getattr(self, "_icn_headers", []):
            return
        self._sel_sprite_idx = (self._sel_sprite_idx - 1) % len(self._icn_headers)
        self._show_sprite_frame()

    def _next_sprite(self) -> None:
        if not getattr(self, "_icn_headers", []):
            return
        self._sel_sprite_idx = (self._sel_sprite_idx + 1) % len(self._icn_headers)
        self._show_sprite_frame()

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
            status = "Not installed (no matching file in music folder)"
            fg = C_SUBTEXT
        self._music_status_label.config(text=status, fg=fg)
        self._music_replacement_path = mt.replacement_path if mt.replaced else ""
        label = (os.path.basename(mt.replacement_path)
                 if mt.replaced else "No replacement selected")
        self._music_import_label.config(text=label)

        names = "\n".join([
            f"MAPPED:      {mt.track.mapped_name()}",
            f"DOS/GOG:     {mt.track.dos_name()}",
            f"Win/Track:   {mt.track.win_name()}",
        ])
        self._music_names_info.config(text=names)

        self._detail_title.config(text=f"🎵  {mt.track.friendly_name}")
        self._detail_sub.config(text=f"Track {mt.track.track_id}  ·  {mt.track.enum_name}")

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

    def _play_audio_file(self, path: str) -> None:
        if not _AUDIO_OK:
            messagebox.showinfo("Audio unavailable", "pygame.mixer failed to initialise.")
            return
        def _play():
            try:
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
            except Exception as e:
                self._log(f"Playback error: {e}")
        threading.Thread(target=_play, daemon=True).start()

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
