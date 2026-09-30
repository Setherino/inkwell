"""Export the page as a PDF, the way it looks on screen.

Same layout, same grid, same colours, same math -- but where the terminal
had to fake bold and italic with look-alike code points (𝗯𝗼𝗹𝗱, 𝘪𝘵𝘢𝘭𝘪𝘤),
paper has real type, so those are decoded back to ordinary letters drawn in
the real Bold and Italic faces. The text comes out selectable and
searchable rather than a picture of a terminal.

No dependencies: the PDF is written here, the font is read by sfnt.py, and
zlib does the compression.
"""

from __future__ import annotations

import os
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import urwid

from . import theme as themes
from . import typography as T
from .document import Document
from .sfnt import Face

FONT = "/System/Library/Fonts/Menlo.ttc"
FACES = {"regular": 0, "bold": 1, "italic": 2, "bold italic": 3}

# A monospace TrueType family per platform, in order of preference. One
# .ttc with four faces on a Mac; four files elsewhere.
_WIN = "C:\\Windows\\Fonts\\"
_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono"
_LIBERATION = "/usr/share/fonts/truetype/liberation/LiberationMono"
CANDIDATES = {
    "darwin": [{name: (FONT, index) for name, index in FACES.items()}],
    "win32": [{"regular": (_WIN + "consola.ttf", 0), "bold": (_WIN + "consolab.ttf", 0),
               "italic": (_WIN + "consolai.ttf", 0), "bold italic": (_WIN + "consolaz.ttf", 0)},
              {"regular": (_WIN + "cour.ttf", 0), "bold": (_WIN + "courbd.ttf", 0),
               "italic": (_WIN + "couri.ttf", 0), "bold italic": (_WIN + "courbi.ttf", 0)}],
    "linux": [{"regular": (_DEJAVU + ".ttf", 0), "bold": (_DEJAVU + "-Bold.ttf", 0),
               "italic": (_DEJAVU + "-Oblique.ttf", 0),
               "bold italic": (_DEJAVU + "-BoldOblique.ttf", 0)},
              {"regular": (_LIBERATION + "-Regular.ttf", 0),
               "bold": (_LIBERATION + "-Bold.ttf", 0),
               "italic": (_LIBERATION + "-Italic.ttf", 0),
               "bold italic": (_LIBERATION + "-BoldItalic.ttf", 0)}],
}


class NoFont(RuntimeError):
    """No monospace TrueType family to draw the PDF with."""


def fonts(platform: str = sys.platform, exists=os.path.exists) -> dict:
    """{face name: (path, index)} for the first family that is all present."""
    order = [platform] + [p for p in CANDIDATES if p != platform]
    for plat in order:
        for family in CANDIDATES.get(plat, []):
            if all(exists(path) for path, _index in family.values()):
                return dict(family)
    looked = sorted({path for fam in CANDIDATES.values() for f in fam
                     for path, _i in f.values()})
    raise NoFont("no monospace TrueType font found; looked for "
                 + ", ".join(looked))

PAGES = {"letter": (612.0, 792.0), "a4": (595.28, 841.89)}
MARGIN = 40.0
LEADING = 1.30           # line height, in ems
FOOTER = 18.0            # room under the text for the page number

# What the terminal draws with a look-alike, and what it really means.
LOOKALIKE: dict = {}
for _name, _table in (("bold", T.BOLD), ("italic", T.ITALIC),
                      ("mono", T.MONO), ("smallcaps", T.SMALLCAPS)):
    for _plain, _fancy in _table.items():
        LOOKALIKE[chr(_fancy)] = (chr(_plain), _name)

# Style per attribute, for the text the document did not fake.
STYLED = {"title": "bold", "section": "bold", "head": "bold",
          "term": "bold", "kv_value": "bold", "table_head": "bold",
          "callout": "bold", "quote": "italic", "ask_mark": "bold"}

# Glyphs no face on the machine can draw, and the nearest honest thing.
INSTEAD = {"ₚ": "p", "ₕ": "h", "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n",
           "ₛ": "s", "ₜ": "t", "ᵢ": "i", "ⱼ": "j", "ᵣ": "r", "ᵤ": "u",
           "ᵥ": "v"}


@dataclass
class Run:
    """A stretch of one colour and one face on one line."""

    column: int
    text: str
    style: str
    colour: tuple


@dataclass
class Line:
    """One line: its runs, and how far down to the next one."""

    runs: list = field(default_factory=list)
    step: float = LEADING          # in ems

    def __bool__(self) -> bool:
        return bool(self.runs)


@dataclass
class Sheet:
    """One page's worth of lines."""

    lines: list = field(default_factory=list)

    @property
    def depth(self) -> float:
        return sum(line.step for line in self.lines)


def colour_of(name: str, palette: dict) -> tuple:
    entry = palette.get(name) or palette["body"]
    return _rgb(entry[3] or "#000")


def _rgb(value: str) -> tuple:
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return (0.0, 0.0, 0.0)
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _decode(text: str, style: str) -> list:
    """Split a run into (text, style) pieces, undoing the look-alikes."""
    pieces: list = []
    for character in text:
        plain, faked = LOOKALIKE.get(character, (character, None))
        if faked == "smallcaps":
            plain, want = plain.upper(), style
        elif faked == "bold":
            want = "bold italic" if style == "italic" else "bold"
        elif faked == "italic":
            want = "bold italic" if style == "bold" else "italic"
        elif faked == "mono":
            want = style
        else:
            want = style
        plain = INSTEAD.get(plain, plain)
        if pieces and pieces[-1][1] == want:
            pieces[-1][0] += plain
        else:
            pieces.append([plain, want])
    return [(text, style) for text, style in pieces]


class Book:
    """The document, cut into pages."""

    def __init__(self, notes, cols: int = 92, theme: str = "light",
                 page: str = "letter") -> None:
        self.notes = list(notes)
        self.cols = max(20, cols)
        self.palette = themes.PALETTES.get(theme, themes.LIGHT)
        self.width, self.height = PAGES.get(page, PAGES["letter"])
        self.faces = {name: Face(path, index)
                      for name, (path, index) in fonts().items()}
        self.regular = self.faces["regular"]

        room = self.width - 2 * MARGIN
        self.size = min(11.0, room / (self.cols * self.regular.advance))
        self.cell = self.size * self.regular.advance
        self.leading = self.size * LEADING
        # Block-drawing characters have to stack with no gap, the way a
        # terminal stacks them, so art rows step by the glyph's own height.
        self.art_step = self.regular.outline_height("█")
        self.depth = (self.height - 2 * MARGIN - FOOTER) / self.size
        self.rows = max(1, int(self.depth / LEADING))
        self.undrawable: set = set()
        self.sheets = self._paginate()

    # --- turning notes into lines -----------------------------------------
    def _lines(self) -> list:
        """Every line of the document, grouped by the note it came from."""
        doc = Document()
        doc.rebuild(self.notes)
        groups = []
        for note in self.notes:
            plan = doc.plan(note, self.cols, maxrow=200, unicode_ok=True,
                            big=True, stamps=False)
            if plan.big and not self._can_draw(plan.big):
                # The screen can set a title in a font built from sextants;
                # the embedded face has no such glyphs, so set it as type.
                plan = doc.plan(note, self.cols, maxrow=200, unicode_ok=True,
                                big=False, stamps=False)
            lines = [Line() for _ in range(plan.blank_before)]
            if plan.big:
                # A block-font title: the plan says which font and which
                # words, so draw the same glyph rows the screen would.
                size, words = plan.big
                colour = colour_of("title", self.palette)
                # Each line of the title is one block of art: centre the
                # block as a whole, or its rows shear apart.
                for words_line in words:
                    art = _block_art(words_line, size)
                    wide = max((T.cols(row) for row in art), default=0)
                    pad = max(0, (self.cols - wide) // 2)
                    for index, row in enumerate(art):
                        last = index == len(art) - 1
                        runs = [Run(pad + T.cols(before), piece, face, colour)
                                for before, piece, face in
                                _placed(self._drawable(row, "regular"))]
                        lines.append(Line(runs,
                                          LEADING if last else self.art_step))
            for row in plan.rows:
                lines.append(Line(self._runs(row)))
            lines += [Line() for _ in range(plan.blank_after)]
            groups.append(lines)
        return groups

    def _runs(self, row) -> list:
        out = []
        column = 0
        for attr, text in row:
            if not text:
                continue
            style = STYLED.get(attr, "regular")
            colour = colour_of(attr, self.palette) if attr else colour_of(
                "body", self.palette)
            at = column
            for piece, face in _decode(text, style):
                for chunk, chunk_face in self._drawable(piece, face):
                    if chunk.strip():
                        out.append(Run(at, chunk, chunk_face, colour))
                    at += T.cols(chunk)
            column += T.cols(text)
        return out

    def _can_draw(self, big) -> bool:
        """Can the embedded face actually draw this block-font title?"""
        _size, words = big
        return all(self.regular.has(character)
                   for line in words
                   for row in _block_art(line, _size)
                   for character in row if character != " ")

    def _drawable(self, text: str, style: str) -> list:
        """Split a piece by what can actually be drawn.

        The bold face may be missing a symbol the regular one has, so fall
        back to regular before giving up; anything no face can draw becomes
        a space, and is reported rather than left as an empty box.
        """
        pieces: list = []
        for character in text:
            if self.faces[style].has(character):
                face = style
            elif self.regular.has(character):
                face = "regular"
            else:
                self.undrawable.add(character)
                character, face = " ", style
            if pieces and pieces[-1][1] == face:
                pieces[-1][0] += character
            else:
                pieces.append([character, face])
        return [(text, face) for text, face in pieces]

    def _paginate(self) -> list:
        """Fill pages, keeping a note whole when it fits on one."""
        sheets = [Sheet()]
        for lines in self._lines():
            wanted = sum(line.step for line in lines)
            room = self.depth - sheets[-1].depth
            # Keep a note whole, and never leave one strand at the foot of
            # a page: if it will not fit, or barely fits, start the page.
            if lines and any(lines) and wanted <= self.depth and (
                    wanted > room or room <= 2 * LEADING):
                sheets.append(Sheet())
            for line in lines:
                if sheets[-1].depth + line.step > self.depth:
                    sheets.append(Sheet())
                sheets[-1].lines.append(line)
        while sheets and not any(sheets[-1].lines):
            sheets.pop()
        return sheets or [Sheet()]

    # --- drawing ----------------------------------------------------------
    def _content(self, sheet: Sheet, number: int) -> bytes:
        parts = []
        used = {}
        y = self.height - MARGIN - self.size
        for line in sheet.lines:
            for run in line.runs:
                face = self.faces[run.style]
                glyphs = "".join(f"{face.glyph(c):04X}" for c in run.text)
                used.setdefault(run.style, set()).update(
                    face.glyph(c) for c in run.text)
                x = MARGIN + run.column * self.cell
                red, green, blue = run.colour
                parts.append(
                    f"BT /{run.style.replace(' ', '')} {self.size:.2f} Tf "
                    f"{red:.3f} {green:.3f} {blue:.3f} rg "
                    f"{x:.2f} {y:.2f} Td <{glyphs}> Tj ET")
            y -= line.step * self.size
        stamp = f"{number}"
        face = self.faces["regular"]
        glyphs = "".join(f"{face.glyph(c):04X}" for c in stamp)
        used.setdefault("regular", set()).update(face.glyph(c) for c in stamp)
        grey = _rgb(self.palette["meta"][3])
        parts.append(
            f"BT /regular {self.size * 0.85:.2f} Tf "
            f"{grey[0]:.3f} {grey[1]:.3f} {grey[2]:.3f} rg "
            f"{(self.width - len(stamp) * self.cell) / 2:.2f} "
            f"{MARGIN * 0.6:.2f} Td <{glyphs}> Tj ET")
        self._used = getattr(self, "_used", {})
        for style, glyph_ids in used.items():
            self._used.setdefault(style, set()).update(glyph_ids)
        return "\n".join(parts).encode("latin-1")


class Writer:
    """A very small PDF file writer."""

    def __init__(self) -> None:
        self.objects: list = [None]         # object 0 is the free head

    def add(self, body: bytes) -> int:
        self.objects.append(body)
        return len(self.objects) - 1

    def reserve(self) -> int:
        self.objects.append(b"")
        return len(self.objects) - 1

    def put(self, number: int, body: bytes) -> None:
        self.objects[number] = body

    @staticmethod
    def stream(dictionary: str, payload: bytes, compress: bool = True) -> bytes:
        if compress:
            payload = zlib.compress(payload, 9)
            dictionary = dictionary.rstrip() + " /Filter /FlateDecode"
        return (f"<< {dictionary} /Length {len(payload)} >>\nstream\n".encode()
                + payload + b"\nendstream")

    def build(self) -> bytes:
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, body in enumerate(self.objects[1:], 1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
        start = len(out)
        out += f"xref\n0 {len(self.objects)}\n".encode()
        out += b"0000000000 65535 f \n"
        for offset in offsets[1:]:
            out += f"{offset:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(self.objects)} /Root 1 0 R >>\n"
                f"startxref\n{start}\n%%EOF\n").encode()
        return bytes(out)


def export(notes, path, cols: int = 92, theme: str = "light",
           page: str = "letter", title: str = "") -> dict:
    """Write the notes to *path* as a PDF. Returns what happened."""
    book = Book(notes, cols=cols, theme=theme, page=page)
    contents = [book._content(sheet, number)
                for number, sheet in enumerate(book.sheets, 1)]

    writer = Writer()
    catalogue = writer.reserve()            # object 1, the root
    pages = writer.reserve()

    fonts = {}
    for style, face in book.faces.items():
        if style not in getattr(book, "_used", {}):
            continue
        fonts[style] = _embed(writer, face, book._used[style])

    resources = "/Font << " + " ".join(
        f"/{style.replace(' ', '')} {number} 0 R"
        for style, number in fonts.items()) + " >>"

    kids = []
    for body in contents:
        stream = writer.add(Writer.stream("", body))
        kids.append(writer.add(
            f"<< /Type /Page /Parent {pages} 0 R "
            f"/MediaBox [0 0 {book.width:.2f} {book.height:.2f}] "
            f"/Resources << {resources} >> /Contents {stream} 0 R >>".encode()))

    writer.put(pages, (f"<< /Type /Pages /Count {len(kids)} /Kids ["
                       + " ".join(f"{k} 0 R" for k in kids) + "] >>").encode())
    info = writer.add(("<< /Producer (inkwell) /Title ("
                       + _escape(title or Path(path).stem) + ") >>").encode())
    writer.put(catalogue,
               f"<< /Type /Catalog /Pages {pages} 0 R >>".encode())

    Path(path).write_bytes(writer.build())
    return {"path": str(path), "pages": len(kids), "notes": len(book.notes),
            "columns": book.cols, "size": Path(path).stat().st_size,
            "undrawable": "".join(sorted(book.undrawable))}


def _placed(pieces) -> list:
    """(what came before, text, face) for each piece of a split run."""
    out = []
    before = ""
    for text, face in pieces:
        out.append((before, text, face))
        before += text
    return out


def _block_art(words: str, size: str) -> list:
    """The rows of block characters a big-font line is drawn with."""
    drawable = T.prepare(size, words)
    canvas = urwid.BigText(drawable, T.font(size)).render(())
    return [row.decode("utf-8").rstrip() for row in canvas.text]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _embed(writer: Writer, face: Face, glyphs) -> int:
    """A Type0 font: the whole face, addressed by glyph id."""
    file_object = writer.add(Writer.stream(
        f"/Length1 {len(face.standalone())}", face.standalone()))
    descriptor = writer.add((
        f"<< /Type /FontDescriptor /FontName /{face.name} "
        f"/Flags {face.flags} /FontBBox [{' '.join(str(v) for v in face.bbox)}] "
        f"/ItalicAngle {face.italic_angle:.0f} /Ascent {face.bbox[3]} "
        f"/Descent {face.bbox[1]} /CapHeight {face.bbox[3]} /StemV 80 "
        f"/FontFile2 {file_object} 0 R >>").encode())
    widths = " ".join(f"{glyph} [{face.width(glyph)}]"
                      for glyph in sorted(glyphs) if glyph)
    descendant = writer.add((
        f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{face.name} "
        f"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        f"/Supplement 0 >> /FontDescriptor {descriptor} 0 R "
        f"/DW {face.width(0) or 600} /W [{widths}] "
        f"/CIDToGIDMap /Identity >>").encode())
    return writer.add((
        f"<< /Type /Font /Subtype /Type0 /BaseFont /{face.name} "
        f"/Encoding /Identity-H /DescendantFonts [{descendant} 0 R] >>").encode())
