#!/usr/bin/env python3
r"""
fh2_studio diagnostic — run from the fh2_studio folder:
    python diagnose.py
    python diagnose.py "C:\path\to\HEROES2.AGG"  ELF.ICN  0
Saves each decoded sprite as a PNG so you can see exactly what our
decode pipeline produces, independent of the Tkinter display.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fh2agg.aggfile import parse_agg
from fh2agg.icn     import parse_icn, decode_sprite, TOP_HEADER_SIZE, ICN_HEADER_SIZE
from fh2agg.palette import load_palette
from fh2agg.pngconvert import sprite_to_images
from PIL import Image


# ── helpers ──────────────────────────────────────────────────────────────────

def composite_white(rgba: Image.Image) -> Image.Image:
    """Paste RGBA sprite onto a white background so shadows are visible."""
    bg = Image.new("RGB", rgba.size, (255, 255, 255))
    bg.paste(rgba, (0, 0), rgba)
    return bg


def composite_green(rgba: Image.Image) -> Image.Image:
    """Paste RGBA sprite onto a terrain-green background."""
    bg = Image.new("RGB", rgba.size, (82, 154, 76))
    bg.paste(rgba, (0, 0), rgba)
    return bg


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # ---------- argument parsing ----------
    agg_path    = r"C:\Program Files\fheroes2\data\HEROES2.AGG"
    sprite_name = "ELF.ICN"
    frame_idx   = 0

    if len(sys.argv) >= 2:
        agg_path = sys.argv[1]
    if len(sys.argv) >= 3:
        sprite_name = sys.argv[2].upper()
    if len(sys.argv) >= 4:
        frame_idx = int(sys.argv[3])

    # ---------- open AGG ----------
    print(f"Opening: {agg_path}")
    if not os.path.isfile(agg_path):
        print(f"  ERROR: file not found — {agg_path}")
        return 1

    with open(agg_path, "rb") as f:
        raw = f.read()
    print(f"  AGG size: {len(raw):,} bytes")

    print("Parsing AGG …")
    try:
        entries = parse_agg(raw, verify_hashes=True)
    except Exception as e:
        print(f"  ERROR parsing AGG: {e}")
        return 1
    print(f"  {len(entries)} entries")

    # ---------- palette ----------
    if "KB.PAL" not in entries:
        print("  ERROR: KB.PAL not found in AGG")
        return 1
    pal_raw = entries["KB.PAL"]
    print(f"\nKB.PAL: {len(pal_raw)} bytes")
    palette = load_palette(pal_raw)
    print(f"  palette[  0] = {palette[0]}")
    print(f"  palette[  1] = {palette[1]}")
    print(f"  palette[128] = {palette[128]}")
    print(f"  palette[255] = {palette[255]}")

    # ---------- locate ICN ----------
    if sprite_name not in entries:
        print(f"\nERROR: '{sprite_name}' not found.")
        icn_names = sorted(k for k in entries if k.endswith(".ICN"))
        print(f"Available ICN files ({len(icn_names)}):")
        for n in icn_names[:30]:
            print(f"  {n}")
        if len(icn_names) > 30:
            print(f"  … and {len(icn_names)-30} more")
        return 1

    icn_blob = entries[sprite_name]
    print(f"\n{sprite_name}: {len(icn_blob)} bytes raw")

    # ---------- parse ICN ----------
    try:
        headers, datas = parse_icn(icn_blob)
    except Exception as e:
        print(f"  ERROR parsing ICN: {e}")
        return 1
    print(f"  {len(headers)} sprites (frames)")

    # Show the computed data_start vs what parse_icn used
    declared_count = int.from_bytes(icn_blob[0:2], "little")
    block_size     = int.from_bytes(icn_blob[2:6], "little")
    data_start     = TOP_HEADER_SIZE + len(headers) * ICN_HEADER_SIZE
    print(f"  declared count={declared_count}, block_size={block_size}")
    print(f"  data_start={data_start}  (TOP_HEADER_SIZE={TOP_HEADER_SIZE} + "
          f"{len(headers)}×{ICN_HEADER_SIZE}={len(headers)*ICN_HEADER_SIZE})")
    print(f"  available data bytes = {len(icn_blob) - data_start}")

    # Show offsetData for first few sprites
    print("  First 5 sprite headers:")
    for i, h in enumerate(headers[:5]):
        print(f"    [{i}] {h.width}×{h.height}  offsetX={h.offsetX}  "
              f"offsetY={h.offsetY}  offsetData={h.offsetData}  "
              f"data_len={len(datas[i])}")

    # ---------- decode chosen frame ----------
    if frame_idx >= len(headers):
        print(f"\nERROR: frame {frame_idx} out of range (0–{len(headers)-1})")
        return 1

    hdr  = headers[frame_idx]
    data = datas[frame_idx]

    print(f"\nDecoding frame {frame_idx} ({hdr.width}×{hdr.height}) …")
    print(f"  data bytes: {len(data)}")
    print(f"  first 48 bytes: {data[:48].hex(' ')}")

    try:
        image, transform = decode_sprite(data, hdr)
    except Exception as e:
        print(f"  ERROR in decode_sprite: {e}")
        import traceback; traceback.print_exc()
        return 1

    n_op  = sum(1 for t in transform if t == 0)
    n_tr  = sum(1 for t in transform if t == 1)
    n_sp  = sum(1 for t in transform if t > 1)
    print(f"  opaque={n_op}  transparent={n_tr}  special={n_sp}  "
          f"total={hdr.width * hdr.height}")

    # Per-row transparency map
    print("  Row-by-row transparent count:")
    for row in range(hdr.height):
        base = row * hdr.width
        tc = sum(1 for x in range(hdr.width) if transform[base + x] == 1)
        bar = "#" * (hdr.width - tc) + "." * tc
        print(f"    row {row:3d}: [{bar}]  ({tc} transparent)")

    # ---------- build RGBA ----------
    rgba, _ = sprite_to_images(image, transform, hdr.width, hdr.height, palette)

    # ---------- save PNGs ----------
    stem = f"{sprite_name.replace('.','_')}_frame{frame_idx}"

    # 1. Full-resolution RGBA (transparent areas = transparent)
    out_rgba = f"{stem}_RGBA.png"
    rgba.save(out_rgba)
    print(f"\nSaved: {out_rgba}  ({hdr.width}×{hdr.height} RGBA)")

    # 2. On white background (good for creatures / UI elements)
    out_white = f"{stem}_white_bg.png"
    composite_white(rgba).save(out_white)
    print(f"Saved: {out_white}  (same sprite on white background)")

    # 3. On terrain-green background (good for creatures)
    out_green = f"{stem}_green_bg.png"
    composite_green(rgba).save(out_green)
    print(f"Saved: {out_green}  (same sprite on grass/terrain background)")

    print("\nOpen any of those PNGs to see the decoded result.")
    print("If they look correct → the bug is in the Tkinter display layer.")
    print("If they look wrong   → the bug is in parsing or decode.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
