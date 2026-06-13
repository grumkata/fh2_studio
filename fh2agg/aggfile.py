"""
Reader/writer for the .AGG resource archive format used by Heroes of Might
and Magic II and read verbatim by fheroes2 (src/engine/agg_file.cpp).

File layout (all integers little-endian):

    offset 0:                     uint16   entryCount
    offset 2:                     entryCount * AggEntry (12 bytes each):
                                       uint32 nameHash
                                       uint32 dataOffset   (absolute file offset)
                                       uint32 dataSize
    offset 2 + 12*entryCount:      raw data blocks (one per entry, back to back,
                                    starting exactly at this offset)
    last 15*entryCount bytes:      entryCount * 15-byte ASCIIZ filenames
                                    (8.3 name, NUL padded to 15 bytes)

`nameHash` is calculate_agg_filename_hash(name) - see agghash.py. fheroes2's
loader refuses to open the archive at all if a single hash does not match,
so any repacked archive MUST recompute this correctly for every entry.
"""

from __future__ import annotations

import struct
from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from .agghash import calculate_agg_filename_hash

ENTRY_STRUCT = struct.Struct("<III")  # hash, offset, size
NAME_FIELD_SIZE = 15


class AggFormatError(ValueError):
    pass


@dataclass
class AggEntryInfo:
    name: str
    hash: int
    offset: int
    size: int


def _read_name_field(raw: bytes) -> str:
    if len(raw) != NAME_FIELD_SIZE:
        raise AggFormatError(f"name field must be {NAME_FIELD_SIZE} bytes, got {len(raw)}")
    nul = raw.find(b"\x00")
    if nul == -1:
        nul = len(raw)
    return raw[:nul].decode("latin-1")


def _pack_name_field(name: str) -> bytes:
    encoded = name.encode("latin-1")
    if len(encoded) >= NAME_FIELD_SIZE:
        raise AggFormatError(f"entry name {name!r} is too long for a {NAME_FIELD_SIZE}-byte AGG name field")
    return encoded + b"\x00" * (NAME_FIELD_SIZE - len(encoded))


def parse_agg(data: bytes, verify_hashes: bool = True) -> "OrderedDict[str, bytes]":
    """Parse raw AGG file bytes into an ordered {name: data} mapping.

    The dict preserves the on-disk entry order. If `verify_hashes` is True
    (default) a mismatched filename hash raises AggFormatError, mirroring
    fheroes2's own AGGFile::open(), which refuses the whole archive in that
    case.
    """
    if len(data) < 2:
        raise AggFormatError("file too small to be an AGG archive")

    (count,) = struct.unpack_from("<H", data, 0)

    entry_table_size = count * ENTRY_STRUCT.size
    name_table_size = count * NAME_FIELD_SIZE

    if entry_table_size + name_table_size >= len(data):
        raise AggFormatError("entry/name table sizes do not fit in file - not a valid AGG (or wrong file)")

    entry_table = data[2 : 2 + entry_table_size]
    name_table = data[len(data) - name_table_size :]

    result: "OrderedDict[str, bytes]" = OrderedDict()

    for i in range(count):
        name_hash, offset, size = ENTRY_STRUCT.unpack_from(entry_table, i * ENTRY_STRUCT.size)
        name = _read_name_field(name_table[i * NAME_FIELD_SIZE : (i + 1) * NAME_FIELD_SIZE])

        if verify_hashes:
            expected = calculate_agg_filename_hash(name)
            if expected != name_hash:
                raise AggFormatError(
                    f"hash mismatch for entry {i} ({name!r}): file has {name_hash}, expected {expected}"
                )

        if offset + size > len(data):
            raise AggFormatError(f"entry {i} ({name!r}) data range [{offset}:{offset + size}] exceeds file size")

        result[name] = data[offset : offset + size]

    return result


def build_agg(entries: Iterable[tuple[str, bytes]]) -> bytes:
    """Build raw AGG file bytes from an ordered iterable of (name, data).

    Recomputes the entry table, data offsets and name table from scratch.
    The resulting file is byte-for-byte a valid AGG archive as read by
    fheroes2's AGGFile::open().
    """
    entries = list(entries)
    count = len(entries)

    data_start = 2 + count * ENTRY_STRUCT.size

    entry_records = bytearray()
    data_blob = bytearray()
    name_table = bytearray()

    offset = data_start
    for name, payload in entries:
        name_hash = calculate_agg_filename_hash(name)
        entry_records += ENTRY_STRUCT.pack(name_hash, offset, len(payload))
        data_blob += payload
        name_table += _pack_name_field(name)
        offset += len(payload)

    out = bytearray()
    out += struct.pack("<H", count)
    out += entry_records
    out += data_blob
    out += name_table
    return bytes(out)


def _selftest() -> None:
    sample = [
        ("KB.PAL", b"\x01\x02\x03" * 256),
        ("TROLL.ICN", b"hello icn data"),
        ("SOME.78A", b"\x00\x01\x02\x03\x04\x05"),
        ("X.BIN", b""),
    ]

    raw = build_agg(sample)
    parsed = parse_agg(raw)

    assert list(parsed.items()) == sample, (list(parsed.items()), sample)

    # Corrupt a hash and make sure verification catches it.
    bad = bytearray(raw)
    # First entry's hash is at offset 2 (4 bytes, little endian) - flip a bit.
    bad[2] ^= 0xFF
    try:
        parse_agg(bytes(bad), verify_hashes=True)
    except AggFormatError:
        pass
    else:
        raise AssertionError("expected AggFormatError for corrupted hash")

    print(f"aggfile: round-trip of {len(sample)} entries OK, hash verification OK")


if __name__ == "__main__":
    _selftest()
