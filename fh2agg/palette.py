"""
Handling of the KB.PAL palette entry (768 bytes = 256 colors x 3 bytes,
6-bit-per-channel VGA values 0-63).

fheroes2 loads this once at startup via fheroes2::setGamePalette() and then
uses GetColorId() = GetPALColorId(r/4, g/4, b/4) to map 8-bit RGB values back
to one of the 256 palette indices when converting "true colour" surfaces
back into the game's indexed image format. We don't need the engine's exact
precomputed reverse-lookup table (GetPALColorId) - a brute-force nearest
colour search over 256 entries is plenty fast for offline tooling and gives
an equivalent (nearest match) result.
"""

from __future__ import annotations

from functools import lru_cache

PALETTE_SIZE = 768  # bytes: 256 colors * 3 (R,G,B), 6 bits per channel


class PaletteError(ValueError):
    pass


def _vga6_to_rgb8(v: int) -> int:
    """Convert a 6-bit (0-63) VGA colour component to 8-bit (0-255).

    Uses the standard VGA bit-replication scale: v8 = (v6 << 2) | (v6 >> 4).
    0 -> 0, 63 -> 255, with even spacing in between.
    """
    v &= 0x3F
    return ((v << 2) | (v >> 4)) & 0xFF


def load_palette(data: bytes) -> list[tuple[int, int, int]]:
    """Parse a 768-byte KB.PAL blob into 256 (r, g, b) tuples, 0-255 each."""
    if len(data) != PALETTE_SIZE:
        raise PaletteError(f"KB.PAL must be exactly {PALETTE_SIZE} bytes, got {len(data)}")

    palette = []
    for i in range(256):
        r, g, b = data[i * 3 : i * 3 + 3]
        palette.append((_vga6_to_rgb8(r), _vga6_to_rgb8(g), _vga6_to_rgb8(b)))
    return palette


class NearestColorMatcher:
    """Brute-force nearest-colour lookup against a 256-entry RGB palette,
    with an LRU cache since real images have far fewer unique colours than
    pixels."""

    def __init__(self, palette: list[tuple[int, int, int]]):
        if len(palette) != 256:
            raise PaletteError(f"palette must have 256 entries, got {len(palette)}")
        self._palette = palette
        # Bind a cached lookup per-instance.
        self._lookup = lru_cache(maxsize=4096)(self._lookup_uncached)

    def _lookup_uncached(self, rgb: tuple[int, int, int]) -> int:
        r, g, b = rgb
        best_index = 0
        best_dist = None
        for index, (pr, pg, pb) in enumerate(self._palette):
            dr = r - pr
            dg = g - pg
            db = b - pb
            dist = dr * dr + dg * dg + db * db
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_index = index
                if dist == 0:
                    break
        return best_index

    def index_for(self, rgb: tuple[int, int, int]) -> int:
        return self._lookup(rgb)

    def rgb_for(self, index: int) -> tuple[int, int, int]:
        return self._palette[index]


def _selftest() -> None:
    # Build a synthetic palette: index i -> grayscale (i,i,i) in 0-255 space,
    # stored as 6-bit values (i scaled down).
    raw = bytearray(PALETTE_SIZE)
    for i in range(256):
        v6 = i >> 2  # 0..63
        raw[i * 3 + 0] = v6
        raw[i * 3 + 1] = v6
        raw[i * 3 + 2] = v6

    palette = load_palette(bytes(raw))
    assert len(palette) == 256
    # index 0 -> (0,0,0); index 255 -> v6=63 -> rgb8=255
    assert palette[0] == (0, 0, 0), palette[0]
    assert palette[255] == (255, 255, 255), palette[255]

    matcher = NearestColorMatcher(palette)
    # A pure colour should match the closest grayscale step.
    idx = matcher.index_for((10, 10, 10))
    assert palette[idx][0] in (8, 12) or abs(palette[idx][0] - 10) <= 5, palette[idx]

    # Exact match for index 128's colour should return 128 (or a tie with
    # identical distance, which for this monotonic synthetic palette won't
    # happen).
    target = palette[128]
    assert matcher.index_for(target) == 128

    print("palette: VGA conversion + nearest-colour matching OK")


if __name__ == "__main__":
    _selftest()
