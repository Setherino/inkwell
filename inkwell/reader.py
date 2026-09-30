"""Books in inkwell: chapters as notebooks, with a shelf and a contents.

    python3 -m inkwell.reader                  # the shelf, then read
    python3 -m inkwell.reader iar              # straight into one book
    python3 -m inkwell.reader iar 3            # ...at chapter 3
    python3 -m inkwell.reader --list           # every book, and its chapters
    python3 -m inkwell.reader --find "kalman"  # search the whole shelf

**A book is a naming convention, not a special file.** Any two or more
notebooks in the notes folder sharing a ``<prefix>-<slot>-<title>.json``
name are read as one book in that order -- ``iar-01-introduction.json``,
``iar-02-kinematics.json``, and so on -- which is what tools/tex2ink.py
writes out of a LaTeX source tree. A folder can hold as many books as you
convert into it, and they show up on the shelf on their own. An optional
``<prefix>.book.json`` beside them says what the book is called; without
one the prefix is used (``iar`` -> ``IAR``).

So there are two levels above a page of notes, and esc walks back out
through both (see the tree in app.py):

    shelf     which book        only shown when the folder holds several
    contents  chapters, sections and the search, for the book you are in

The contents lists chapters in reading order; Enter opens a chapter's
sections, Enter on a section opens the notebook scrolled to it. Typing
searches that whole book as you go: matching sections first, then the
passages that say the word, each shown in context under its chapter, and
Enter on a passage opens the notebook at that very note. ``f2`` brings the
contents back from inside a chapter, ``ctrl f`` opens it ready to search,
``f3`` goes straight to the shelf, ``f10`` quits. Everything else is
inkwell: a book is editable, so notes can be written into the margins.

When the reader is run from a packed archive (tools/build_reader.py) the
notebooks travel inside it and are copied into the notes folder the first
time -- never over a copy that is already there, so annotations survive.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import urwid

from . import shaping as S
from . import store
from . import theme as themes
from .app import PAGE, ROOT, SHELF, Inkwell
from .widgets import VIEW

BOOK_FOLDER = "book"        # inside the package, only ever in the built archive

# A book is a set of notebooks in the notes folder whose names share a
# prefix: ``<prefix>-<slot>-<title>.json``. Nothing in this module knows
# which book -- they are discovered, and a folder can hold several.
MANIFEST = ".book.json"     # <prefix>.book.json: what the book is called
MIN_CHAPTERS = 2            # ...below which a matching name is just a notebook

_SLOT = re.compile(r"^[a-z0-9]+-(?P<slot>[0-9]+|[a-z])-")
_NAMED = re.compile(r"^(?P<prefix>[a-z][a-z0-9]*)-(?P<slot>[0-9]+|[a-z])-")

# Searching. One or two letters is a filter on the contents, not a search of
# the prose -- "a" would otherwise answer with the whole book. The caps keep
# the menu a list you can read rather than a haystack; the shell (--find)
# asks for no cap at all.
MIN_QUERY = 3
MAX_HITS = 200
PER_CHAPTER = 20
SNIPPET = 72
LINE_WIDTH = 100            # --find: a passage a terminal can show on one line


@dataclass
class Section:
    index: int          # which note the heading is
    level: int          # 1 = "##", 2 = "###"
    title: str


@dataclass
class Chapter:
    path: Path
    slot: str
    title: str
    sections: list
    count: int
    # Every note, already read: how it was classified and its text with the
    # markup stripped. Kept so a search is a scan of memory, not of the disk.
    shapes: list = field(default_factory=list)

    def section_at(self, index: int) -> "Section | None":
        """The section a note falls under -- the last heading above it."""
        found = None
        for section in self.sections:
            if section.index > index:
                break
            found = section
        return found


@dataclass
class Book:
    """One book on the shelf: a prefix, a name, and its chapters in order."""
    prefix: str
    title: str
    chapters: list
    source: str = ""            # where it was converted from, if it says

    @property
    def notes(self) -> int:
        return sum(chapter.count for chapter in self.chapters)

    @property
    def sections(self) -> int:
        return sum(len(chapter.sections) for chapter in self.chapters)


@dataclass
class Hit:
    """A note whose prose contains what was searched for."""
    chapter: Chapter
    index: int
    text: str
    start: int
    end: int
    section: Section | None = None


@dataclass
class Row:
    text: str
    chapter: Chapter
    section: Section | None = None
    hit: Hit | None = None
    parts: tuple = ()           # (attr, text) pieces, so a match can be marked

    @property
    def target(self) -> int:
        """The note this row opens."""
        if self.hit is not None:
            return self.hit.index
        return self.section.index if self.section else 0


def _order(name: str):
    """Reading order from a file name: numbered chapters, then lettered."""
    m = _SLOT.match(name)
    slot = m.group("slot") if m else name
    return (0, int(slot)) if slot.isdigit() else (1, slot)


# --- the shelf --------------------------------------------------------------
def name_of(prefix: str) -> str:
    """What to call a book with no manifest.

    A short prefix is nearly always an acronym someone chose on purpose
    (``iar`` -> ``IAR``); a longer one reads better as words.
    """
    if len(prefix) <= 4 and prefix.isalpha():
        return prefix.upper()
    return prefix.replace("-", " ").replace("_", " ").title()


def manifest_path(directory, prefix: str) -> Path:
    return Path(directory or store.DEFAULT_DIR) / f"{prefix}{MANIFEST}"


def read_manifest(directory, prefix: str) -> dict:
    """What a book says about itself, or {} if it does not say."""
    try:
        data = json.loads(manifest_path(directory, prefix).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(directory, prefix: str, title: str, source: str = "") -> Path:
    """Record what a converted book is called, so the shelf can name it."""
    path = manifest_path(directory, prefix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"prefix": prefix, "title": title,
                                "source": source}, indent=1))
    return path


def prefixes(directory=None) -> list:
    """Every prefix in the folder that looks like a book, alphabetically.

    Two notebooks sharing a ``<prefix>-<slot>-<title>`` name make a book; a
    lone one is just a notebook that happens to be named that way. A
    manifest says "this is a book" outright, however few chapters it has.
    """
    directory = Path(directory or store.DEFAULT_DIR)
    counts: dict = {}
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    for path in entries:
        if not path.is_file() or path.suffix != store.SUFFIX:
            continue
        m = _NAMED.match(path.name)
        if m:
            counts[m.group("prefix")] = counts.get(m.group("prefix"), 0) + 1
    for path in entries:
        if path.name.endswith(MANIFEST):
            counts.setdefault(path.name[:-len(MANIFEST)], 0)
    return sorted(p for p, n in counts.items()
                  if n >= MIN_CHAPTERS or read_manifest(directory, p))


def books(directory=None) -> list:
    """Every book in the notes folder, by title. The shelf.

    Reading a book costs a pass over its notes, so a folder of several is
    read once here and the chapters are kept -- searching is then a scan of
    memory rather than of the disk.
    """
    directory = Path(directory or store.DEFAULT_DIR)
    found = []
    for prefix in prefixes(directory):
        chapters = contents(directory, prefix)
        if not chapters:
            continue
        said = read_manifest(directory, prefix)
        found.append(Book(prefix,
                          str(said.get("title") or "").strip() or name_of(prefix),
                          chapters, str(said.get("source") or "")))
    found.sort(key=lambda b: b.title.lower())
    return found


def pick_book(shelf, wanted):
    """The book someone named: by prefix, or by part of its title."""
    if not shelf:
        return None
    if not wanted:
        return shelf[0]
    w = str(wanted).strip().lower()
    for book in shelf:
        if w == book.prefix.lower():
            return book
    for book in shelf:
        if w in book.title.lower():
            return book
    return None


# --- the book on disk -------------------------------------------------------
def contents(directory, prefix: str) -> list:
    """Every chapter of one book, in reading order, with its sections."""
    directory = Path(directory or store.DEFAULT_DIR)
    found = []
    for path in directory.glob(f"{prefix}-*{store.SUFFIX}"):
        notes = store.load(path)
        title = ""
        sections = []
        shapes = []
        for i, note in enumerate(notes):
            shape = S.classify(note.text)
            shapes.append(shape)
            if shape.kind == S.TITLE and not title:
                title = shape.text
            elif shape.kind == S.SECTION:
                sections.append(Section(i, 1, shape.text))
            elif shape.kind == S.HEAD and note.text.lstrip().startswith("###"):
                sections.append(Section(i, 2, shape.text))
        m = _SLOT.match(path.name)
        found.append(Chapter(path, m.group("slot") if m else path.stem,
                             title or store.title_of(path), sections, len(notes),
                             shapes))
    found.sort(key=lambda c: _order(c.path.name))
    return found


# --- searching ----------------------------------------------------------------
def passages(chapter: Chapter, query: str, limit=None) -> list:
    """The notes in one chapter whose prose says *query* (already lowered).

    Headings are left out: they are already rows of their own in the
    contents, and a chapter called "Kinematics" should not answer a search
    for kinematics with its own title fifty times.
    """
    if limit is not None and limit <= 0:
        return []
    covered = {s.index for s in chapter.sections}
    found = []
    for i, shape in enumerate(chapter.shapes):
        if i in covered or shape.kind == S.TITLE:
            continue
        at = shape.text.lower().find(query)
        if at < 0:
            continue
        found.append(Hit(chapter, i, shape.text, at, at + len(query),
                         chapter.section_at(i)))
        if limit is not None and len(found) >= limit:
            break
    return found


def search(chapters, query: str, limit=None, least: int = MIN_QUERY) -> list:
    """Every passage in the book containing *query*, in reading order."""
    q = query.strip().lower()
    if len(q) < least:
        return []
    out = []
    for ch in chapters:
        out += passages(ch, q, None if limit is None else limit - len(out))
        if limit is not None and len(out) >= limit:
            break
    return out if limit is None else out[:limit]


def snippet(hit: Hit, width: int = SNIPPET) -> list:
    """A hit as (attribute, text) pieces: its line, trimmed around the word.

    Long paragraphs are cut back to a window either side of the match and
    marked with an ellipsis, so what the menu shows is the sentence the
    word is in rather than the first line of the paragraph it hides in.
    """
    word = hit.text[hit.start:hit.end]
    text = " ".join(hit.text.split())            # one line, however it was typed
    at = text.lower().find(word.lower())
    if at < 0:                                   # only if the note changed under us
        return [(None, text[:width])]
    half = max(0, (width - len(word)) // 2)
    start, end = max(0, at - half), min(len(text), at + len(word) + half)
    if start > 0:                                # do not begin mid-word
        space = text.find(" ", start, at)
        start = space + 1 if space != -1 else start
    if end < len(text):
        space = text.rfind(" ", at + len(word), end)
        end = space if space != -1 else end
    before = ("…" if start > 0 else "") + text[start:at]
    after = text[at + len(word):end] + ("…" if end < len(text) else "")
    parts = [(None, before)] if before else []
    parts.append(("match", text[at:at + len(word)]))
    if after:
        parts.append((None, after))
    return parts


def place(section) -> str:
    """A section's number, when it has one: "2.1  Forward Kinematics" -> "2.1"."""
    head = section.title.split()[0] if section and section.title.split() else ""
    return head if any(c.isdigit() for c in head) else ""


def _passage_row(hit: Hit) -> Row:
    """A hit as a line of the menu: where it is, then the sentence itself."""
    label = place(hit.section)
    lead = "    " + (label + " · " if label else "")
    parts = [(None, lead)] + snippet(hit)
    return Row("".join(text for _attr, text in parts),
               hit.chapter, hit.section, hit, tuple(parts))


def rows(chapters, expanded, query: str = "") -> list:
    """What the menu shows: chapters, opened ones with their sections.

    With a query it is the whole book searched at once -- every chapter and
    section whose title contains it, and under them the passages that say
    it -- so a topic can be found without knowing which chapter it is in,
    or whether anyone thought to give it a heading.
    """
    q = query.strip().lower()
    out = []
    if not q:
        for ch in chapters:
            out.append(Row(ch.title, ch))
            if ch.path in expanded:
                out += [Row("  " * s.level + s.title, ch, s) for s in ch.sections]
        return out
    room = MAX_HITS
    for ch in chapters:
        heads = [s for s in ch.sections if q in s.title.lower()]
        found = (passages(ch, q, min(PER_CHAPTER, room))
                 if len(q) >= MIN_QUERY else [])
        if not (heads or found or q in ch.title.lower()):
            continue
        out.append(Row(ch.title, ch))
        out += [Row("  " * s.level + s.title, ch, s) for s in heads]
        out += [_passage_row(h) for h in found]
        room -= len(found)
    return out


# --- first run ----------------------------------------------------------------
def bundled(package: str = "inkwell", folder: str = BOOK_FOLDER) -> list:
    """The notebooks packed inside this program, as (name, bytes), in order."""
    try:
        from importlib import resources
        root = resources.files(package) / folder
        if not root.is_dir():
            return []
        items = [(p.name, p.read_bytes()) for p in root.iterdir()
                 if p.name.endswith(store.SUFFIX)]
    except Exception:                       # noqa: BLE001 - a checkout has no book
        return []
    return sorted(items, key=lambda item: _order(item[0]))


def install(bundle, directory=None) -> list:
    """Copy bundled notebooks into the folder. Never over one already there."""
    directory = store.ensure(directory)
    added = []
    now = time.time()
    for i, (name, data) in enumerate(bundle):
        path = directory / name
        if path.exists():
            continue
        path.write_bytes(data)
        # The open dialog sorts by mtime: reading order is newest first.
        os.utime(path, (now - i * 60, now - i * 60))
        added.append(path)
    return added


# --- the menu -----------------------------------------------------------------
class _Line(urwid.WidgetWrap):
    _selectable = True

    def __init__(self, row: Row) -> None:
        self.row = row
        markup = ([(None, " ")] + list(row.parts) if row.parts
                  else [(None, " " + row.text)])
        super().__init__(urwid.Text(markup, wrap="clip"))

    def selectable(self) -> bool:
        return True

    def keypress(self, size, key):
        return key


# A menu line's own attributes: the searched-for word is marked in the row,
# and gives that up when the row is the focused one -- it is highlighted
# whole, and a second highlight inside it would only be harder to read.
LINE = {None: "dialog_item", "match": "dialog_title"}
LINE_FOCUS = {None: "dialog_focus", "match": "dialog_focus"}


class _Spine(urwid.WidgetWrap):
    """One book on the shelf: its name, and how much of it there is."""

    _selectable = True

    def __init__(self, book: Book, current: bool = False) -> None:
        self.book = book
        title = ("▸ " if current else "  ") + book.title
        chapters = f"{len(book.chapters)} chapter{'' if len(book.chapters) == 1 else 's'}"
        super().__init__(urwid.Columns([
            ("weight", 3, urwid.Text(title, wrap="clip")),
            ("weight", 1, urwid.Text(chapters, align="right")),
            (10, urwid.Text(f"{book.notes} notes", align="right")),
        ], dividechars=1))

    def selectable(self) -> bool:
        return True

    def keypress(self, size, key):
        return key


class Shelf(urwid.WidgetWrap):
    """Which book. The level above a book's own contents.

    A folder can hold as many books as you convert into it, so this is the
    top of the reader's tree: Enter opens a book's contents, and esc from
    the contents comes back here. With only one book on it the reader never
    shows this -- there would be nothing to choose.
    """

    signals = ["chosen", "closed"]

    def __init__(self, books, current: str = "", title: str = "Shelf") -> None:
        self.books = list(books)
        self.current = current
        self.query = ""
        self.finder = urwid.Text("")
        self.walker = urwid.SimpleFocusListWalker([])
        self.listing = urwid.ListBox(self.walker)
        self.hint = urwid.Text("", wrap="clip")
        self._fill()
        frame = urwid.Frame(
            self.listing,
            header=urwid.Pile([urwid.AttrMap(self.finder, "dialog_title"),
                               urwid.AttrMap(urwid.Divider("─"), "rule")]),
            footer=urwid.Pile([urwid.AttrMap(urwid.Divider("─"), "rule"),
                               urwid.AttrMap(self.hint, "dialog")]))
        box = urwid.LineBox(urwid.Padding(frame, left=1, right=1), title=title)
        super().__init__(urwid.AttrMap(box, "dialog"))

    def shown(self) -> list:
        q = self.query.strip().lower()
        if not q:
            return self.books
        return [b for b in self.books
                if q in b.title.lower() or q in b.prefix.lower()]

    def _fill(self) -> None:
        self._rows = self.shown()
        self.walker[:] = [
            urwid.AttrMap(_Spine(book, book.prefix == self.current),
                          "dialog_item", "dialog_focus")
            for book in self._rows]
        if not self._rows:
            self.walker[:] = [urwid.AttrMap(
                urwid.Text("  no book matches"), "dialog")]
        else:
            at = next((i for i, b in enumerate(self._rows)
                       if b.prefix == self.current), 0)
            self.walker.set_focus(at)
        count = len(self.books)
        self.finder.set_text(
            [("dialog_title", "  find: "), ("dialog_title", self.query)]
            + ([("dialog", f"   {len(self._rows)} of {count}")] if self.query
               else [("dialog", f"{count} book{'' if count == 1 else 's'}")]))
        self.hint.set_text(" ↑↓ move · ⏎ open · esc back · f10 quit")

    def current_book(self):
        widget = self.listing.focus
        spine = widget.base_widget if widget else None
        return getattr(spine, "book", None)

    def keypress(self, size, key):
        if key == "esc":
            return key              # up a level -- the app closes the shelf
        if key == "f2":
            self._emit("closed")    # ...f2 is a toggle, not a rung
            return None
        if key == "enter":
            book = self.current_book()
            if book is not None:
                self._emit("chosen", book)
            return None
        if key == "backspace":
            self.query = self.query[:-1]
            self._fill()
            return None
        if len(key) == 1 and key.isprintable():
            self.query += key
            self._fill()
            return None
        return super().keypress(size, key)

    def mouse_event(self, size, event, button, col, row, focus):
        handled = super().mouse_event(size, event, button, col, row, focus)
        if urwid.util.is_mouse_press(event) and button == 1:
            book = self.current_book()
            if book is not None:
                self._emit("chosen", book)
                return True
        return handled


class Menu(urwid.WidgetWrap):
    """The table of contents, and the search. Arrows move, Enter opens."""

    signals = ["chosen", "closed"]

    def __init__(self, chapters, title: str = "Contents") -> None:
        self.chapters = list(chapters)
        self.expanded: set = set()
        self.query = ""
        self.finder = urwid.Text("")
        self.walker = urwid.SimpleFocusListWalker([])
        self.listing = urwid.ListBox(self.walker)
        self.hint = urwid.Text("", wrap="clip")
        self._fill()
        frame = urwid.Frame(
            self.listing,
            header=urwid.Pile([urwid.AttrMap(self.finder, "dialog_title"),
                               urwid.AttrMap(urwid.Divider("─"), "rule")]),
            footer=urwid.Pile([urwid.AttrMap(urwid.Divider("─"), "rule"),
                               urwid.AttrMap(self.hint, "dialog")]))
        box = urwid.LineBox(urwid.Padding(frame, left=1, right=1), title=title)
        super().__init__(urwid.AttrMap(box, "dialog"))

    # -- rows ------------------------------------------------------------------
    def _fill(self, keep: Row | None = None) -> None:
        self._rows = rows(self.chapters, self.expanded, self.query)
        self.walker[:] = [urwid.AttrMap(_Line(r), LINE, LINE_FOCUS)
                          for r in self._rows]
        if not self._rows:
            self.walker[:] = [urwid.AttrMap(
                urwid.Text("  nothing matches"), "dialog")]
        elif keep is not None:
            for i, r in enumerate(self._rows):
                if r.chapter is keep.chapter and r.section is keep.section:
                    self.walker.set_focus(i)
                    break
        elif self.query:
            # A section or a passage answers a search; the chapter above it is
            # only there to say where. Start on the first real answer.
            first = next((i for i, r in enumerate(self._rows)
                          if r.section or r.hit), 0)
            # Land on the first answer with the chapter it is in still on the
            # screen above it: a passage is no use without knowing its place.
            if first:
                self.listing.set_focus(first - 1)
            self.listing.set_focus(first, "above" if first else None)
        else:
            self.walker.set_focus(0)
        self.finder.set_text(self._found())
        self.hint.set_text(" ↑↓ move · ⏎ open · → ← unfold · esc back · f10 quit")

    def _found(self) -> list:
        """The search box: what was typed, and how much of the book says it."""
        if not self.query:
            return [("dialog_title", "  find: "),
                    ("dialog", "type to search the book")]
        heads = sum(1 for r in self._rows if r.section and not r.hit)
        seen = sum(1 for r in self._rows if r.hit)
        return [("dialog_title", "  find: "), ("dialog_title", self.query),
                ("dialog", f"   {heads} section{'' if heads == 1 else 's'}"
                           f" · {seen} passage{'' if seen == 1 else 's'}")]

    def current(self) -> Row | None:
        widget = self.listing.focus
        line = widget.base_widget if widget else None
        return getattr(line, "row", None)

    # -- keys ------------------------------------------------------------------
    def keypress(self, size, key):
        row = self.current()
        if key == "esc":
            return key              # up a level -- the app closes the menu
        if key == "f2":
            self._emit("closed")    # ...f2 is a toggle, not a rung
            return None
        if key == "enter":
            if row is None:
                return None
            if (row.section is None and not self.query
                    and row.chapter.path not in self.expanded):
                self.expanded.add(row.chapter.path)
                self._fill(keep=row)
                return None
            self._emit("chosen", row.chapter.path, row.target)
            return None
        if key in ("right", "left", " ") and row is not None and not self.query:
            path = row.chapter.path
            if key == "left" or (key == " " and path in self.expanded):
                self.expanded.discard(path)
                self._fill(keep=Row(row.chapter.title, row.chapter))
            else:
                self.expanded.add(path)
                self._fill(keep=row)
            return None
        if key == "backspace":
            self.query = self.query[:-1]
            self._fill()
            return None
        if len(key) == 1 and key.isprintable():
            self.query += key
            self._fill()
            return None
        return super().keypress(size, key)

    def mouse_event(self, size, event, button, col, row, focus):
        handled = super().mouse_event(size, event, button, col, row, focus)
        if urwid.util.is_mouse_press(event) and button == 1 and self.current():
            self.keypress(size, "enter")
            return True
        return handled


# --- the app ------------------------------------------------------------------
class Reader(Inkwell):
    """inkwell with a shelf of books where the folder dialog was.

    Two levels sit above a page of notes here rather than one:

        SHELF     which book        (only when the folder holds several)
        ROOT      its contents      chapters and sections, and the search

    esc walks back out through both, exactly as it does everywhere else.
    """

    def __init__(self, path, theme: str = "dark", prefix: str = "",
                 folder=None) -> None:
        super().__init__(path, use_llm=False, theme=theme)
        self.folder = Path(folder) if folder else (
            self.path.parent if self.path else store.DEFAULT_DIR)
        m = _NAMED.match(Path(path).name) if path else None
        self.prefix = prefix or (m.group("prefix") if m else "")
        self.menu: Menu | None = None
        self.shelf: Shelf | None = None

    # --- the two levels above the page ------------------------------------
    def books(self) -> list:
        return books(self.folder)

    def at_root(self) -> bool:
        """True on either of the reader's top two levels."""
        return self.menu is not None or self.shelf is not None

    def depth(self) -> int:
        if self.shelf is not None:
            return SHELF
        if self.menu is not None:
            return ROOT
        return super().depth()

    def open_library(self) -> None:         # ...what open_root reaches
        """Coming up from the composer lands on the book you are reading."""
        self.open_contents()

    def close_root(self) -> None:
        """One modal steps aside. The contents uncovers the shelf, if any."""
        if self.shelf is not None:
            return self.close_shelf()
        if self.menu is not None and len(self.books()) > 1:
            return self.open_shelf()        # ...the level the contents covers
        self.close_contents()

    def _command(self, key: str) -> bool | None:
        if key == "ctrl f":                 # where a reader looks for a search
            self.open_contents()
            return True
        if key == "f3" and self.at_root():
            self.open_shelf()               # straight to the shelf
            return True
        return super()._command(key)

    def _show(self, widget) -> None:
        if self.loop:
            self.loop.widget = urwid.Overlay(
                widget, self.frame,
                align="center", width=("relative", 80), min_width=44,
                valign="middle", height=("relative", 85), min_height=10)

    # --- the shelf --------------------------------------------------------
    def open_shelf(self) -> None:
        """Show the books. Remembers what it covers, like any other root."""
        if self.shelf is not None:
            return self.close_shelf()
        if not self.at_root():
            self._came_from = min(self.depth(), PAGE)
            self._close_boxes()
        self.menu = None                    # the contents is what it covers
        self.shelf = Shelf(self.books(), current=self.prefix)
        urwid.connect_signal(self.shelf, "chosen",
                             lambda _w, book: self.open_book(book))
        urwid.connect_signal(self.shelf, "closed", lambda _w: self.close_shelf())
        self._show(self.shelf)

    def close_shelf(self) -> None:
        self.shelf = None
        if self.loop:
            self.loop.widget = self.frame
        self._uncover()

    def open_book(self, book) -> None:
        """Pick a book off the shelf: straight into its contents."""
        self.shelf = None
        self.prefix = book.prefix
        self.open_contents(book.chapters, book.title)

    # --- one book's contents ----------------------------------------------
    def open_contents(self, chapters=None, title: str = "") -> None:
        if self.menu is not None:
            return self.close_contents()
        if self.shelf is not None and chapters is None:
            return                          # the shelf is above this; stay
        if not self.at_root():
            self._came_from = min(self.depth(), PAGE)
            self._close_boxes()
        if chapters is None:
            shelf = self.books()
            book = pick_book(shelf, self.prefix)
            if book is None:
                # Nothing on the shelf under this prefix. Offer the shelf
                # rather than an empty contents.
                if shelf:
                    return self.open_shelf()
                chapters, title = [], "Contents"
            else:
                self.prefix, chapters, title = book.prefix, book.chapters, book.title
        self.menu = Menu(chapters, title=title or "Contents")
        urwid.connect_signal(self.menu, "chosen",
                             lambda _w, path, index: self.go(path, index))
        urwid.connect_signal(self.menu, "closed", lambda _w: self.close_contents())
        self._show(self.menu)

    def close_contents(self) -> None:
        self.menu = None
        if self.loop:
            self.loop.widget = self.frame
        self._uncover()

    def go(self, path, index: int) -> None:
        """Open a chapter with a section at the top of the page."""
        if Path(path) != self.path:
            self.load_notebook(path)
        self.close_contents()
        self.jump_to(index)

    def _refresh(self) -> None:
        super()._refresh()
        text, _attrs = self.status.get_text()
        if "f2 open" in text:
            # The status line never wraps, so the search only earns its place
            # once there is room for it.
            said = "f2 contents · ^f find" if VIEW.cols >= 78 else "f2 contents"
            self.status.set_text([("status", text.replace("f2 open", said))])

    def run(self, show_contents: bool = True) -> None:
        """Open on the shelf when there is a choice to make, else the book."""
        self._make_loop()
        if show_contents:
            if len(self.books()) > 1:
                self.open_shelf()
            else:
                self.open_contents()
        self.loop.run()


def pick(chapters, wanted: str | None):
    """The chapter someone asked for: a number, a letter, or part of a title."""
    if not chapters:
        return None
    if wanted is None:
        return chapters[0]
    w = wanted.strip().lower()
    for ch in chapters:
        if w in (ch.slot, ch.slot.lstrip("0"), ch.slot.upper().lower()):
            return ch
    for ch in chapters:
        if w in ch.title.lower():
            return ch
    return None


def report(hits, wanted: str, named: bool = False) -> int:
    """Print what a search found, grouped the way the contents are printed."""
    if not hits:
        where = "the book" if named else "any book on the shelf"
        print(f"nothing in {where} says {wanted!r}", file=sys.stderr)
        return 1
    chapter = section = None
    for hit in hits:
        if hit.chapter is not chapter:
            chapter, section = hit.chapter, None
            print(chapter.title)
        if hit.section is not section:
            section = hit.section
            if section is not None:
                print("  " * section.level + section.title)
        print("    " + "".join(text for _attr, text in snippet(hit, LINE_WIDTH)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="inkwell-reader", description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("book", nargs="?", default=None,
                        help="a book, by prefix or part of its title "
                             "(omit for the shelf)")
    parser.add_argument("chapter", nargs="?", default=None,
                        help="a chapter number, letter, or part of its title")
    parser.add_argument("--list", action="store_true",
                        help="print the shelf, or one book's contents")
    parser.add_argument("--find", metavar="TEXT",
                        help="print every passage that says TEXT")
    parser.add_argument("--where", action="store_true",
                        help="print the folder the notebooks live in")
    parser.add_argument("--dir", type=Path, default=None,
                        help="notes folder (default: ~/Documents/Inkwell, "
                             "or $INKWELL_DIR)")
    parser.add_argument("--theme", default="auto", choices=("auto", "light", "dark"))
    parser.add_argument("--ascii", action="store_true", help="no unicode letterforms")
    parser.add_argument("--export", metavar="FILE.pdf", type=Path,
                        help="write the chapter to a PDF and stop")
    parser.add_argument("--width", type=int, default=92, metavar="COLUMNS")
    args = parser.parse_args(argv)

    VIEW.unicode_ok = not args.ascii
    folder = store.ensure(args.dir)
    install(bundled(), folder)
    if args.where:
        print(folder)
        return 0

    shelf = books(folder)
    if not shelf:
        print(f"no book found in {folder}.\nA book is two or more notebooks "
              f"named <prefix>-<n>-<title>.json; tools/tex2ink.py writes them "
              f"from LaTeX.", file=sys.stderr)
        return 1

    # One positional argument is a book when it names one, and otherwise a
    # chapter of the only book there is -- so "reader 3" keeps working on a
    # one-book shelf without anyone having to name it.
    wanted_book, wanted_chapter = args.book, args.chapter
    book = pick_book(shelf, wanted_book) if wanted_book else None
    if book is None and wanted_book and wanted_chapter is None and len(shelf) == 1:
        book, wanted_chapter = shelf[0], wanted_book
    if book is None and wanted_book:
        names = ", ".join(b.prefix for b in shelf)
        print(f"no book matches {wanted_book!r}; the shelf has: {names}",
              file=sys.stderr)
        return 1

    if args.list:
        for each in ([book] if book else shelf):
            print(f"{each.title}  ({each.prefix}, {len(each.chapters)} chapters,"
                  f" {each.notes} notes)")
            if book or len(shelf) == 1:
                for ch in each.chapters:
                    print("  " + ch.title)
                    for s in ch.sections:
                        print("  " + "  " * s.level + s.title)
        return 0

    if args.find:
        searched = (book.chapters if book
                    else [ch for each in shelf for ch in each.chapters])
        return report(search(searched, args.find, least=1), args.find,
                      named=book is not None)

    on = book or (shelf[0] if len(shelf) == 1 else None)
    chapter = pick(on.chapters, wanted_chapter) if on else None
    if on is not None and chapter is None:
        print(f"no chapter matches {wanted_chapter!r}; try --list",
              file=sys.stderr)
        return 1

    theme = themes.detect() if args.theme == "auto" else args.theme
    # With nothing named and several books, open on the newest one's first
    # chapter behind the shelf: the shelf is what you are actually looking at.
    start = chapter.path if chapter else shelf[0].chapters[0].path
    app = Reader(start, theme=theme, folder=folder,
                 prefix=on.prefix if on else "")
    if args.export:
        written = app.export_pdf(args.export, cols=args.width)
        print(f"{written['notes']} notes -> {written['path']} "
              f"({written['pages']} pages)")
        return 0
    app.run(show_contents=wanted_chapter is None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
