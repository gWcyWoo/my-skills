from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path


def write_png(
    path: Path,
    red: int,
    green: int,
    blue: int,
    *,
    width: int = 1,
    height: int = 1,
    metadata: bytes | None = None,
) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = bytes((0, *([red, green, blue] * width)))
    ancillary = chunk(b"tEXt", metadata) if metadata is not None else b""
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + ancillary
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )
