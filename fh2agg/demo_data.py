"""
Synthetic (non-copyrighted) palette + ICN data used by both make_demo_agg.py
and selftest.py, so you can exercise the whole extract/export/edit/import/
repack pipeline without owning a copy of the original game.
"""

from __future__ import annotations

from .icn import ICNHeader, build_icn, encode_sprite


def build_synthetic_palette() -> bytes:
    """256 colours, 6-bit VGA values: a grayscale ramp plus two named
    colours (index 10 = bright red, index 20 = bright blue)."""
    raw = bytearray(768)
    for i in range(256):
        v = i % 64
        raw[i * 3 + 0] = v
        raw[i * 3 + 1] = v
        raw[i * 3 + 2] = v
    raw[10 * 3 + 0], raw[10 * 3 + 1], raw[10 * 3 + 2] = 63, 0, 0  # red
    raw[20 * 3 + 0], raw[20 * 3 + 1], raw[20 * 3 + 2] = 0, 0, 63  # blue
    return bytes(raw)


def build_synthetic_icn() -> tuple[bytes, list[bytes]]:
    """A 3-sprite ICN:
      sprite 0: 16x16, solid red square (left) + transparent (right) - the
                one you're meant to "reskin" in the demo.
      sprite 1: 24x12, a varied-colour stripe, a 2px shadow strip, and a
                solid blue stripe - must survive untouched.
      sprite 2: 160x4, long solid + long transparent runs - must survive
                untouched.
    """
    sprites = []

    w0, h0 = 16, 16
    img0 = bytearray(w0 * h0)
    trf0 = bytearray(w0 * h0)
    for y in range(h0):
        for x in range(w0):
            if x < w0 // 2:
                img0[y * w0 + x] = 10  # red
                trf0[y * w0 + x] = 0
            else:
                trf0[y * w0 + x] = 1
    sprites.append((ICNHeader(1, 2, w0, h0, 0, 0), img0, trf0))

    w1, h1 = 24, 12
    img1 = bytearray(w1 * h1)
    trf1 = bytearray(w1 * h1)
    for x in range(w1):
        img1[x] = 30 + (x % 20)
        trf1[x] = 0
    for x in range(w1):
        trf1[w1 + x] = 5 if x < 8 else 1
    for row in range(2, h1):
        for x in range(w1):
            img1[row * w1 + x] = 20  # blue
            trf1[row * w1 + x] = 0
    sprites.append((ICNHeader(0, 0, w1, h1, 0, 0), img1, trf1))

    w2, h2 = 160, 4
    img2 = bytearray(w2 * h2)
    trf2 = bytearray(w2 * h2)
    for row in range(h2):
        for x in range(0, 140):
            img2[row * w2 + x] = 10
            trf2[row * w2 + x] = 0
        for x in range(140, 160):
            trf2[row * w2 + x] = 1
    sprites.append((ICNHeader(-4, 0, w2, h2, 0, 0), img2, trf2))

    headers = [hdr for hdr, _, _ in sprites]
    sprite_data = [encode_sprite(img, trf, hdr.width, hdr.height) for hdr, img, trf in sprites]

    blob = build_icn(headers, sprite_data)
    return blob, sprite_data
