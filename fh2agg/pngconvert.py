"""
Conversion between the raw (image, transform) sprite layers used by
fh2agg.icn and a pair of ordinary PNG files that can be opened in any image
editor (GIMP, Aseprite, Photoshop, ...):

  NNNN.png       RGBA "what it looks like":
                   - transform==1 (transparent)   -> alpha = 0
                   - transform==0 (opaque)        -> palette colour, alpha = 255
                   - transform in 2..15 (special) -> a translucent black/white/grey
                                                      preview overlay so you can SEE
                                                      shadows / highlight contours

  NNNN.mask.png  Grayscale "L" image, same size, storing the *original*
                 transform value (0, 1, or 2-15) per pixel. icn_import uses
                 this to restore special shadow/highlight pixels in any area
                 you leave fully transparent in NNNN.png, while anything you
                 paint with a solid colour (alpha=255) always wins.

You generally only need to look at / edit NNNN.png. The .mask.png is there so
that repainting, say, a unit's torso doesn't wipe out its battlefield shadow
in areas you didn't touch.
"""

from __future__ import annotations

from PIL import Image

from .palette import NearestColorMatcher

ALPHA_OPAQUE_THRESHOLD = 128  # alpha >= this is treated as "opaque" on import


def _preview_color_for_special(t: int) -> tuple[int, int, int, int]:
    """Translucent preview colour for a special transform value 2-15."""
    if 2 <= t <= 5:
        # Darkening: 2 = strong, 5 = light.
        alpha = 255 - (t - 2) * 40
        return (0, 0, 0, alpha)
    if 6 <= t <= 10:
        # Lightening: 6 = strong, 10 = light.
        alpha = 255 - (t - 6) * 40
        return (255, 255, 255, alpha)
    # 11-15: reserved/uncommon - generic grey marker.
    return (128, 128, 128, 150)


def sprite_to_images(
    image: bytes, transform: bytes, width: int, height: int, palette: list[tuple[int, int, int]]
) -> tuple[Image.Image, Image.Image]:
    """Convert raw (image, transform) layers into (preview_rgba, mask_l) PIL images."""
    if width == 0 or height == 0:
        # 1x1 fully transparent placeholder so callers always get valid images.
        rgba = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        mask = Image.new("L", (1, 1), 1)
        return rgba, mask

    rgba = Image.new("RGBA", (width, height))
    mask = Image.new("L", (width, height))

    rgba_pixels = rgba.load()
    mask_pixels = mask.load()

    for y in range(height):
        row_base = y * width
        for x in range(width):
            t = transform[row_base + x]
            mask_pixels[x, y] = t

            if t == 0:
                r, g, b = palette[image[row_base + x]]
                rgba_pixels[x, y] = (r, g, b, 255)
            elif t == 1:
                rgba_pixels[x, y] = (0, 0, 0, 0)
            else:
                rgba_pixels[x, y] = _preview_color_for_special(t)

    return rgba, mask


def images_to_sprite(
    rgba_image: Image.Image,
    mask_image: Image.Image | None,
    matcher: NearestColorMatcher,
) -> tuple[bytearray, bytearray, int, int]:
    """Convert an edited RGBA PNG (plus optional original .mask.png) back into
    raw (image, transform) layers.

    Rules per pixel:
      - if a mask is provided, mask value m is 2-15, AND the RGBA pixel is
        EXACTLY the untouched preview colour for m (see
        _preview_color_for_special): restore the special transform m. This
        is what makes an un-edited sprite round-trip exactly.
      - otherwise, alpha >= ALPHA_OPAQUE_THRESHOLD: opaque, palette-match the
        RGB colour (transform=0). Any edit (including painting over a
        special-transform area) takes this path.
      - otherwise: fully transparent (transform=1).
    """
    rgba_image = rgba_image.convert("RGBA")
    width, height = rgba_image.size

    if mask_image is not None and mask_image.size != (width, height):
        raise ValueError(f"mask image size {mask_image.size} does not match RGBA image size {(width, height)}")

    if mask_image is not None:
        mask_image = mask_image.convert("L")
        mask_pixels = mask_image.load()
    else:
        mask_pixels = None

    rgba_pixels = rgba_image.load()

    size = width * height
    image = bytearray(size)
    transform = bytearray(size)

    for y in range(height):
        row_base = y * width
        for x in range(width):
            r, g, b, a = rgba_pixels[x, y]

            if mask_pixels is not None:
                m = mask_pixels[x, y]
                if 2 <= m <= 15 and (r, g, b, a) == _preview_color_for_special(m):
                    transform[row_base + x] = m
                    image[row_base + x] = 0
                    continue

            if a >= ALPHA_OPAQUE_THRESHOLD:
                transform[row_base + x] = 0
                image[row_base + x] = matcher.index_for((r, g, b))
            else:
                transform[row_base + x] = 1
                image[row_base + x] = 0

    return image, transform, width, height


def _selftest() -> None:
    # Synthetic 3-colour palette-ish setup: build a tiny palette where index 5
    # is pure red and index 7 is pure blue, rest black (index 0 = black too).
    palette = [(0, 0, 0)] * 256
    palette[5] = (255, 0, 0)
    palette[7] = (0, 0, 255)
    matcher = NearestColorMatcher(palette)

    width, height = 2, 2
    image = bytearray([5, 0, 0, 7])
    transform = bytearray([0, 1, 4, 0])  # opaque red, transparent, special(4), opaque blue

    rgba, mask = sprite_to_images(image, transform, width, height, palette)
    assert rgba.getpixel((0, 0)) == (255, 0, 0, 255)
    assert rgba.getpixel((1, 0)) == (0, 0, 0, 0)
    assert rgba.getpixel((1, 1)) == (0, 0, 255, 255)
    assert mask.getpixel((0, 1)) == 4
    # Preview colour for type 4 (darkening): alpha = 255 - (4-2)*40 = 175.
    assert rgba.getpixel((0, 1)) == (0, 0, 0, 175)

    # --- Case A: round trip WITH the mask, no edits -> exact reproduction. ---
    img_a, trf_a, w_a, h_a = images_to_sprite(rgba, mask, matcher)
    assert (w_a, h_a) == (width, height)
    assert bytes(trf_a) == bytes(transform), (bytes(trf_a), bytes(transform))
    assert bytes(img_a) == bytes(image), (bytes(img_a), bytes(image))

    # --- Case B: round trip WITHOUT the mask -> special pixel's preview
    # colour gets baked in as an ordinary opaque pixel (alpha=175 >= threshold). ---
    img_b, trf_b, _, _ = images_to_sprite(rgba, None, matcher)
    idx_special = 1 * width + 0  # pixel (0,1)
    assert trf_b[idx_special] == 0
    assert img_b[idx_special] == 0  # nearest match to (0,0,0) in our palette is index 0
    # Other pixels unaffected.
    assert trf_b[0] == 0 and img_b[0] == 5
    assert trf_b[3] == 0 and img_b[3] == 7
    assert trf_b[1] == 1  # pixel (1,0) was plain transparent, alpha=0 -> stays transparent

    # --- Case C: edit the special pixel (paint solid green over it), reimport
    # WITH the mask -> the edit wins, mask is ignored for that pixel. ---
    edited = rgba.copy()
    edited.putpixel((0, 1), (0, 255, 0, 255))
    img_c, trf_c, _, _ = images_to_sprite(edited, mask, matcher)
    assert trf_c[idx_special] == 0  # now opaque (edited), not restored to special=4
    assert img_c[idx_special] == 0  # nearest palette match for green in our tiny palette is black (index 0)
    # Untouched pixels still round-trip via the mask.
    assert trf_c[0] == 0 and img_c[0] == 5
    assert trf_c[3] == 0 and img_c[3] == 7
    assert trf_c[1] == 1

    print("pngconvert: sprite<->PNG round trip + edit/mask handling OK")


if __name__ == "__main__":
    _selftest()
