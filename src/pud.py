from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct


@dataclass
class PudChunk:
    tag: str
    data: bytes
    offset: int


@dataclass
class PudMap:
    path: Path
    chunks: list[PudChunk] = field(default_factory=list)

    @classmethod
    def read(cls, path: str | Path) -> "PudMap":
        path = Path(path)
        blob = path.read_bytes()
        chunks: list[PudChunk] = []
        pos = 0
        while pos + 8 <= len(blob):
            raw_tag, size = struct.unpack_from("<4sI", blob, pos)
            tag = raw_tag.decode("ascii", "replace")
            start = pos + 8
            end = start + size
            if end > len(blob):
                raise ValueError(f"Truncated {tag!r} chunk at 0x{pos:X}")
            chunks.append(PudChunk(tag, blob[start:end], pos))
            pos = end
        if pos != len(blob):
            raise ValueError(f"Trailing {len(blob) - pos} byte(s) after final chunk")
        if not chunks or chunks[0].tag != "TYPE":
            raise ValueError("Not a Warcraft II PUD (missing TYPE chunk)")
        return cls(path, chunks)

    def first(self, tag: str) -> bytes | None:
        return next((c.data for c in self.chunks if c.tag == tag), None)

    def text(self, tag: str) -> str:
        data = self.first(tag) or b""
        return data.split(b"\0", 1)[0].decode("cp1252", "replace")

    @property
    def dimensions(self) -> tuple[int, int]:
        data = self.first("DIM ")
        return struct.unpack_from("<HH", data) if data and len(data) >= 4 else (0, 0)

    @property
    def terrain(self) -> int | None:
        data = self.first("ERA ")
        return struct.unpack_from("<H", data)[0] if data and len(data) >= 2 else None

    @property
    def units(self) -> int:
        data = self.first("UNIT") or b""
        # Warcraft II UNIT records are 8 bytes in classic PUD maps.
        return len(data) // 8

    def summary(self) -> str:
        width, height = self.dimensions
        lines = [
            f"File: {self.path.name}",
            f"Name: {self.text('DESC') or '(unnamed)'}",
            f"Dimensions: {width} x {height}",
            f"Terrain ID: {self.terrain}",
            f"UNIT records: {self.units}",
            "Chunks: " + ", ".join(f"{c.tag}({len(c.data)})" for c in self.chunks),
        ]
        return "\n".join(lines)

