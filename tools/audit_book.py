#!/usr/bin/env python3
"""Audit a converted book: render every note, and report what came out wrong.

    python3 tools/audit_book.py                       # ~/Documents/Inkwell
    python3 tools/audit_book.py /tmp/auditbook --widths 60,92,120
    python3 tools/audit_book.py /tmp/auditbook --kind latex --examples 8

Every note of every chapter is rendered through the real widget stack at
each width, and the resulting rows are read back -- text *and* display
attributes -- by six detectors:

  font    a character the font has no glyph for, or U+FFFD
  latex   a ``\\command`` that survived into the page
  script  a raw ``^`` or ``_`` left over from math
  wide    a row whose display width is past the right margin
  blank   three or more blank rows in a row
  sparse  a block of page that is mostly whitespace
  delim   a bracket opened in math and never closed

Nothing is written anywhere: the notes folder is read and left alone.

The detectors are deliberately narrow, because a detector that cries wolf
is worse than none. The exclusions, and why each one is not a defect:

* Terminal bold and italic are faked with mathematical look-alike code
  points, and Menlo has no glyph for any of them -- so the raw code point
  is the wrong thing to test. ``pdf.LOOKALIKE`` says what each look-alike
  really means and ``pdf.py`` draws it in the real Bold or Italic face, so
  every character is checked against the face it will actually be drawn
  in. Without this, every bold heading in the book reports as a defect.
* A block-font title is built out of sextants, which no embedded face
  has; ``pdf.Book`` already falls back to type for those. Reported as
  ``font.art``, apart from the text.
* ``pdf.INSTEAD`` already names the subscript letters no face can draw and
  swaps them on paper. Reported as ``font.substituted``, apart from the rest.
* URLs, file names and verbatim code rows legitimately hold ``_``, and
  inline code names are set in mono look-alikes (``𝚚_𝚛𝚊𝚗𝚍``): all excluded
  from the script-marker check.
* Prose wraps mid-parenthesis all the time, so the delimiter check runs
  only over math, and only over a whole run of math rows at once -- an
  equation broken across two rows still has to balance, but only as a
  block.
"""

from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import re
import struct
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urwid                               # noqa: E402

urwid.set_encoding("utf8")

from urwid.str_util import calc_width      # noqa: E402

from inkwell import pdf                    # noqa: E402
from inkwell import store                  # noqa: E402
from inkwell.document import Document      # noqa: E402
from inkwell.sfnt import Face              # noqa: E402
from inkwell.widgets import VIEW, NoteWidget   # noqa: E402

KINDS = ("font.glyph", "font.replacement", "font.substituted", "font.art",
         "latex", "script", "wide", "blank", "sparse", "delim")

# Characters a terminal draws a block-font title with: Block Elements and
# the sextants of Symbols for Legacy Computing.
ART_RANGES = ((0x2580, 0x259F), (0x1FB00, 0x1FBFF))

REPLACEMENT = "�"

# Undoing the terminal's fake styling: a look-alike is drawn as this letter
# in this face.
_FACE_OF = {"bold": "bold", "italic": "italic",
            "mono": "regular", "smallcaps": "regular", None: "regular"}


class Row(NamedTuple):
    """One rendered row: its text, and the attributes it was drawn with."""

    text: str
    attrs: frozenset = frozenset()


@dataclass(frozen=True)
class Finding:
    kind: str                  # one of KINDS
    key: str                   # what to group it by in the histogram
    text: str = ""             # the offending row
    row: int = 0               # its index within the note
    where: str = ""            # chapter / note / width, filled in by audit()


# --- font coverage ----------------------------------------------------------
def intended(character: str) -> tuple:
    """(the letter really drawn, the face it is drawn in).

    Bold and italic on a terminal are look-alike code points; on paper
    ``pdf.py`` decodes them back and sets them in a real face. Checking the
    look-alike itself would report every heading in the book.
    """
    plain, faked = pdf.LOOKALIKE.get(character, (character, None))
    if faked == "smallcaps":
        plain = plain.upper()
    return plain, _FACE_OF.get(faked, "regular")


def is_block_art(text: str) -> bool:
    """A row that is nothing but block-drawing glyphs and space."""
    seen = False
    for ch in text:
        if ch == " ":
            continue
        if not any(lo <= ord(ch) <= hi for lo, hi in ART_RANGES):
            return False
        seen = True
    return seen


class Glyphs:
    """Which characters the faces on this machine can actually draw."""

    def __init__(self, faces: dict) -> None:
        self.faces = faces
        self._cache: dict = {}

    @classmethod
    def system(cls, font: Optional[str] = None,
               index: int = 0) -> Optional["Glyphs"]:
        """The faces the PDF export would use, or None if there are none."""
        try:
            if font:
                names = ("regular", "bold", "italic", "bold italic")
                found = {name: Face(font, index + i)
                         for i, name in enumerate(names)}
            else:
                found = {name: Face(path, at)
                         for name, (path, at) in pdf.fonts().items()}
        except (pdf.NoFont, OSError, ValueError, struct.error):
            return None
        return cls(found)

    def has(self, character: str, face: str = "regular") -> bool:
        key = (character, face)
        if key not in self._cache:
            drawer = self.faces.get(face) or self.faces.get("regular")
            self._cache[key] = bool(drawer and drawer.has(character))
        return self._cache[key]



def _named(character: str) -> str:
    try:
        name = unicodedata.name(character)
    except ValueError:
        name = "<unnamed>"
    return "U+%04X %s %r" % (ord(character), name, character)


def font_findings(rows: Sequence[Row], glyphs) -> list:
    """Characters the font cannot draw, one finding per character."""
    if glyphs is None:
        return []
    found = []
    for i, item in enumerate(rows):
        art = is_block_art(item.text)
        for ch in item.text:
            if ch.isspace():
                continue
            if ch == REPLACEMENT:
                found.append(Finding("font.replacement", _named(ch),
                                     item.text, i))
                continue
            plain, face = intended(ch)
            if glyphs.has(plain, face):
                continue
            kind = ("font.art" if art else
                    "font.substituted" if ch in pdf.INSTEAD else "font.glyph")
            found.append(Finding(kind, _named(ch), item.text, i))
    return found


# --- LaTeX leaks ------------------------------------------------------------
COMMAND = re.compile(r"\\(?:[A-Za-z]+|\\)")


def latex_findings(rows: Sequence[Row]) -> list:
    """A ``\\command`` that survived. Verbatim rows quote LaTeX on purpose."""
    found = []
    for i, item in enumerate(rows):
        if "code" in item.attrs:
            continue
        for match in COMMAND.finditer(item.text):
            found.append(Finding("latex", match.group(), item.text, i))
    return found


# --- raw script markers -----------------------------------------------------
# Things that hold an underscore honestly, blanked before the check.
INNOCENT = re.compile(
    r"(?:https?|ftp)://\S+"                     # a full URL
    r"|\bwww\.\S+"                              # ...or one without a scheme
    r"|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,24}/\S*"  # youtu.be/_lHSaw
    r"|\S*\.(?:png|pdf|py|tex|json|html?|md|txt|csv|bib|c|cpp|h|m|sh)\b"
)
MONO = {ch for ch, (_plain, kind) in pdf.LOOKALIKE.items() if kind == "mono"}
MARKERS = "^_"


def script_findings(rows: Sequence[Row]) -> list:
    """A ``^`` or ``_`` left on the page by math that did not typeset."""
    found = []
    for i, item in enumerate(rows):
        if "code" in item.attrs:
            continue
        text = INNOCENT.sub(lambda m: " " * len(m.group()), item.text)
        for at, ch in enumerate(text):
            if ch not in MARKERS:
                continue
            before = text[at - 1] if at else ""
            after = text[at + 1] if at + 1 < len(text) else ""
            if before in MONO or after in MONO:
                continue            # an inline code name, e.g. 𝚚_𝚛𝚊𝚗𝚍
            found.append(Finding("script", ch, item.text, i))
    return found


# --- layout -----------------------------------------------------------------
def width_of(text: str) -> int:
    """Columns the row really takes up -- not len(), which miscounts both
    combining accents (too many) and wide glyphs (too few)."""
    return calc_width(text, 0, len(text))


def wide_findings(rows: Sequence[Row], width: int) -> list:
    return [Finding("wide", "%d cols" % width_of(item.text), item.text, i)
            for i, item in enumerate(rows) if width_of(item.text) > width]


def blank_findings(rows: Sequence[Row], limit: int = 3) -> list:
    """Runs of *limit* or more blank rows, ignoring the run at either end."""
    found, run, start = [], 0, 0
    body = list(rows)
    while body and not body[-1].text.strip():
        body.pop()
    lead = 0
    while lead < len(body) and not body[lead].text.strip():
        lead += 1
    for i in range(lead, len(body)):
        if body[i].text.strip():
            if run >= limit:
                found.append(Finding("blank", "%d rows" % run, "", start))
            run = 0
        else:
            if not run:
                start = i
            run += 1
    if run >= limit:
        found.append(Finding("blank", "%d rows" % run, "", start))
    return found


def core(rows: Sequence[Row]) -> list:
    """The rows without the blank padding above and below the block."""
    body = list(rows)
    while body and not body[0].text.strip():
        body.pop(0)
    while body and not body[-1].text.strip():
        body.pop()
    return body


def content_ratio(rows: Sequence[Row]) -> float:
    """How much of the block, padding aside, actually has ink on it."""
    body = core(rows)
    if not body:
        return 0.0
    return sum(1 for r in body if r.text.strip()) / len(body)


def sparse_findings(rows: Sequence[Row], floor: float = 0.6,
                    minimum: int = 8) -> list:
    """A block that is mostly whitespace.

    Short blocks are exempt: a two-line heading is half rule and half the
    gap under it, and that is the design, not a fault.
    """
    body = core(rows)
    if len(body) < minimum:
        return []
    ratio = content_ratio(body)
    if ratio >= floor:
        return []
    return [Finding("sparse", "%.2f" % ratio,
                    next((r.text for r in body if r.text.strip()), ""), 0)]


# --- delimiters -------------------------------------------------------------
CLOSES = {")": "(", "]": "[", "}": "{"}


def _unbalanced(text: str) -> str:
    """What is wrong with the brackets in *text*, or "" if nothing is."""
    stack = []
    for ch in text:
        if ch in "([{":
            stack.append(ch)
        elif ch in CLOSES:
            if stack and stack[-1] == CLOSES[ch]:
                stack.pop()
            else:
                return "unopened " + ch
    if stack:
        return "unclosed " + "".join(sorted(set(stack)))
    return ""


def delimiter_findings(rows: Sequence[Row], attr: str = "math") -> list:
    """Math whose brackets do not close.

    Checked a block at a time -- consecutive math rows are one equation,
    and an equation broken over two rows still balances across the pair.
    Prose is not checked at all: it wraps mid-parenthesis constantly.
    """
    found, i = [], 0
    rows = list(rows)
    while i < len(rows):
        if attr not in rows[i].attrs:
            i += 1
            continue
        j = i
        while j < len(rows) and attr in rows[j].attrs:
            j += 1
        blob = " ".join(r.text for r in rows[i:j])
        why = _unbalanced(blob)
        if why:
            found.append(Finding("delim", why, blob.strip()[:120], i))
        i = j
    return found


# --- putting them together --------------------------------------------------
def note_findings(rows: Sequence[Row], width: int, glyphs) -> list:
    return (font_findings(rows, glyphs) + latex_findings(rows)
            + script_findings(rows) + wide_findings(rows, width)
            + blank_findings(rows) + sparse_findings(rows)
            + delimiter_findings(rows))


# --- rendering --------------------------------------------------------------
def rows_of(widget, width: int) -> list:
    """Render one note widget and read the rows back with their attributes."""
    out = []
    for line in widget.render((width,), False).content():
        text = "".join(run.decode("utf-8", "replace") for _a, _cs, run in line)
        attrs = frozenset(a for a, _cs, _run in line if a)
        out.append(Row(text.rstrip(), attrs))
    return out


def render_notes(notes, width: int, height: int = 200) -> list:
    """Render notes at *width*; one list of Rows per note.

    *notes* are store.Note objects, or (text, fmt) pairs.
    """
    made = [n if isinstance(n, store.Note) else store.Note(n[0], fmt=n[1])
            for n in notes]
    doc = Document()
    doc.rebuild(made)
    VIEW.cols, VIEW.rows = width, height
    return [rows_of(NoteWidget(note, doc), width) for note in made]


# --- the whole book ---------------------------------------------------------
@dataclass
class Report:
    findings: list = field(default_factory=list)
    notes: int = 0
    rows: int = 0
    chapters: int = 0
    ratios: dict = field(default_factory=dict)

    @property
    def histogram(self) -> Counter:
        return Counter(f.kind for f in self.findings)


def find_chapters(where: Optional[str] = None, pattern: str = "iar-*.json") -> list:
    """Converted chapters to audit, in reading order. Read-only."""
    if where and os.path.isfile(where):
        return [where]
    folders = [where] if where else [
        "/tmp/auditbook",
        os.environ.get("INKWELL_DIR", ""),
        os.path.expanduser("~/Documents/Inkwell"),
    ]
    for folder in folders:
        if folder and os.path.isdir(folder):
            hits = sorted(_glob.glob(os.path.join(folder, pattern)))
            if hits:
                return hits
    return []


def audit(paths: Sequence[str], widths: Sequence[int] = (60, 92, 120),
          glyphs=None) -> Report:
    report = Report()
    for path in paths:
        report.chapters += 1
        notes = store.load(path)
        chapter = os.path.basename(path)
        for width in widths:
            pages = render_notes(notes, width)
            whole = []
            for n, rows in enumerate(pages):
                whole.extend(rows)
                if width == widths[0]:
                    report.notes += 1
                report.rows += len(rows)
                where = "%s note %d @%d" % (chapter, n, width)
                for hit in note_findings(rows, width, glyphs):
                    report.findings.append(
                        Finding(hit.kind, hit.key, hit.text, hit.row, where))
            # The reader sees the chapter, not one note: check the run of
            # blank rows and the ink-per-row over the whole thing.
            where = "%s @%d" % (chapter, width)
            for hit in blank_findings(whole) + sparse_findings(whole):
                report.findings.append(
                    Finding(hit.kind, hit.key, hit.text, hit.row, where))
            report.ratios[where] = round(content_ratio(whole), 3)
    return report


# --- the report -------------------------------------------------------------
def render_report(report: Report, examples: int = 3,
                  only: Optional[str] = None) -> str:
    out = []
    out.append("%d chapters, %d notes, %d rendered rows"
               % (report.chapters, report.notes, report.rows))
    hist = report.histogram
    out.append("")
    out.append("defect                 count")
    out.append("-" * 40)
    widest = max(hist.values()) if hist else 1
    for kind in KINDS:
        n = hist.get(kind, 0)
        bar = "#" * int(28 * n / widest) if n else ""
        out.append("%-18s %7d %s" % (kind, n, bar))
    out.append("%-18s %7d" % ("TOTAL", sum(hist.values())))

    by_kind = defaultdict(lambda: defaultdict(list))
    for f in report.findings:
        by_kind[f.kind][f.key].append(f)
    for kind in KINDS:
        if only and kind != only and not kind.startswith(only):
            continue
        groups = by_kind.get(kind)
        if not groups:
            continue
        out.append("")
        out.append("--- %s (%d) ---" % (kind, hist[kind]))
        ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        for key, hits in ranked[:examples * 4]:
            out.append("  %-46s x%d" % (key[:46], len(hits)))
            for hit in hits[:examples]:
                out.append("      %s" % hit.where)
                if hit.text:
                    out.append("      | %s" % hit.text.strip()[:96])
    thin = sorted((v, k) for k, v in report.ratios.items() if v < 0.6)
    out.append("")
    out.append("thinnest chapters by content ratio:")
    for value, key in sorted((v, k) for k, v in report.ratios.items())[:5]:
        out.append("  %.3f  %s%s" % (value, key, "   <-- under 0.6"
                                     if value < 0.6 else ""))
    if thin:
        out.append("  %d chapter/width pairs are under 0.6" % len(thin))
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("where", nargs="?", default=None,
                        help="a notebook, or a folder of them "
                             "(default: /tmp/auditbook, then $INKWELL_DIR, "
                             "then ~/Documents/Inkwell)")
    parser.add_argument("--widths", default="60,92,120",
                        help="terminal widths to render at")
    parser.add_argument("--examples", type=int, default=3,
                        help="examples to print per defect key")
    parser.add_argument("--kind", default=None,
                        help="only detail this defect class")
    parser.add_argument("--font", default=None,
                        help="font file to test coverage against")
    parser.add_argument("--json", dest="as_json", default=None,
                        help="also write the findings to this file")
    parser.add_argument("--fail-on", default="",
                        help="comma-separated kinds that make this exit 1")
    args = parser.parse_args(argv)

    paths = find_chapters(args.where)
    if not paths:
        print("no notebooks found; run tools/tex2ink.py first", file=sys.stderr)
        return 2
    widths = tuple(int(w) for w in args.widths.split(","))
    glyphs = Glyphs.system(args.font)
    if glyphs is None:
        print("note: no TrueType font found, font coverage not checked",
              file=sys.stderr)
    report = audit(paths, widths, glyphs)
    print(render_report(report, args.examples, args.kind))

    if args.as_json:
        with open(args.as_json, "w") as handle:
            json.dump({"histogram": dict(report.histogram),
                       "ratios": report.ratios,
                       "findings": [{"kind": f.kind, "key": f.key,
                                     "where": f.where, "text": f.text}
                                    for f in report.findings]},
                      handle, indent=1)
    bad = {k.strip() for k in args.fail_on.split(",") if k.strip()}
    return 1 if bad & set(report.histogram) else 0


if __name__ == "__main__":
    sys.exit(main())
