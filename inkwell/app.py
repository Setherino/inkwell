"""Inkwell: type into the box at the bottom; notes format themselves above.

Layout is a Frame -- ListBox of notes over a composer. The only stateful
thing worth knowing: nothing about a note's appearance is stored. Every
frame, document.py re-lays each note at the current terminal size, so a
resize is a re-format rather than a re-flow.

The other thing worth knowing is where you are. The interface is a tree,
so it is written down as one -- ``SHELF`` to ``EDITING`` below -- and esc is
one step up it, from wherever you happen to be. ``ascend`` is the whole
ladder in one place: no widget decides what "up" means from where it sits,
they hand esc back and the app, which is the only thing that knows the
shape of the tree, moves the cursor.
"""

from __future__ import annotations

import argparse
import os
import sys
import contextlib
from pathlib import Path

import urwid

from . import shaping as S
from . import store
from . import clip
from . import pdf as pdf_export
from . import theme as themes
from .document import Document
from .history import History
from .muse import Muse
from .widgets import VIEW, Composer, Library, NoteWidget

IDLE_COMMIT = 3.0        # seconds of quiet before an unfinished line is filed

# The tree, deepest last. Esc always makes this number smaller.
#
# A tree can be taller in one app than another: the reader's shelf of books
# sits at SHELF, above the contents of any one of them. Plain inkwell has
# nothing above ROOT, so it simply never reports that level.
SHELF = 0           # which book (the reader only)
ROOT = 1            # the folder of notebooks (the reader: one book's contents)
COMPOSER = 2        # the box at the bottom
PAGE = 3            # a note has the cursor bar; arrows scroll
EDITING = 4         # an open box -- the halo, or one of its panes

# Shift+Enter is not a key a terminal sends by default: the usual answer is a
# bare CR, which is indistinguishable from Enter. A terminal that can tell the
# two apart says so with a CSI-u sequence (kitty, WezTerm, ghostty, newer
# iTerm2) or xterm's modifyOtherKeys form, and urwid 4 decodes neither.
SHIFT_ENTER = ("[13;2u", "[27;2;13~")


def _key_tries() -> list:
    """Every sequence trie urwid might decode this terminal's input with.

    There is meant to be one. In urwid 4.0.8 ``urwid.display.escape`` hands
    out two different module objects for the single ``sys.modules`` entry, so
    the ``process_keyqueue`` you get by importing it is not the one the
    screen's parser calls, and they own separate tries. Teaching the wrong
    one looks like it worked -- ``trie.get`` finds the sequence afterwards --
    while the app goes on seeing "meta [". So teach all of them.
    """
    found: list = []

    def remember(trie) -> None:
        if trie is not None and not any(trie is seen for seen in found):
            found.append(trie)

    try:
        from urwid.display.escape import process_keyqueue
        remember(process_keyqueue.__globals__.get("input_trie"))
    except Exception:                   # noqa: BLE001 - some other urwid
        pass
    try:
        from urwid import raw_display
        escape = raw_display.Screen.parse_input.__globals__.get("escape")
        remember(getattr(escape, "input_trie", None))
    except Exception:                   # noqa: BLE001
        pass
    for module in list(sys.modules.values()):
        remember(getattr(module, "input_trie", None))
    return found


def teach_shift_enter() -> None:
    """Teach urwid the sequences a terminal sends for shift+enter."""
    for trie in _key_tries():
        for sequence in SHIFT_ENTER:
            codes = [ord(character) for character in sequence]
            try:
                if trie.get(codes, False) is None:
                    trie.add(trie.data, sequence, "shift enter")
            except Exception:           # noqa: BLE001 - a trie conflict
                pass


class _Screen(urwid.raw_display.Screen):
    """A screen that keeps the editing keys for editing.

    A terminal claims ctrl+c, ctrl+z, ctrl+s and ctrl+v for itself -- but on
    a Mac set up the usual way those are copy, undo, save and paste, so they
    are taken back for the duration. urwid puts the terminal's own settings
    back when the screen stops, so the shell gets them again on the way out.
    """

    def start(self, *args, **kwargs):
        started = super().start(*args, **kwargs)
        try:
            self.tty_signal_keys(intr="undefined", quit="undefined",
                                 start="undefined", stop="undefined",
                                 susp="undefined")
        except Exception:                   # noqa: BLE001 - not every terminal
            pass
        try:
            import termios
            fd = self._term_input_file.fileno()
            settings = termios.tcgetattr(fd)
            settings[3] &= ~termios.IEXTEN          # ...and ctrl+v (literal next)
            termios.tcsetattr(fd, termios.TCSADRAIN, settings)
        except Exception:                   # noqa: BLE001
            pass
        return started


class Deck(urwid.Frame):
    """A Frame that tells the notes how much screen there is.

    Notes read the size from ``VIEW`` at render time, so a resize costs
    nothing until something is actually drawn.
    """

    no_cache = ["render"]

    def __init__(self, *args, on_resize=None, on_input=None, **kwargs) -> None:
        self._on_resize = on_resize
        self._on_input = on_input
        self._last: tuple[int, int] | None = None
        self.body_size: tuple[int, int] | None = None
        super().__init__(*args, **kwargs)

    def render(self, size, focus: bool = False):
        VIEW.cols, VIEW.rows = size
        (htrim, ftrim), _rows = self.frame_top_bottom(size, focus)
        self.body_size = (size[0], max(1, size[1] - htrim - ftrim))
        if size != self._last:
            self._last = size
            if self._on_resize:
                self._on_resize()
        return super().render(size, focus)

    # Every input event ends with a look at who still has the cursor, so a
    # note that lost focus can put itself away.
    def keypress(self, size, key: str):
        result = super().keypress(size, key)
        if self._on_input:
            self._on_input(False)
        return result

    def mouse_event(self, size, event, button, col, row, focus):
        maxcol, maxrow = size
        (htrim, ftrim), _rows = self.frame_top_bottom(size, focus)
        in_body = htrim <= row < maxrow - ftrim
        handled = super().mouse_event(size, event, button, col, row, focus)
        if self._on_input:
            # A press in the body that nothing claimed is a click on the page
            # itself: treat it as putting the pen down.
            blank = bool(in_body and not handled
                         and urwid.util.is_mouse_press(event) and button == 1)
            self._on_input(blank)
        return handled


class Inkwell:
    def __init__(self, path: Path | None, use_llm: bool = True,
                 theme: str = "dark") -> None:
        self.path = Path(path) if path else None
        self.theme = theme if theme in themes.PALETTES else "dark"
        self.library: Library | None = None
        self._said = ""            # something to tell the writer, once
        self._anchor: int | None = None    # where a note selection started
        self._grouping = 0                 # >0 while one gesture is under way
        self._came_from: int | None = None  # the level the root is covering
        self.doc = Document()
        self.history = History()
        self.walker = urwid.SimpleFocusListWalker([])
        self.listbox = urwid.ListBox(self.walker)
        self.listbox.set_focus_valign("bottom")
        self.composer = Composer()
        self.status = urwid.Text("", align="left", wrap="clip")
        footer = urwid.Pile([
            urwid.AttrMap(self.status, "status"),
            urwid.AttrMap(self.composer, None),
        ])
        self.frame = Deck(self.listbox, footer=footer, focus_part="footer",
                          on_resize=self._on_resize, on_input=self._settle)
        self.muse = Muse() if use_llm else Muse(key="")
        self.loop: urwid.MainLoop | None = None
        self._idle = None
        self._wake_fd = None
        self._notes: list[NoteWidget] = []

        urwid.connect_signal(self.composer, "commit", lambda _w, text: self.commit(text))
        urwid.connect_signal(self.composer, "typed", lambda _w: self.touch())
        urwid.connect_signal(self.composer, "sink", lambda _w: self.to_notes())

        self._stamp = store.stamp_of(path) if path else 0.0
        for note in (store.load(path) if path else []):
            self._attach(note, refresh=False)
        self.remember()
        self._refresh()

    def _close_boxes(self, *, except_for=None) -> None:
        """Close every open edit box, keeping what it says. Focus untouched."""
        with self.holding_the_view():
            for widget in list(self._notes):
                if widget.editing and widget is not except_for:
                    widget.stop_edit()

    def _settle(self, blank_click: bool = False) -> None:
        """Close any edit box that no longer holds the cursor.

        Clicking (or arrowing) away from a note is the same as pressing
        Enter on it: the text is kept and the note goes back to normal.
        """
        if blank_click:
            self.stay()
            return
        focused = self.listbox.focus if self.frame.focus_position == "body" else None
        self._close_boxes(except_for=focused)

    def _on_resize(self) -> None:
        self._refresh()
        with self.holding_the_view():
            for widget in self._notes:
                widget._invalidate()

    # --- notes ------------------------------------------------------------
    def _attach(self, note, *, refresh: bool = True) -> NoteWidget:
        widget = NoteWidget(note, self.doc)
        urwid.connect_signal(widget, "changed", self._changed)
        urwid.connect_signal(widget, "removed", self._removed)
        urwid.connect_signal(widget, "leave", lambda _w: self.stay())
        urwid.connect_signal(widget, "step", self.step)
        urwid.connect_signal(widget, "split", self._split)
        urwid.connect_signal(widget, "join_up", self._join_up)
        urwid.connect_signal(widget, "join_down", self._join_down)
        self._notes.append(widget)
        self.walker.append(widget)
        self.reformat()
        if refresh:
            self._refresh()
        return widget

    def commit(self, text: str) -> None:
        text = text.rstrip()          # leading spaces are the nesting marker
        if not text.strip():
            return
        following = self.at_the_end()
        view = self._view()
        note = store.Note(text)
        widget = self._attach(note)
        self.muse.ask(id(note), text, wake=self._wake, context=self.context())
        # Typing at the foot of the page follows along; reading further up
        # is left exactly where it was.
        if following:
            self._scroll_to_end()
        else:
            self._restore(view)
        self.remember()
        self.save()

    def _changed(self, widget) -> None:
        self._explode(widget)
        self.reformat()
        self.remember()
        if widget.note.text.strip():
            self.muse.ask(id(widget.note), widget.note.text, wake=self._wake,
                          context=self.context(widget))
        self.save()
        self._refresh()

    def _explode(self, widget) -> bool:
        """A blank line inside a note starts a new block, so make it one.

        The whole thing counts as a single step to undo: it is one gesture
        as far as the writer is concerned.
        """
        chunks = S.blocks_in(widget.note.text)
        if len(chunks) < 2:
            return False
        at = self._position(widget)
        if at < 0:
            return False
        # Starting a new block inside a list keeps you in the list.
        marker = S.list_marker_of(chunks[0])
        with self.one_step():
            widget.note.text = chunks[0]
            widget.note.fmt = {}
            widget.note.emphasis = ""
            widget.note.tag = ""
            widget._built = None
            for offset, chunk in enumerate(chunks[1:], 1):
                if marker and not S.classify(chunk).explicit:
                    chunk = marker + chunk
                self._insert(at + offset, chunk)
        return True

    def reformat(self) -> None:
        """Re-lay the whole document; every note may be affected by any edit."""
        with self.holding_the_view():
            self.doc.rebuild([w.note for w in self._notes])
            for widget in self._notes:
                widget._built = None
                widget._invalidate()

    def context(self, before=None) -> list[str]:
        """The few notes above, so the model can nest and group sensibly."""
        texts = []
        for widget in self._notes:
            if widget is before:
                break
            texts.append(widget.note.text)
        return texts[-6:]

    def _removed(self, widget) -> None:
        if widget in self._notes:
            self._notes.remove(widget)
        for i, w in enumerate(self.walker):
            if w is widget:
                del self.walker[i]
                break
        self.reformat()
        self.remember()
        if not any(w.editing for w in self._notes):
            self.stay()             # don't steal the cursor from another note
        self.save()
        self._refresh()

    # --- splitting and joining -------------------------------------------
    def _position(self, widget) -> int:
        for i, candidate in enumerate(self._notes):
            if candidate is widget:
                return i
        return -1

    def _insert(self, at: int, text: str) -> NoteWidget:
        note = store.Note(text)
        widget = NoteWidget(note, self.doc)
        urwid.connect_signal(widget, "changed", self._changed)
        urwid.connect_signal(widget, "removed", self._removed)
        urwid.connect_signal(widget, "leave", lambda _w: self.stay())
        urwid.connect_signal(widget, "step", self.step)
        urwid.connect_signal(widget, "split", self._split)
        urwid.connect_signal(widget, "join_up", self._join_up)
        urwid.connect_signal(widget, "join_down", self._join_down)
        self._notes.insert(at, widget)
        self.walker.insert(at, widget)
        self.reformat()
        self.muse.ask(id(note), text, wake=self._wake,
                      context=[w.note.text for w in self._notes[max(0, at - 6):at]])
        self.remember()
        self.save()
        return widget

    def _split(self, widget, tail: str) -> None:
        """One box becomes two, with the cursor at the head of the new one."""
        at = self._position(widget) + 1
        fresh = self._insert(at, tail)
        self.history.merge_last()      # one gesture, one step to undo
        self.frame.focus_position = "body"
        self.listbox.set_focus(at)
        fresh.start_edit(at_end=False)
        self._refresh()

    def _join_up(self, widget) -> None:
        """Backspace at the start of a note glues it onto the one above."""
        at = self._position(widget)
        if at <= 0:
            return
        above = self._notes[at - 1]
        text = widget._edit.edit_text if widget.editing else widget.note.text
        joined = S.join(above.note.text, text)
        cursor = len(above.note.text.rstrip())
        widget.editing = False
        widget._edit = None
        above.note.text = joined
        above.note.fmt = {}
        above.note.emphasis = ""
        self._drop(widget)
        self.frame.focus_position = "body"
        self.listbox.set_focus(self._position(above))
        above.start_edit()
        above._edit.edit_pos = min(cursor, len(joined))
        self._changed(above)

    def _join_down(self, widget) -> None:
        """Delete at the end of a note pulls the next one up into it."""
        at = self._position(widget)
        if at < 0 or at + 1 >= len(self._notes):
            return
        below = self._notes[at + 1]
        text = widget._edit.edit_text if widget.editing else widget.note.text
        cursor = len(text.rstrip())
        joined = S.join(text, below.note.text)
        self._drop(below)
        widget.note.text = joined
        widget.note.fmt = {}
        widget.note.emphasis = ""
        if widget.editing:
            widget._edit.set_edit_text(joined)
            widget._edit.edit_pos = min(cursor, len(joined))
            widget._built = None
            widget._invalidate()
        self._changed(widget)

    def _drop(self, widget) -> None:
        """Take a widget out of the page without touching focus."""
        if widget in self._notes:
            self._notes.remove(widget)
        for i, candidate in enumerate(self.walker):
            if candidate is widget:
                del self.walker[i]
                break
        self.reformat()

    def save(self) -> None:
        """Write the notebook out, unless something else got there first.

        Another session -- an old window left open -- would otherwise
        silently replace this one's work. If the file changed underneath us,
        write beside it instead and say so.
        """
        if not self.path:
            return
        notes = [w.note for w in self._notes]
        found = store.stamp_of(self.path)
        if self._stamp and found and abs(found - self._stamp) > 0.001:
            spare = store.beside(self.path)
            store.save(notes, spare)
            self._said = (f"{self.path.name} changed underneath -- saved to "
                          f"{spare.name} instead")
            self._stamp = found
            return
        self._stamp = store.save(notes, self.path)

    # --- picking notes ------------------------------------------------------
    def picked(self) -> list:
        """The notes currently picked out, in page order."""
        return [w for w in self._notes if w.picked]

    def _repaint(self, chosen) -> None:
        for widget in self._notes:
            want = widget in chosen
            if widget.picked != want:
                widget.picked = want
                widget._built = None
                widget._invalidate()

    def reach(self, step: int) -> None:
        """Extend the picked run up or down the page (shift and an arrow)."""
        if not self._notes:
            return
        here = self.listbox.focus_position
        if self._anchor is None:
            self._anchor = here
        target = min(max(here + step, 0), len(self._notes) - 1)
        with self.holding_the_view():
            self.listbox.set_focus(target)
        first, last = sorted((self._anchor, target))
        self._repaint(self._notes[first:last + 1])
        self._refresh()

    def pick_all(self) -> None:
        self._anchor = 0
        self._repaint(self._notes)
        self._refresh()

    def unpick(self) -> None:
        self._anchor = None
        self._repaint([])

    def _chosen(self) -> list:
        """What a copy would take: the picked notes, or the focused one."""
        chosen = self.picked()
        if chosen:
            return chosen
        if self.frame.focus_position == "body" and self.listbox.focus:
            return [self.listbox.focus]
        return []

    def copy_notes(self, cut: bool = False) -> int:
        """Notes leave as text, one blank line between them."""
        chosen = self._chosen()
        if not chosen:
            return 0
        clip.copy("\n\n".join(w.note.text for w in chosen))
        if cut:
            with self.one_step(), self.holding_the_view():
                for widget in chosen:
                    self._drop(widget)
            self.unpick()
            self.save()
        self._said = (f"{'cut' if cut else 'copied'} {len(chosen)} note"
                      f"{'' if len(chosen) == 1 else 's'}")
        self._refresh()
        return len(chosen)

    def paste_notes(self) -> int:
        """Text arrives as notes: a blank line between blocks, as ever."""
        chunks = S.blocks_in(clip.paste())
        if not chunks:
            return 0
        at = (self.listbox.focus_position + 1
              if self.frame.focus_position == "body" and self._notes
              else len(self._notes))
        with self.one_step():
            for offset, chunk in enumerate(chunks):
                self._insert(at + offset, chunk)
        self._said = (f"pasted {len(chunks)} note"
                      f"{'' if len(chunks) == 1 else 's'}")
        self._refresh()
        return len(chunks)

    # --- export -----------------------------------------------------------
    def export_pdf(self, path=None, cols: int = 92) -> dict:
        """Write the page out as a PDF, next to the notebook by default."""
        if path is None:
            path = (self.path.with_suffix(".pdf") if self.path
                    else store.ensure() / "notes.pdf")
        return pdf_export.export([w.note for w in self._notes], path,
                                 cols=cols, theme="light",
                                 title=self.notebook_name())

    # --- undo -------------------------------------------------------------
    def remember(self) -> None:
        """Record the page as a step you can come back to."""
        if self._grouping:
            return                      # mid-gesture: one step, recorded at the end
        self.history.record([w.note for w in self._notes])

    @contextlib.contextmanager
    def one_step(self):
        """Several changes that are a single thing to undo."""
        self._grouping += 1
        try:
            yield
        finally:
            self._grouping -= 1
        self.remember()

    def undo(self) -> bool:
        return self._step(self.history.undo())

    def redo(self) -> bool:
        return self._step(self.history.redo())

    def _step(self, notes) -> bool:
        """Put a remembered page back, without moving what you are reading."""
        if notes is None:
            return False
        with self.holding_the_view():
            for widget in self._notes:
                widget.stop_edit(keep=False)
            del self.walker[:]
            self._notes = []
            for note in notes:
                self._attach(note, refresh=False)
            self.reformat()
        self.save()
        self._refresh()
        return True

    # --- the root of the tree ---------------------------------------------
    # The folder of notebooks sits above everything else; the reader puts its
    # table of contents here instead, so these three are what ``ascend``
    # talks to rather than the dialog itself.
    def at_root(self) -> bool:
        return self.library is not None

    def open_root(self) -> None:
        """Show the top of the tree: f2, and esc out of the composer."""
        if not self.at_root():
            # Coming up here is leaving the note you were in, so the box
            # closes (keeping its text) -- and esc back down must never land
            # in an edit box that is no longer open.
            self._came_from = min(self.depth(), PAGE)
            self._close_boxes()
        self.open_library()

    def close_root(self) -> None:
        self.close_library()

    def _uncover(self) -> None:
        """Put the cursor back at the level the root was covering."""
        level = self._came_from
        self._came_from = None
        self.go_to(PAGE if level is None else level)

    # --- notebooks --------------------------------------------------------
    def open_library(self) -> None:
        """Show the folder of notebooks."""
        if self.library is not None:
            return self.close_library()
        directory = store.ensure(self.path.parent if self.path
                                 else store.DEFAULT_DIR)
        self.library = Library(directory, self.path)
        urwid.connect_signal(self.library, "chosen",
                             lambda _w, path: self.load_notebook(path))
        urwid.connect_signal(self.library, "closed", lambda _w: self.close_library())
        if self.loop:
            self.loop.widget = urwid.Overlay(
                self.library, self.frame,
                align="center", width=("relative", 66), min_width=46,
                valign="middle", height="pack")

    def close_library(self) -> None:
        self.library = None
        if self.loop:
            self.loop.widget = self.frame
        self._uncover()

    def load_notebook(self, path) -> None:
        """Save what is open, then put another notebook on the page."""
        self.save()
        self.path = Path(path)
        self._stamp = store.stamp_of(self.path)
        del self.walker[:]
        self._notes = []
        self.history = History()        # each notebook has its own past
        for note in store.load(self.path):
            self._attach(note, refresh=False)
        self.reformat()
        self.remember()
        self.close_library()
        self._refresh()

    def notebook_name(self) -> str:
        return store.title_of(self.path) if self.path else "scratch"

    # --- the view ---------------------------------------------------------
    # The page must not move under you. Anything that changes the document
    # records where the reader is looking and puts it back afterwards.
    def _view(self):
        """(position, offset from the top of the body) -- where you are looking.

        By position rather than by widget, so it survives undo, which builds
        the page again from scratch.
        """
        size = self.frame.body_size
        if size is None or not len(self.walker):
            return None
        try:
            offset, _inset = self.listbox.get_focus_offset_inset(size)
            return self.listbox.focus_position, offset
        except Exception:                   # noqa: BLE001 - never break a redraw
            return None

    def _restore(self, view) -> None:
        if view is None or not len(self.walker):
            return
        position, offset = view
        size = self.frame.body_size
        if size is None:
            return
        try:
            self.listbox.change_focus(size, min(position, len(self.walker) - 1),
                                      offset)
        except Exception:                   # noqa: BLE001
            pass

    @contextlib.contextmanager
    def holding_the_view(self):
        """Do something to the document without scrolling the reader away."""
        view = self._view()
        try:
            yield
        finally:
            self._restore(view)

    def at_the_end(self) -> bool:
        """True when the last note is already on screen."""
        size = self.frame.body_size
        if size is None or not len(self.walker):
            return True
        try:
            return "bottom" in self.listbox.ends_visible(size)
        except Exception:                   # noqa: BLE001
            return True

    # --- where you are in the tree ----------------------------------------
    def depth(self) -> int:
        """Which level of the tree has the cursor. Esc always lowers it."""
        if self.at_root():
            return ROOT
        if any(widget.editing for widget in self._notes):
            return EDITING
        return PAGE if self.frame.focus_position == "body" else COMPOSER

    def ascend(self) -> bool:
        """Esc: one step up the tree, from wherever you are in it.

        A picked run of notes, a selection inside a box, a filter typed
        into the contents -- those decorate a level rather than being one
        of their own, so they go when you leave the level they belong to.
        Nothing costs two presses to get out of.
        """
        here = self.depth()
        if here == EDITING:
            self.stay()             # the box closes, keeping what it says
        elif here == PAGE:
            self.unpick()           # a picked run belongs to the page you left
            self.to_composer()
        elif here == COMPOSER:
            self.open_root()
        else:
            # At the top, or on the level above it. Whatever is showing
            # steps aside; if something was covering another modal, that
            # one is what you come back to.
            self.close_root()
        self._refresh()
        return True

    def go_to(self, level: int) -> None:
        """Put the cursor on a level: PAGE, or the composer below it."""
        if level >= PAGE:
            self.stay()
        else:
            self.to_composer()

    # --- focus ------------------------------------------------------------
    def stay(self) -> None:
        """Close whatever is open, and stay in the page.

        Finishing a note leaves you among the notes, ready to arrow about
        -- one rung up is esc's job, not Enter's.
        """
        self._close_boxes()
        self.frame.focus_position = "body" if self._notes else "footer"

    def step(self, widget, direction: int) -> None:
        """Move to the note above or below (an arrow off the end of a note)."""
        at = self._position(widget)
        if at < 0:
            return
        target = at + direction
        self.frame.focus_position = "body"
        if not 0 <= target < len(self._notes):
            return
        size = self.frame.body_size
        if size is None:
            self.listbox.set_focus(target)
            return
        self.listbox.change_focus(size, target,
                                  coming_from="below" if direction < 0 else "above")

    def to_composer(self) -> None:
        """Put the pen down. The page stays where it is."""
        self._close_boxes()
        self.frame.focus_position = "footer"

    def to_notes(self) -> None:
        """Step up into the page, onto the nearest note you can see.

        Nearest means the bottom-most one on screen: you are coming up out
        of the composer, so that is the one under your eyes -- and it never
        scrolls, because it is already visible.
        """
        if not self._notes:
            return
        self.frame.focus_position = "body"
        size = self.frame.body_size
        if size is None:
            self.listbox.set_focus(len(self.walker) - 1)
            return
        try:
            middle, _top, bottom = self.listbox.calculate_visible(size, True)
            below = list(bottom[1]) if bottom else []
            if not below:
                return                      # already on the last visible note
            offset, _widget, _position, rows, _cursor = middle
            # Where the target sits now, so moving the focus there does not
            # scroll the page a single row.
            offset += rows + sum(each[2] for each in below[:-1])
            _widget, position, _rows = below[-1]
            self.listbox.change_focus(size, position,
                                      min(offset, size[1] - 1))
        except Exception:                   # noqa: BLE001 - keep the focus we have
            pass

    def _scroll_to_end(self) -> None:
        """Only ever called when the reader is already at the foot of it."""
        if len(self.walker):
            self.listbox.set_focus_valign("bottom")
            self.listbox.set_focus(len(self.walker) - 1)

    def jump_to(self, index: int) -> None:
        """Put a note (a chapter's section heading, say) at the top of the page."""
        if not self._notes:
            return
        index = max(0, min(int(index), len(self._notes) - 1))
        self.stay()
        self.frame.focus_position = "body"
        self.listbox.set_focus_valign("top")
        self.listbox.set_focus(index)

    # --- idle commit ------------------------------------------------------
    def touch(self) -> None:
        self._said = ""
        if not self.loop:
            return
        if self._idle is not None:
            self.loop.remove_alarm(self._idle)
        self._idle = self.loop.set_alarm_in(IDLE_COMMIT, self._on_idle)
        self._refresh()

    def _on_idle(self, *_args) -> None:
        """A pause counts as ending the thought."""
        self._idle = None
        if S.is_idle_commit(self.composer.edit_text):
            self.composer.flush()
        self._refresh()

    # --- llm --------------------------------------------------------------
    def _wake(self) -> None:
        if self._wake_fd is not None:
            try:
                os.write(self._wake_fd, b".")
            except OSError:
                pass

    def _absorb(self, _data=b"") -> bool:
        by_id = {id(w.note): w for w in self._notes}
        touched = False
        for note_id, fields in self.muse.drain():
            widget = by_id.get(note_id)
            if widget is None:
                continue
            note = widget.note
            fields = dict(fields)
            if fields.get("block") not in S.FORMATTABLE:
                fields.pop("block", None)   # never a title, never a typo
            # Markup the user typed themselves is never overruled -- the
            # formatter only fills in what was left plain.
            if S.classify(note.text).explicit:
                fields = {k: v for k, v in fields.items()
                          if k in ("emphasis", "tag")}
            note.fmt = {k: v for k, v in fields.items()
                        if k not in ("emphasis", "tag")}
            note.emphasis = fields.get("emphasis", "") or ""
            note.tag = fields.get("tag", "") or ""
            touched = True
        if touched:
            # An answer arriving from the model must never tug the page.
            with self.holding_the_view():
                self.reformat()
            self.remember()
            self.save()
        self._refresh()
        return True

    # --- chrome -----------------------------------------------------------
    def _refresh(self) -> None:
        count = len(self._notes)
        bits = [self.notebook_name(), f"{count} note{'' if count == 1 else 's'}"]
        # The hints earn their place by width: the status line never wraps.
        if VIEW.cols >= 54:
            bits.append("f2 open · f5 " + themes.other(self.theme))
        if VIEW.cols >= 78:
            bits.append("^z undo · f8 delete · f10 quit")
        if VIEW.cols >= 100:
            bits.append("^c copy · ^v paste · ^p pdf · f6 join")
        if VIEW.cols >= 116:
            bits.append(f"{VIEW.cols}×{VIEW.rows}")
        if self.muse.enabled:
            bits.append(f"llm {'…' if self.muse.pending else '✓'}")
        if self._said:
            self.status.set_text([("status_said", " " + self._said)])
            return
        markup = [("status", " " + " · ".join(bits))]
        if not count and VIEW.cols >= 40:
            markup = [("ghost", "  type a sentence — it files itself when you "
                                "end it, or pause")]
        self.status.set_text(markup)

    def unhandled(self, key: str) -> bool | None:
        told = self._said
        result = self._command(key)
        if told and self._said == told:
            self._said = ""                 # last time's message, now stale
            self._refresh()
        return result

    def _command(self, key: str) -> bool | None:
        if key in ("f10", "ctrl q"):
            raise urwid.ExitMainLoop
        if key in ("shift up", "shift down") and self._notes:
            if self.frame.focus_position != "body":
                self.to_notes()
            self.reach(-1 if key == "shift up" else 1)
            return True
        if key == "ctrl a" and self._notes:
            self.to_notes()
            self.pick_all()
            return True
        if key in ("ctrl c", "ctrl x"):
            self.copy_notes(cut=key == "ctrl x")
            return True
        if key == "ctrl v":
            self.paste_notes()
            return True
        if key == "ctrl p":
            try:
                written = self.export_pdf()
            except Exception as exc:              # noqa: BLE001 - just say so
                self._said = f"could not write the PDF: {exc}"
            else:
                where = str(written["path"]).replace(str(Path.home()), "~")
                self._said = (f"{written['pages']} page"
                              f"{'' if written['pages'] == 1 else 's'} "
                              f"-> {where}")
                if written["undrawable"]:
                    self._said += (f" (no glyph for {written['undrawable']})")
            self._refresh()
            return True
        if key in ("ctrl z", "ctrl _", "f11"):
            self.undo()
            return True
        if key in ("ctrl r", "ctrl y"):
            self.redo()
            return True
        if key == "f2":
            self.open_root()
            return True
        if key == "f5":
            self.set_theme(themes.other(self.theme))
            return True
        if key == "f8":
            if self.frame.focus_position == "body" and self._notes:
                self._removed(self.listbox.focus)
            return True
        if key in ("f4", "f3") and self.frame.focus_position == "body":
            widget = self.listbox.focus
            if widget is not None:
                (widget.split_across if key == "f4" else widget.unsplit_across)()
            return True
        if key == "f6":
            if self.frame.focus_position == "body" and self.listbox.focus:
                self._join_up(self.listbox.focus)
            return True
        if key == "f9":
            VIEW.unicode_ok = not VIEW.unicode_ok
            self._invalidate_all()
            return True
        if key == "f7":
            VIEW.big = not VIEW.big
            self._invalidate_all()
            return True
        if key == "esc":
            return self.ascend()        # ...one step up the tree, always
        if key == "down" and self.frame.focus_position == "body":
            if self._notes and self.listbox.focus is self._notes[-1]:
                self.to_composer()
                return True
        return None

    def set_theme(self, name: str) -> None:
        """Switch palettes without restarting."""
        self.theme = name if name in themes.PALETTES else "dark"
        if self.loop:
            self.loop.screen.register_palette(themes.palette(self.theme))
            self.loop.screen.clear()
        self._refresh()

    def _invalidate_all(self) -> None:
        for widget in self._notes:
            widget._built = None
            widget._invalidate()
        self._refresh()

    # --- run --------------------------------------------------------------
    def _make_loop(self) -> urwid.MainLoop:
        teach_shift_enter()
        screen = _Screen()
        try:
            screen.set_terminal_properties(colors=256)
        except Exception:                          # noqa: BLE001 - 16-colour term
            pass
        self.loop = urwid.MainLoop(self.frame, themes.palette(self.theme),
                                   screen=screen,
                                   unhandled_input=self.unhandled,
                                   handle_mouse=True)
        self._attach_wakeup(self.loop)
        return self.loop

    def _attach_wakeup(self, loop) -> None:
        """The pipe the model's thread pokes to say an answer is in.

        Only wanted when there is a model to answer -- and urwid has no
        watch_pipe on Windows, so a reader (no model) never asks for one.
        """
        if self.muse.enabled and hasattr(loop, "watch_pipe"):
            self._wake_fd = loop.watch_pipe(self._absorb)

    def run(self) -> None:
        self._make_loop()
        self.loop.run()


def resolve(given=None, directory: Path | None = None) -> Path:
    """Which notebook to open: the one named, or the newest in the folder.

    A bare name ("hw0") means a notebook in the folder, not a file in the
    working directory -- that is almost always what someone means.
    """
    folder = store.ensure(directory)
    if given is None:
        return (store.notebooks(folder) or [store.default_path(folder)])[0]
    given = Path(given)
    if given.exists() or given.parent != Path("."):
        return given
    if given.suffix == store.SUFFIX:
        return folder / given.name
    # An exact name wins over a tidied one: a notebook called HW0 keeps its
    # capitals, so exporting it writes HW0.pdf.
    exact = folder / (given.name + store.SUFFIX)
    if exact.exists():
        return exact
    return store.path_for(given.name, folder)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="inkwell", description=__doc__.split("\n\n")[0])
    parser.add_argument("notebook", nargs="?", type=Path, default=None,
                        help="a notebook in the folder, by name (\"HW0\")")
    parser.add_argument("--file", type=Path, default=None,
                        help="a notebook to open (default: the newest in "
                             + str(store.DEFAULT_DIR) + ")")
    parser.add_argument("--export", metavar="FILE.pdf", type=Path,
                        help="write the notebook to a PDF and stop")
    parser.add_argument("--width", type=int, default=92, metavar="COLUMNS",
                        help="how wide the exported page is (default: 92)")
    parser.add_argument("--theme", default="auto",
                        choices=("auto", "light", "dark"),
                        help="colours for a light or dark terminal "
                             "(default: ask the terminal)")
    parser.add_argument("--no-save", action="store_true", help="scratch session")
    parser.add_argument("--no-llm", action="store_true",
                        help="heuristics only, no network")
    parser.add_argument("--ascii", action="store_true",
                        help="no unicode letterforms")
    args = parser.parse_args(argv)
    VIEW.unicode_ok = not args.ascii
    theme = themes.detect() if args.theme == "auto" else args.theme
    path = None if args.no_save else resolve(args.notebook or args.file)
    app = Inkwell(path, use_llm=not args.no_llm, theme=theme)
    if args.export:
        written = app.export_pdf(args.export, cols=args.width)
        print(f"{written['notes']} notes -> {written['path']} "
              f"({written['pages']} pages, {written['size'] // 1024} KB)")
        if written["undrawable"]:
            print("no glyph for: " + written["undrawable"])
        return 0
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
