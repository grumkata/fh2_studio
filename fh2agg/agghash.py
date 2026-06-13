"""
Re-implementation of fheroes2::calculateAggFilenameHash from
src/engine/agg_file.cpp.

The original C++:

    uint32_t calculateAggFilenameHash( const std::string_view str )
    {
        uint32_t hash = 0;
        uint32_t sum = 0;

        for ( auto iter = str.rbegin(); iter != str.rend(); ++iter ) {
            const unsigned char c = static_cast<unsigned char>( std::toupper(
                static_cast<unsigned char>( *iter ) ) );

            hash = ( hash << 5 ) + ( hash >> 25 );

            sum += c;
            hash += sum + c;
        }

        return hash;
    }

All arithmetic on `hash` and `sum` is uint32_t, i.e. it wraps modulo 2**32.
The function is verified against the real compiled C++ implementation in
selftest.py (see KNOWN_HASHES).
"""

from __future__ import annotations

MASK32 = 0xFFFFFFFF


def calculate_agg_filename_hash(name: str) -> int:
    """Compute the 32-bit AGG filename hash for ``name``.

    Matches fheroes2's calculateAggFilenameHash exactly: characters are
    processed in reverse order, upper-cased, using the same wrapping
    32-bit arithmetic as the C++ uint32_t implementation.
    """
    h = 0
    s = 0

    # str.upper() can in theory map a single char to multiple chars for some
    # unicode input, but AGG filenames are always plain ASCII 8.3 names, so
    # this is safe. We still guard against anything unexpected.
    upper = name.upper()

    for ch in reversed(upper):
        c = ord(ch) & 0xFF

        h = ((h << 5) & MASK32) + (h >> 25)
        h &= MASK32

        s = (s + c) & MASK32
        h = (h + s + c) & MASK32

    return h


# Reference values captured by compiling and running the real C++ function
# (see selftest.py for the verification step). Used for a self-test so this
# Python port can be trusted without needing a copy of the original game.
KNOWN_HASHES = {
    "A": 130,
    "AB": 4420,
    "TROLL.ICN": 1191338262,
    "KB.PAL": 1031509959,
    "HEROES2.AGG": 357381261,
    "kb.pal": 1031509959,  # hash is case-insensitive
    "monster04.icn": 4179462504,
    "": 0,
}


def _selftest() -> None:
    for name, expected in KNOWN_HASHES.items():
        actual = calculate_agg_filename_hash(name)
        assert actual == expected, f"hash({name!r}) = {actual}, expected {expected}"
    print(f"agghash: {len(KNOWN_HASHES)} known-value checks passed")


if __name__ == "__main__":
    _selftest()
