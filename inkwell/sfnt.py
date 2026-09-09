"""Just enough TrueType to embed a font in a PDF.

Reads the table directory, the character map and the advance widths, and
can lift one face out of a .ttc collection as a standalone font file --
which is what a PDF's FontFile2 has to contain.

Nothing here draws anything; it only answers "which glyph is this
character, how wide is it, and what bytes do I embed".
"""

from __future__ import annotations

import struct
from pathlib import Path


class Face:
    """One face from a .ttf or one member of a .ttc."""

    def __init__(self, path, index: int = 0) -> None:
        self.path = Path(path)
        self.index = index
        self.data = self.path.read_bytes()
        self._tables = self._directory()
        self.units = self._units()
        self.cmap = self._cmap()
        self._widths = self._hmtx()
        self.name = self._name(6) or self.path.stem
        self.flags, self.bbox, self.italic_angle = self._descriptor()

    # --- the table directory ---------------------------------------------
    def _origin(self) -> int:
        if self.data[:4] != b"ttcf":
            return 0
        count, = struct.unpack(">I", self.data[8:12])
        if not 0 <= self.index < count:
            raise ValueError(f"{self.path} has no face {self.index}")
        start, = struct.unpack(">I", self.data[12 + 4 * self.index:
                                               16 + 4 * self.index])
        return start

    def _directory(self) -> dict:
        base = self._origin()
        count, = struct.unpack(">H", self.data[base + 4:base + 6])
        out = {}
        for i in range(count):
            tag, checksum, offset, length = struct.unpack(
                ">4sIII", self.data[base + 12 + 16 * i: base + 28 + 16 * i])
            out[tag] = (offset, length, checksum)
        return out

    def table(self, tag: bytes) -> bytes:
        offset, length, _checksum = self._tables[tag]
        return self.data[offset:offset + length]

    # --- what we need out of it -------------------------------------------
    def _units(self) -> int:
        return struct.unpack(">H", self.table(b"head")[18:20])[0] or 1000

    def _cmap(self) -> dict:
        raw = self.table(b"cmap")
        count, = struct.unpack(">H", raw[2:4])
        chosen = None
        for i in range(count):
            pid, eid, offset = struct.unpack(">HHI", raw[4 + 8 * i: 12 + 8 * i])
            kind, = struct.unpack(">H", raw[offset:offset + 2])
            wide = (pid, eid) in ((3, 10), (0, 4), (0, 6))
            if kind == 12 and wide:
                chosen = (offset, 12)
                break
            if kind == 4 and chosen is None and (pid, eid) in ((3, 1), (0, 3)):
                chosen = (offset, 4)
        if chosen is None:
            return {}
        offset, kind = chosen
        return (self._cmap4 if kind == 4 else self._cmap12)(raw, offset)

    @staticmethod
    def _cmap4(raw: bytes, at: int) -> dict:
        pairs, = struct.unpack(">H", raw[at + 6:at + 8])
        count = pairs // 2
        ends = struct.unpack(f">{count}H", raw[at + 14:at + 14 + pairs])
        starts_at = at + 16 + pairs
        starts = struct.unpack(f">{count}H", raw[starts_at:starts_at + pairs])
        deltas_at = starts_at + pairs
        deltas = struct.unpack(f">{count}h", raw[deltas_at:deltas_at + pairs])
        ranges_at = deltas_at + pairs
        ranges = struct.unpack(f">{count}H", raw[ranges_at:ranges_at + pairs])
        out = {}
        for i in range(count):
            for code in range(starts[i], min(ends[i], 0xFFFF) + 1):
                if ranges[i] == 0:
                    glyph = (code + deltas[i]) & 0xFFFF
                else:
                    at_glyph = ranges_at + 2 * i + ranges[i] + 2 * (code - starts[i])
                    if at_glyph + 2 > len(raw):
                        continue
                    glyph, = struct.unpack(">H", raw[at_glyph:at_glyph + 2])
                    if glyph:
                        glyph = (glyph + deltas[i]) & 0xFFFF
                if glyph:
                    out[code] = glyph
        return out

    @staticmethod
    def _cmap12(raw: bytes, at: int) -> dict:
        groups, = struct.unpack(">I", raw[at + 12:at + 16])
        out = {}
        for i in range(groups):
            first, last, glyph = struct.unpack(
                ">III", raw[at + 16 + 12 * i: at + 28 + 12 * i])
            for offset, code in enumerate(range(first, last + 1)):
                out[code] = glyph + offset
        return out

    def _hmtx(self) -> list:
        count, = struct.unpack(">H", self.table(b"hhea")[34:36])
        raw = self.table(b"hmtx")
        return [struct.unpack(">H", raw[4 * i:4 * i + 2])[0]
                for i in range(min(count, len(raw) // 4))]

    def _name(self, which: int) -> str:
        raw = self.table(b"name")
        count, strings = struct.unpack(">HH", raw[2:6])
        for i in range(count):
            pid, eid, lang, kind, length, offset = struct.unpack(
                ">6H", raw[6 + 12 * i: 18 + 12 * i])
            if kind != which:
                continue
            text = raw[strings + offset: strings + offset + length]
            try:
                return (text.decode("utf-16-be") if pid == 3
                        else text.decode("latin-1")).strip()
            except UnicodeDecodeError:
                continue
        return ""

    def _descriptor(self) -> tuple:
        head = self.table(b"head")
        scale = 1000 / self.units
        bbox = [round(v * scale) for v in struct.unpack(">4h", head[36:44])]
        post = self.table(b"post")
        angle = struct.unpack(">i", post[4:8])[0] / 65536.0
        fixed_pitch, = struct.unpack(">I", post[12:16])
        flags = 4                                  # symbolic
        if fixed_pitch:
            flags |= 1
        if angle:
            flags |= 64
        return flags, bbox, angle

    # --- what the PDF asks for --------------------------------------------
    def glyph(self, character: str) -> int:
        return self.cmap.get(ord(character), 0)

    def has(self, character: str) -> bool:
        return ord(character) in self.cmap

    def width(self, glyph: int) -> int:
        """Advance in 1000ths of an em, the unit PDF wants."""
        if not self._widths:
            return 600
        raw = self._widths[glyph] if glyph < len(self._widths) else self._widths[-1]
        return round(raw * 1000 / self.units)

    @property
    def advance(self) -> float:
        """Advance of a monospace cell, in ems."""
        return (self._widths[0] / self.units) if self._widths else 0.6

    def outline_height(self, character: str) -> float:
        """How tall a glyph's outline is, in ems.

        Needed for the block-drawing characters: a terminal stacks them
        with no gap, so a PDF has to know their real height to do the same.
        """
        glyph = self.glyph(character)
        if not glyph or b"loca" not in self._tables or b"glyf" not in self._tables:
            return 1.0
        long_format = struct.unpack(">h", self.table(b"head")[50:52])[0]
        loca = self.table(b"loca")
        if long_format:
            start, end = struct.unpack(">II", loca[4 * glyph:4 * glyph + 8])
        else:
            first, second = struct.unpack(">HH", loca[2 * glyph:2 * glyph + 4])
            start, end = first * 2, second * 2
        if end <= start:
            return 1.0
        header = self.table(b"glyf")[start:start + 10]
        _contours, _x0, y0, _x1, y1 = struct.unpack(">5h", header)
        return (y1 - y0) / self.units

    def standalone(self) -> bytes:
        """This face as its own font file, for embedding."""
        if self.data[:4] != b"ttcf":
            return self.data
        tags = sorted(self._tables)
        count = len(tags)
        power = 1
        while power * 2 <= count:
            power *= 2
        header = struct.pack(">IHHHH", 0x00010000, count, power * 16,
                             (power).bit_length() - 1, (count - power) * 16)
        directory = b""
        body = b""
        at = len(header) + 16 * count
        for tag in tags:
            offset, length, checksum = self._tables[tag]
            directory += struct.pack(">4sIII", tag, checksum, at + len(body),
                                     length)
            chunk = self.data[offset:offset + length]
            body += chunk + b"\0" * (-len(chunk) % 4)
        return header + directory + body
