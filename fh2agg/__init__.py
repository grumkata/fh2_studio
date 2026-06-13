"""
fh2agg - A small toolkit for unpacking / repacking the AGG resource archives
and ICN sprite sheets used by the original Heroes of Might and Magic II
(and read, byte-for-byte compatibly, by the fheroes2 engine).

This package re-implements, in pure Python, the exact binary formats used by
fheroes2's own C++ reader (src/engine/agg_file.cpp, src/engine/image_tool.cpp).
It is intended for personal modding of a HEROES2.AGG / HEROES2X.AGG file that
YOU already own a legal copy of. It does not contain, embed, or download any
original game assets.
"""

__version__ = "0.1.0"
