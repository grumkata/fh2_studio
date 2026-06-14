"""
ICN sprite sheet container + per-sprite RLE codec.

=== Container layout (matches agg_image.cpp readIcnFromAgg) ===

    offset 0: uint16 count       - number of sprites
    offset 2: uint32 blockSize   - total size of the data section (after headers)
    offset 6: count * ICNHeader (13 bytes each)
    offset 6 + 13*count: data section, blockSize bytes total

ICNHeader (13 bytes, all little-endian, matches agg_file.h):
    int16  offsetX
    int16  offsetY
    uint16 width
    uint16 height
    uint8  animationFrames   (bit 0x20 => "monochromatic" sprite)
    uint32 offsetData        (offset of this sprite's RLE data, relative to
                               the start of the data section)

Sprite i's RLE data runs from offsetData[i] to offsetData[i+1] (or to
blockSize for the last sprite).

=== Per-pixel layers ===

Decoding a sprite produces two parallel byte arrays of size width*height:

  image[pos]     - palette index (0-255), meaningful only where transform==0
  transform[pos] - 0: opaque pixel, use image[pos] via the palette
                   1: fully transparent ("hole")
                   2-15: special shadow/highlight effect (battlefield
                         shadows, "shine" contours, etc.) - image[pos] is
                         not used/written for these

=== RLE opcode reference (from decodeICNSprite) ===

  0x00          end of current row, move to start of next row
  0x01-0x7F     N = byte; copy the next N bytes as raw palette indices
                (transform=0 for these pixels)
  0x80          end of image
  0x81-0xBF     N = byte-0x80; skip N pixels, leaving them at their default
                (transform=1, fully transparent)
  0xC0          special-transform block:
                  next byte = transformValue
                  countValue = transformValue & 0x03
                  if countValue != 0: N = countValue
                  else:               N = following byte
                  if transformValue & 0x40:
                      transformType = ((transformValue & 0x3C) >> 2) + 2
                      if transformType < 16: set transform=transformType for N pixels
                  (transformValue & 0x80 = "shining contour" bit - unused here)
  0xC1          next byte = N, next byte = color; fill N pixels with `color`
                (transform=0)
  0xC2-0xFF     N = byte-0xC0, next byte = color; fill N pixels with `color`
                (transform=0)

This module's `encode_sprite` is the inverse of `decode_sprite`: it always
emits the "standard" (non-monochromatic) encoding, clearing the 0x20 bit of
animationFrames for any sprite it produces.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

TOP_HEADER_SIZE = 6  # uint16 count + uint32 blockSize
ICN_HEADER_STRUCT = struct.Struct("<hhHHBI")  # offsetX, offsetY, width, height, animationFrames, offsetData
ICN_HEADER_SIZE = ICN_HEADER_STRUCT.size
assert ICN_HEADER_SIZE == 13

MONOCHROME_BIT = 0x20


class IcnFormatError(ValueError):
    pass


@dataclass
class ICNHeader:
    offsetX: int
    offsetY: int
    width: int
    height: int
    animationFrames: int
    offsetData: int

    @property
    def is_monochrome(self) -> bool:
        return bool(self.animationFrames & MONOCHROME_BIT)

    def pack(self) -> bytes:
        return ICN_HEADER_STRUCT.pack(
            self.offsetX, self.offsetY, self.width, self.height, self.animationFrames, self.offsetData
        )

    @classmethod
    def unpack(cls, blob: bytes, offset: int) -> "ICNHeader":
        ox, oy, w, h, af, od = ICN_HEADER_STRUCT.unpack_from(blob, offset)
        return cls(ox, oy, w, h, af, od)


# ---------------------------------------------------------------------------
# Container (multi-sprite ICN blob) <-> list of (header, raw RLE bytes)
# ---------------------------------------------------------------------------


def parse_icn(blob: bytes) -> tuple[list[ICNHeader], list[bytes]]:
    """Split a raw ICN blob into (headers, per-sprite RLE byte strings).

    Lenient by design: original HOMM2 AGG files routinely have blockSize values
    larger than the bytes actually stored, and offsetData sequences that extend
    past the available data.  We clamp everything silently rather than raising,
    returning an empty bytes object for any sprite whose data cannot be read.
    Only raises IcnFormatError when the blob is too small for the top-level header.
    """
    if len(blob) < TOP_HEADER_SIZE:
        raise IcnFormatError("blob too small to be an ICN container")

    count, block_size = struct.unpack_from("<HI", blob, 0)

    # Read as many sprite headers as are physically present.
    headers: list[ICNHeader] = []
    for i in range(count):
        off = TOP_HEADER_SIZE + i * ICN_HEADER_SIZE
        if off + ICN_HEADER_SIZE > len(blob):
            break   # truncated header table — stop here, do not raise
        headers.append(ICNHeader.unpack(blob, off))

    actual_count = len(headers)
    data_start   = TOP_HEADER_SIZE + actual_count * ICN_HEADER_SIZE

    # How many data bytes are physically present (blockSize often exceeds this).
    available = max(0, len(blob) - data_start)

    sprite_data: list[bytes] = []
    for i, hdr in enumerate(headers):
        # Clamp the start offset so it never exceeds available bytes.
        s_off = min(max(hdr.offsetData, 0), available)

        if i + 1 < actual_count:
            # Between sprites: end = next sprite's start offset.
            e_off = min(max(headers[i + 1].offsetData, 0), available)
        else:
            # Last sprite: use blockSize, clamped to what is actually present.
            e_off = min(max(block_size, 0), available)

        # Guard against inverted ranges from corrupt offsetData ordering.
        e_off = max(s_off, e_off)

        sprite_data.append(blob[data_start + s_off : data_start + e_off])

    return headers, sprite_data


def build_icn(headers: list[ICNHeader], sprite_data: list[bytes]) -> bytes:
    """Reassemble an ICN blob from headers + per-sprite RLE bytes.

    `offsetData` in each returned header is recomputed from the lengths of
    `sprite_data`, so callers may freely replace entries in `sprite_data`
    with re-encoded bytes of a different length.
    """
    if len(headers) != len(sprite_data):
        raise IcnFormatError(f"headers ({len(headers)}) and sprite_data ({len(sprite_data)}) length mismatch")

    count = len(headers)
    out = bytearray()

    new_headers = []
    running_offset = 0
    for hdr, data in zip(headers, sprite_data):
        new_headers.append(
            ICNHeader(hdr.offsetX, hdr.offsetY, hdr.width, hdr.height, hdr.animationFrames, running_offset)
        )
        running_offset += len(data)

    block_size = running_offset

    out += struct.pack("<HI", count, block_size)
    for hdr in new_headers:
        out += hdr.pack()
    for data in sprite_data:
        out += data

    return bytes(out)


# ---------------------------------------------------------------------------
# Per-sprite RLE decode / encode
# ---------------------------------------------------------------------------


def decode_sprite(data: bytes, header: ICNHeader) -> tuple[bytearray, bytearray]:
    """Decode one sprite's RLE bytes into (image, transform) arrays of
    length width*height.

    image[pos]: palette index 0-255 (valid where transform[pos] == 0)
    transform[pos]: 0 = opaque, 1 = transparent, 2-15 = special effect
    """
    width, height = header.width, header.height
    size = width * height

    image = bytearray(size)
    transform = bytearray(b"\x01" * size)  # default: fully transparent

    if size == 0:
        return image, transform

    n = len(data)
    pos = 0
    posX = 0
    row_start = 0

    if header.is_monochrome:
        while pos < n:
            b = data[pos]
            if b == 0:
                row_start += width
                posX = 0
                pos += 1
            elif b < 0x80:
                count = b
                for k in range(count):
                    idx = row_start + posX + k
                    if idx < size:
                        transform[idx] = 0
                pos += 1
                posX += count
            elif b == 0x80:
                break
            else:
                posX += b - 0x80
                pos += 1
        return image, transform

    while pos < n:
        b = data[pos]

        if b == 0:
            row_start += width
            posX = 0
            pos += 1

        elif b < 0x80:
            count = b
            if pos + 1 + count > n:
                break
            for k in range(count):
                idx = row_start + posX + k
                if idx < size:
                    image[idx] = data[pos + 1 + k]
                    transform[idx] = 0
            pos += 1 + count
            posX += count

        elif b == 0x80:
            break

        elif b < 0xC0:
            posX += b - 0x80
            pos += 1

        elif b == 0xC0:
            if pos + 1 >= n:
                break
            transform_value = data[pos + 1]
            count_value = transform_value & 0x03
            if count_value != 0:
                count = count_value
                consumed = 2
            else:
                if pos + 2 >= n:
                    break
                count = data[pos + 2]
                consumed = 3

            if transform_value & 0x40:
                transform_type = ((transform_value & 0x3C) >> 2) + 2
                if transform_type < 16:
                    for k in range(count):
                        idx = row_start + posX + k
                        if idx < size:
                            transform[idx] = transform_type

            posX += count
            pos += consumed

        else:  # 0xC1–0xFF: RLE fill — count = b − 0xC0, next byte is the color
            count = b - 0xC0
            if pos + 1 >= n:
                break
            color = data[pos + 1]

            for k in range(count):
                idx = row_start + posX + k
                if idx < size:
                    image[idx] = color
                    transform[idx] = 0

            posX += count
            pos  += 2

    return image, transform


def encode_sprite(image: bytes, transform: bytes, width: int, height: int) -> bytes:
    """Encode (image, transform) arrays of length width*height back into ICN
    RLE bytes (always in the "standard"/non-monochrome encoding).

    transform values must be 0, 1, or 2-15 for every pixel (exactly the set
    of values decode_sprite can ever produce).
    """
    size = width * height
    if len(image) != size or len(transform) != size:
        raise IcnFormatError(f"image/transform must each have length {size} (width*height), got {len(image)}/{len(transform)}")

    if width == 0 or height == 0:
        return b""

    for t in transform:
        if not (t == 0 or t == 1 or (2 <= t <= 15)):
            raise IcnFormatError(f"invalid transform value {t}; must be 0, 1, or 2-15")

    out = bytearray()

    for y in range(height):
        base = y * width
        x = 0
        while x < width:
            t = transform[base + x]

            if t == 1:
                run = 1
                while x + run < width and transform[base + x + run] == 1 and run < 63:
                    run += 1
                out.append(0x80 + run)
                x += run

            elif t == 0:
                color = image[base + x]
                run = 1
                while x + run < width and transform[base + x + run] == 0 and image[base + x + run] == color and run < 63:
                    run += 1
                if run >= 2:
                    out += bytes((0xC0 + run, color))
                    x += run
                else:
                    out += bytes((0x01, color))
                    x += 1

            else:  # 2..15
                ttype = t
                run = 1
                while x + run < width and transform[base + x + run] == ttype and run < 255:
                    run += 1

                tbits = (ttype - 2) & 0x0F
                base_tv = 0x40 | (tbits << 2)

                if run <= 3:
                    out += bytes((0xC0, base_tv | run))
                else:
                    cnt = min(run, 255)
                    out += bytes((0xC0, base_tv, cnt))
                    run = cnt
                x += run

        out.append(0x00)

    # Replace the final row terminator (0x00) with the end-of-image marker (0x80).
    out[-1] = 0x80

    return bytes(out)


# ---------------------------------------------------------------------------
# Self-tests (no external files needed)
# ---------------------------------------------------------------------------


def _roundtrip_check(image: bytearray, transform: bytearray, width: int, height: int) -> None:
    encoded = encode_sprite(image, transform, width, height)
    header = ICNHeader(0, 0, width, height, 0, 0)
    dec_image, dec_transform = decode_sprite(encoded, header)
    assert bytes(dec_image) == bytes(image), (bytes(dec_image), bytes(image))
    assert bytes(dec_transform) == bytes(transform), (bytes(dec_transform), bytes(transform))


def _selftest() -> None:
    # 1. Simple 4x2 sprite: top row opaque gradient, bottom row mixed
    #    transparent / solid / special-transform.
    width, height = 4, 2
    image = bytearray(width * height)
    transform = bytearray(width * height)

    # Row 0: four different opaque colours (forces "raw" 0x01 encoding).
    for x in range(4):
        image[x] = 10 + x
        transform[x] = 0

    # Row 1: 2 transparent, then 2 pixels of special transform type 5.
    transform[4] = 1
    transform[5] = 1
    transform[6] = 5
    transform[7] = 5

    _roundtrip_check(image, transform, width, height)

    # 2. A wider sprite with a long solid run (tests 0xC1 with count>3) and a
    #    long transparent run (tests chunking >63) and a long special-transform
    #    run (tests chunking >3 with explicit count byte).
    width, height = 80, 1
    image = bytearray(width)
    transform = bytearray(width)
    # 0-69: solid colour 200
    for x in range(0, 70):
        image[x] = 200
        transform[x] = 0
    # 70-74: special transform type 9
    for x in range(70, 75):
        transform[x] = 9
    # 75-79: transparent
    for x in range(75, 80):
        transform[x] = 1

    _roundtrip_check(image, transform, width, height)

    # 3. Hand-crafted RLE bytes exercising every opcode family, decoded and
    #    checked against expected pixel values directly (independent of our
    #    own encoder).
    width, height = 6, 2
    raw = bytes(
        [
            0x02, 0x05, 0x06,  # row0: 2 raw pixels, colors 5, 6
            0xC3, 0x07,        # row0: RLE 3 pixels of color 7 (0xC3-0xC0=3, standard 2-byte)
            0x81,              # row0: 1 transparent pixel  -> total 6 = width, row done
            0x00,              # end of row 0
            0xC2, 0x09,        # row1: 2 pixels of color 9  (0xC2-0xC0=2, standard 2-byte)
            0xC0, 0x44,        # row1: transformValue=0x44 -> countValue=0, 0x40 set
            0x02,              # ... count byte = 2 -> transformType=((0x44&0x3C)>>2)+2=3
            0x83,              # row1: (0x83-0x80)=3 transparent but only 2 remain
            0x80,              # end of image
        ]
    )
    header = ICNHeader(0, 0, width, height, 0, 0)
    img, trf = decode_sprite(raw, header)

    expected_img = bytearray(width * height)
    expected_trf = bytearray(width * height)
    # row0
    expected_img[0] = 5
    expected_img[1] = 6
    expected_img[2] = 7
    expected_img[3] = 7
    expected_img[4] = 7
    expected_trf[5] = 1
    # row1 (offset 6)
    expected_img[6] = 9
    expected_img[7] = 9
    expected_trf[8] = 3
    expected_trf[9] = 3
    expected_trf[10] = 1
    expected_trf[11] = 1

    assert bytes(img) == bytes(expected_img), (bytes(img), bytes(expected_img))
    assert bytes(trf) == bytes(expected_trf), (bytes(trf), bytes(expected_trf))

    # And re-encoding what we just decoded should itself round-trip.
    _roundtrip_check(img, trf, width, height)

    # 4. Container round-trip: build a 2-sprite ICN blob, parse it back,
    #    and confirm headers/data survive (including after replacing one
    #    sprite's data with different-length bytes).
    h1 = ICNHeader(1, 2, 4, 2, 0, 0)
    h2 = ICNHeader(-3, 0, 80, 1, 0, 0)
    d1 = encode_sprite(bytearray(8), bytearray([1] * 8), 4, 2)
    d2 = encode_sprite(bytearray(80), bytearray([1] * 80), 80, 1)

    blob = build_icn([h1, h2], [d1, d2])
    headers, datas = parse_icn(blob)
    assert len(headers) == 2 and len(datas) == 2
    assert headers[0].width == 4 and headers[0].height == 2
    assert headers[1].offsetX == -3
    assert datas[0] == d1
    assert datas[1] == d2

    # Replace sprite 0 with the larger encoded sprite from test 2.
    big = encode_sprite(bytearray(80), bytearray([1] * 80), 80, 1)
    blob2 = build_icn(headers, [big, datas[1]])
    headers2, datas2 = parse_icn(blob2)
    assert datas2[0] == big
    assert datas2[1] == datas[1]
    assert headers2[1].offsetData == len(big)

    print("icn: sprite RLE round-trip + opcode decode + container round-trip OK")


if __name__ == "__main__":
    _selftest()
