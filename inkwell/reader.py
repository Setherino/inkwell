"""A textbook in inkwell: chapters as notebooks, with a table of contents.

    python3 -m inkwell.reader               # contents menu, then read
    python3 -m inkwell.reader 3             # straight into chapter 3
    python3 -m inkwell.reader kinematics    # ...or by (part of) its title
    python3 -m inkwell.reader --list        # print the contents and stop

The book is the set of notebooks in the notes folder whose names start with
the book prefix (``iar-01-introduction.json`` ...), the files tools/tex2ink.py
writes. When the reader is run from the packed archive (tools/build_reader.py)
the notebooks travel inside it and are copied into the notes folder the first
time -- never over a copy that is already there, so annotations survive.

The menu lists chapters in reading order; Enter opens a chapter's sections,
Enter on a section opens the notebook scrolled to it. Typing searches the
whole book as you go: matching sections first, then the passages that say
the word, each shown in context under its chapter, and Enter on a passage
opens the notebook at that very note. ``f2`` brings the contents back from
inside a chapter and ``ctrl f`` opens it ready to search, ``f10`` quits.
Everything else is inkwell: the book is editable, so notes can be written
straight into the margins.

    python3 -m inkwell.reader --find "kalman"   # search from the shell
"""

from __future__ import annotations

import argparse
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
from .app import Inkwell
from .widgets import VIEW

PREFIX = "iar"
TITLE = "Introduction to Autonomous Robots"
BOOK_FOLDER = "book"        # inside the package, only ever in the built archive

_SLOT = re.compile(r"^[a-z]+-(?P<slot>[0-9]+|[a-z])-")

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


# --- the book on disk -------------------------------------------------------
def contents(directory=None, prefix: str = PREFIX) -> list:
    """Every chapter in the folder, in reading order, with its sections."""
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


class Menu(urwid.WidgetWrap):
    """The table of contents, and the search. Arrows move, Enter opens."""

    signals = ["chosen", "closed"]

    def __init__(self, chapters, title: str = TITLE) -> None:
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
        self.hint.set_text(" ↑↓ move · ⏎ open · → ← unfold · esc close · f10 quit")

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
        if key in ("esc", "f2"):
            self._emit("closed")
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
    """inkwell with the contents menu where the folder dialog was."""

    def __init__(self, path, theme: str = "dark", prefix: str = PREFIX) -> None:
        super().__init__(path, use_llm=False, theme=theme)
        self.prefix = prefix
        self.menu: Menu | None = None

    def open_library(self) -> None:         # f2
        self.open_contents()

    def _command(self, key: str) -> bool | None:
        if key == "ctrl f":                 # where a reader looks for a search
            self.open_contents()
            return True
        return super()._command(key)

    def open_contents(self) -> None:
        if self.menu is not None:
            return self.close_contents()
        folder = self.path.parent if self.path else store.DEFAULT_DIR
        self.menu = Menu(contents(folder, self.prefix))
        urwid.connect_signal(self.menu, "chosen",
                             lambda _w, path, index: self.go(path, index))
        urwid.connect_signal(self.menu, "closed", lambda _w: self.close_contents())
        if self.loop:
            self.loop.widget = urwid.Overlay(
                self.menu, self.frame,
                align="center", width=("relative", 80), min_width=44,
                valign="middle", height=("relative", 85), min_height=10)

    def close_contents(self) -> None:
        self.menu = None
        if self.loop:
            self.loop.widget = self.frame
        self.stay()

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
        self._make_loop()
        if show_contents:
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


def report(hits, wanted: str) -> int:
    """Print what a search found, grouped the way the contents are printed."""
    if not hits:
        print(f"nothing in the book says {wanted!r}", file=sys.stderr)
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
    parser = argparse.ArgumentParser(prog="reader", description=TITLE)
    parser.add_argument("chapter", nargs="?", default=None,
                        help="a chapter number, letter, or part of its title")
    parser.add_argument("--list", action="store_true", help="print the contents")
    parser.add_argument("--find", metavar="TEXT",
                        help="print every passage in the book that says TEXT")
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
    chapters = contents(folder)
    if args.list:
        for ch in chapters:
            print(ch.title)
            for s in ch.sections:
                print("  " * s.level + s.title)
        return 0
    if not chapters:
        print(f"no book found in {folder} (nothing named {PREFIX}-*.json)",
              file=sys.stderr)
        return 1
    if args.find:
        return report(search(chapters, args.find, least=1), args.find)
    chapter = pick(chapters, args.chapter)
    if chapter is None:
        print(f"no chapter matches {args.chapter!r}; try --list", file=sys.stderr)
        return 1
    theme = themes.detect() if args.theme == "auto" else args.theme
    app = Reader(chapter.path, theme=theme)
    if args.export:
        written = app.export_pdf(args.export, cols=args.width)
        print(f"{written['notes']} notes -> {written['path']} "
              f"({written['pages']} pages)")
        return 0
    app.run(show_contents=args.chapter is None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
