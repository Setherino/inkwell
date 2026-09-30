"""The widgets: one note, and the box you type into.

A note is *always* an editable text box -- it just spends most of its life
drawn as formatted document text. Clicking it (or Enter, or typing) swaps
in a real ``urwid.Edit`` with a cursor where you clicked; Enter, Esc or
clicking away swaps it back, re-formatted.

None of these widgets handles esc. It means "up one level of the tree",
and a widget cannot know what is above it -- so esc is handed back and
``app.ascend`` deals with it. See the tree in app.py.
"""

from __future__ import annotations

import urwid

import time
from pathlib import Path

from . import clip
from . import shaping as S
from . import store
from . import typography as T

GUTTER = 2          # reserved on the left for the focus bar
HALO = 1            # a character of blue all round an open edit box
# The little strip of buttons along the bottom of an open box. Each one has
# a key as well, but they are there to be clicked.
BUTTONS = (("break", "  ⏎  "), ("done", "  ✓  "), ("drop", "  ✕  "))
BUTTONS_AT = 34     # ...shown once the box is at least this wide


class Viewport:
    """Last known screen size and display toggles, read at render time."""

    cols = 80
    rows = 24
    unicode_ok = True
    big = True


VIEW = Viewport()


# Shift plus one of these extends a selection; the same key alone drops it.
REACH = {"shift left": "left", "shift right": "right", "shift up": "up",
         "shift down": "down", "shift home": "home", "shift end": "end"}


class Field(urwid.Edit):
    """An edit box you can select text in, and copy out of.

    urwid's Edit has no notion of a selection, so this keeps an anchor: the
    span between it and the cursor is the selection, drawn highlighted and
    replaced by whatever you type next.
    """

    # Set before __init__ runs: urwid renders the text on the way in, and
    # rendering asks about the selection.
    anchor: int | None = None

    # --- the selection ----------------------------------------------------
    def selection(self):
        if self.anchor is None or self.anchor == self.edit_pos:
            return None
        return min(self.anchor, self.edit_pos), max(self.anchor, self.edit_pos)

    def selected_text(self) -> str:
        span = self.selection()
        return self.edit_text[span[0]:span[1]] if span else ""

    def select_all(self) -> None:
        self.anchor = 0
        self.set_edit_pos(len(self.edit_text))

    def drop_selection(self) -> None:
        self.anchor = None

    def cut_selection(self) -> str:
        span = self.selection()
        if not span:
            return ""
        first, last = span
        gone = self.edit_text[first:last]
        self.set_edit_text(self.edit_text[:first] + self.edit_text[last:])
        self.set_edit_pos(first)
        self.anchor = None
        return gone

    def put(self, text: str) -> None:
        """Paste, replacing whatever was selected."""
        self.cut_selection()
        self.insert_text(text)

    # Text arriving any other way -- a line break, a paste, a rewrite --
    # settles the selection. Otherwise the anchor is left behind and the
    # next thing typed swallows what was just inserted.
    def insert_text(self, text):
        self.anchor = None
        return super().insert_text(text)

    def set_edit_text(self, text):
        self.anchor = None
        return super().set_edit_text(text)

    def get_text(self):
        text, attrib = super().get_text()
        span = self.selection()
        if span:
            offset = len(self.caption)
            first, last = span
            attrib = [(None, offset + first), ("selected", last - first)]
        return text, attrib

    # --- keys -------------------------------------------------------------
    def keypress(self, size, key: str):
        # A key this box cannot use is handed back, so the page can have it:
        # shift+up in a one-line box means "select notes", not "select text".
        if key in REACH:
            was = self.anchor
            if self.anchor is None:
                self.anchor = self.edit_pos
            if super().keypress(size, REACH[key]) is not None:
                self.anchor = was
                return key
            self._invalidate()
            return None
        if key == "ctrl a":
            if not self.edit_text:
                return key
            self.select_all()
            self._invalidate()
            return None
        if key in ("ctrl c", "ctrl x"):
            taken = self.selected_text() or self.edit_text
            if not taken:
                return key
            clip.copy(taken)
            if key == "ctrl x":
                if self.selection():
                    self.cut_selection()
                else:
                    self.set_edit_text("")
            self._invalidate()
            return None
        if key == "ctrl v":
            arriving = clip.paste()
            if len(S.blocks_in(arriving)) > 1 and not self.multiline:
                return key              # several blocks: they want notes
            self.put(arriving)
            self._invalidate()
            return None
        if self.selection() and (key in ("backspace", "delete")
                                 or (len(key) == 1 and key.isprintable())):
            self.cut_selection()
            if key in ("backspace", "delete"):
                self._invalidate()
                return None
        result = super().keypress(size, key)
        if result is None and key not in REACH:
            self.anchor = None          # moving or typing settles the selection
        return result


class NoteWidget(urwid.Widget):
    _sizing = frozenset([urwid.Sizing.FLOW])
    _selectable = True
    no_cache = ["render", "rows"]
    signals = ["changed", "leave", "removed", "split", "join_up", "join_down",
               "step"]

    def __init__(self, note, doc) -> None:
        super().__init__()
        self.note = note
        self.doc = doc
        self.picked = False
        self.editing = False
        self._pane: int | None = None      # which pane is being edited
        self._edit: urwid.Edit | None = None
        self._built: tuple | None = None

    # --- formatting -------------------------------------------------------
    @property
    def block(self):
        return self.doc.block_for(self.note)

    def layout(self, maxcol: int):
        return self.doc.plan(self.note, max(8, maxcol - GUTTER),
                             maxrow=VIEW.rows, unicode_ok=VIEW.unicode_ok,
                             big=VIEW.big)

    # --- composition ------------------------------------------------------
    def _compose(self, maxcol: int, focus: bool):
        key = (maxcol, focus, self.editing, self._pane, self.doc.rev,
               self.note.text, self.note.done, self.picked, VIEW.rows,
               VIEW.unicode_ok, VIEW.big)
        if self._built and self._built[0] == key:
            return self._built[1]
        if self.editing and self._pane is None:
            widget = self._compose_edit(maxcol)
        else:
            widget = self._compose_display(maxcol, focus)
        self._built = (key, widget)
        return widget

    @staticmethod
    def _strip() -> str:
        return "".join(label for _name, label in BUTTONS)

    def _button_row(self, width: int):
        """The bottom of the halo: ⏎ break, ✓ done, ✕ discard."""
        if width < BUTTONS_AT:
            return urwid.Divider()
        strip = self._strip()
        markup = [(None, " " * max(0, width - len(strip)))]
        for _name, label in BUTTONS:
            markup.append(("halo_button", label))
        return urwid.Text(markup, wrap="clip")

    def buttons(self, maxcol: int) -> dict:
        """{name: (first column, last column)} for the strip, if it is shown."""
        left, width = self.halo_box(maxcol)
        if width < BUTTONS_AT:
            return {}
        at = left + width - len(self._strip())
        spans = {}
        for name, label in BUTTONS:
            spans[name] = (at, at + len(label) - 1)
            at += len(label)
        return spans

    def insert_break(self) -> None:
        """Put a line break in, right where the cursor is."""
        if not self.editing or self._edit is None:
            return
        self._edit.insert_text("\n")
        self._built = None
        self._invalidate()

    def halo_box(self, maxcol: int) -> tuple:
        """(left, width) of the blue block around an open edit box."""
        measure, offset = T.column(maxcol - GUTTER)
        left = max(0, GUTTER + offset - HALO)
        width = min(measure + 2 * HALO, maxcol - left)
        return left, width

    def _compose_edit(self, maxcol: int):
        assert self._edit is not None
        left, width = self.halo_box(maxcol)
        # A character of blue all the way round: it says "this one is open",
        # and it gives you somewhere forgiving to click.
        inner = urwid.Padding(urwid.AttrMap(self._edit, "editing"),
                              left=HALO, right=HALO)
        block = urwid.Pile([urwid.Divider(), inner, self._button_row(width)])
        return urwid.Padding(urwid.AttrMap(block, "halo"), left=left, width=width)

    def _compose_display(self, maxcol: int, focus: bool):
        plan = self.layout(maxcol)
        if self.picked:
            bar = ("picked", "█ ")
        elif focus:
            bar = ("cursorbar", "▌ ")
        else:
            bar = (None, "  ")
        pieces: list = []

        if plan.panes:
            body = self._compose_panes(plan)
            if plan.indent:
                body = urwid.Padding(body, left=plan.indent)
            body = urwid.Columns([(GUTTER, urwid.Text(bar)), ("weight", 1, body)])
        elif plan.big:
            size, lines = plan.big
            body = urwid.Pile([urwid.Padding(urwid.BigText(("title", line),
                                                          T.font(size)),
                                             align=plan.align, width="clip")
                               for line in lines])
            body = urwid.Columns([(GUTTER, urwid.Text(bar)), ("weight", 1, body)])
        else:
            markup: list = []
            for i, row in enumerate(plan.rows):
                if i:
                    markup.append((None, "\n"))
                markup.append(bar if i == 0 else (None, " " * GUTTER))
                markup.extend(row)
            body = urwid.Text(markup or [(None, "")], wrap="clip")

        pieces += [urwid.Divider()] * plan.blank_before
        pieces.append(body)
        pieces += [urwid.Divider()] * plan.blank_after
        return urwid.Pile(pieces)

    def _compose_panes(self, plan):
        """Side-by-side boxes -- the edited one is a live Edit in its slot."""
        slots = []
        for i, (width, rows) in enumerate(plan.panes):
            if self.editing and self._pane == i:
                inner = urwid.AttrMap(
                    urwid.Padding(urwid.AttrMap(self._edit, "editing"),
                                  left=HALO, right=HALO), "halo")
                if i:
                    inner = urwid.Columns([(2, urwid.Text(("rule", "│ "))),
                                           ("weight", 1, inner)])
                slots.append((width, inner))
                continue
            markup: list = []
            for j, row in enumerate(rows):
                if j:
                    markup.append((None, "\n"))
                markup.extend(row or [(None, "")])
            slots.append((width, urwid.Text(markup or [(None, "")], wrap="clip")))
        return urwid.Columns([(w, widget) for w, widget in slots])

    def content_rows(self, maxcol: int) -> tuple:
        """(first, last) rows this note's own text occupies.

        The blank lines around a note belong to the *document's* spacing, not
        to the note, so a click there is a click on the page.
        """
        if self.editing:
            return 0, max(0, self.rows((maxcol,)) - 1)
        plan = self.layout(maxcol)
        total = self.rows((maxcol,))
        first = plan.blank_before
        last = total - plan.blank_after - 1
        return first, max(first, last)

    def pane_at(self, maxcol: int, col: int):
        """Which pane a click landed in, if any."""
        plan = self.layout(maxcol)
        if not plan.panes:
            return None
        at = GUTTER + plan.indent
        for i, (width, _rows) in enumerate(plan.panes):
            if col < at + width:
                return i
            at += width
        return len(plan.panes) - 1

    # --- urwid plumbing ---------------------------------------------------
    def render(self, size, focus: bool = False):
        (maxcol,) = size
        return urwid.CompositeCanvas(
            self._compose(maxcol, focus).render((maxcol,), focus))

    def rows(self, size, focus: bool = False) -> int:
        (maxcol,) = size
        return self._compose(maxcol, focus).rows((maxcol,), focus)

    def get_cursor_coords(self, size):
        (maxcol,) = size
        widget = self._compose(maxcol, True)
        if self.editing and hasattr(widget, "get_cursor_coords"):
            return widget.get_cursor_coords((maxcol,))
        return None

    # --- edit mode --------------------------------------------------------
    def start_pane_edit(self, index: int, *, at_end: bool = True) -> None:
        """Edit one pane in place, leaving its neighbours on screen."""
        parts = S.panes(self.note.text)
        if not 0 <= index < len(parts):
            return
        self.stop_edit()
        body = parts[index][1]
        self._edit = Field("", body, multiline=True, wrap="space")
        self._edit.edit_pos = len(body) if at_end else 0
        self._pane = index
        self.editing = True
        self._built = None
        self._invalidate()

    def panes(self) -> list:
        return S.panes(self.note.text)

    def start_edit(self, *, at_end: bool = True) -> None:
        if self.editing:
            return
        self._edit = Field("✎ ", self.note.text, multiline=True, wrap="space")
        # Starting at the front means "after the marker" -- you want to type
        # the item, not in front of its bullet.
        self._edit.edit_pos = (len(self.note.text) if at_end
                               else len(S.marker_of(self.note.text)))
        self.editing = True
        self._built = None
        self._invalidate()

    def stop_edit(self, *, keep: bool = True) -> None:
        if not self.editing:
            return
        typed = (self._edit.edit_text if self._edit else "").rstrip()
        if self._pane is not None:
            parts = S.panes(self.note.text)
            weight = parts[self._pane][0]
            parts[self._pane] = (weight, typed if keep else parts[self._pane][1])
            text = (S.repane(parts) if any(body.strip() for _w, body in parts)
                    else "")
        else:
            text = typed if self._edit else self.note.text.rstrip()
        self.editing = False
        self._pane = None
        self._edit = None
        self._built = None
        self._invalidate()
        if keep and text.strip():
            if text != self.note.text:
                self.note.text = text
                self.note.fmt = {}        # re-format this line from scratch
                self.note.emphasis = ""
                self.note.tag = ""
            self._emit("changed")
        elif not text.strip():
            self._emit("removed")

    def keypress(self, size, key: str):
        (maxcol,) = size
        if key == "esc":
            return key              # up a level: the app's to answer, not ours
        if self.editing:
            if key in ("tab", "shift tab") and self._pane is not None:
                step = 1 if key == "tab" else -1
                count = len(S.panes(self.note.text))
                target = (self._pane + step) % count
                self.stop_edit()
                self.start_pane_edit(target)
                return None
            if key in ("enter", "shift enter") and self._pane is not None:
                self.stop_edit()
                self._emit("changed")
                self._emit("leave")
                return None
            if key == "enter":
                self.insert_break()     # a new line, not a new note
                return None
            if key in ("up", "down") and self._pane is None:
                inner = self._compose(maxcol, True)
                if inner.keypress((maxcol,), key) is None:
                    return None         # moved within the note's own lines
                self.stop_edit()        # off the end: step to the next note
                self._emit("step", -1 if key == "up" else 1)
                return None
            if key in ("f1", "meta enter"):
                self.insert_break()      # ...the ⏎ button's key
                return None
            if key in ("f12", "shift enter"):
                return self.press("done") and None
            if self._edit.selection() and key in ("backspace", "delete"):
                return self._compose(maxcol, True).keypress((maxcol,), key)
            if key == "backspace" and self._edit.edit_pos == 0 and self._pane:
                return None            # do not eat the pane's neighbour
            if key == "backspace" and self._edit.edit_pos == 0 and self._pane is None:
                self._emit("join_up")       # ...and two become one again
                return None
            if (key == "delete" and self._pane is None
                    and self._edit.edit_pos >= len(self._edit.edit_text)):
                self._emit("join_down")
                return None
            return self._compose(maxcol, True).keypress((maxcol,), key)

        if key == "enter":
            self.start_edit()
            return None
        block = self.block
        if key in (" ", "shift enter") and block is not None and block.kind == S.CHECK:
            self.note.done = not self.note.done
            self._built = None
            self._invalidate()
            self._emit("changed")
            return None
        if key in ("delete", "backspace"):
            self._emit("removed")
            return None
        if len(key) == 1 and key.isprintable():
            self.start_edit()
            self._edit.insert_text(key)
            self._built = None
            return None
        return key

    def _click_in_halo(self, maxcol, event, button, col, row) -> bool:
        """A click anywhere in the blue block lands somewhere sensible.

        The halo is part of the target: clicking it puts the cursor at the
        nearest point in the text rather than doing nothing. The press also
        drops an anchor, so dragging from here selects.
        """
        if row >= self.rows((maxcol,)) - 1:
            for name, (first, last) in self.buttons(maxcol).items():
                if first <= col <= last:
                    return self.press(name)
        self.point_at(maxcol, col, row)
        self._edit.anchor = self._edit.edit_pos
        return True

    def point_at(self, maxcol: int, col: int, row: int) -> bool:
        """Put the cursor under (col, row), clamped into the text."""
        left, width = self.halo_box(maxcol)
        inner_left = left + HALO
        inner_width = max(1, width - 2 * HALO)
        text_rows = max(1, self._edit.rows((inner_width,)))
        x = min(max(col - inner_left, 0), inner_width - 1)
        y = min(max(row - HALO, 0), text_rows - 1)
        self._edit.move_cursor_to_coords((inner_width,), x, y)
        self._built = None
        self._invalidate()
        return True

    def drag_to(self, maxcol: int, col: int, row: int) -> bool:
        """Extend the selection to (col, row) -- the mouse is still down."""
        if self._edit.anchor is None:
            self._edit.anchor = self._edit.edit_pos
        return self.point_at(maxcol, col, row)

    def press(self, name: str) -> bool:
        """One of the buttons along the bottom of an open box."""
        if name == "break":
            self.insert_break()
        elif name == "done":
            self.stop_edit()
            self._emit("leave")
        elif name == "drop":
            self.stop_edit(keep=False)
            self._emit("leave")
        return True

    def split(self) -> None:
        """Cut the note at the cursor; the tail becomes the next note."""
        if not self.editing:
            return
        text = self._edit.edit_text
        at = self._edit.edit_pos
        head, tail = text[:at].rstrip(), text[at:].strip()
        marker = S.marker_of(text)
        if marker and not S.classify(tail).explicit:
            tail = marker + tail       # the tail keeps the list it was part of
        self.editing = False
        self._edit = None
        self._built = None
        self._invalidate()
        if head.strip():
            self.note.text = head
            self.note.fmt = {}
            self.note.emphasis = ""
            self.note.tag = ""
            self._emit("changed")
            self._emit("split", tail)
        else:
            self.note.text = tail
            self._emit("changed")
            self.start_edit(at_end=False)

    def split_across(self) -> None:
        """Split this box horizontally: one row of panes instead of one box."""
        parts = S.panes(self.note.text)
        if self.editing and self._pane is not None:
            at = self._edit.edit_pos
            body = self._edit.edit_text
            weight = parts[self._pane][0]
            parts[self._pane:self._pane + 1] = [
                (weight, body[:at].strip()), (1.0, body[at:].strip())]
        elif self.editing:
            at = self._edit.edit_pos
            body = self._edit.edit_text
            parts = [(1.0, body[:at].strip()), (1.0, body[at:].strip())]
        else:
            # Not editing: halve the last pane at a word boundary.
            weight, body = parts[-1]
            words = body.split()
            if len(words) < 2:
                parts = parts + [(1.0, "")]
            else:
                half = len(words) // 2
                parts[-1:] = [(weight, " ".join(words[:half])),
                              (1.0, " ".join(words[half:]))]
        self.editing = False
        self._pane = None
        self._edit = None
        self.note.text = S.repane(parts)
        self.note.fmt = {}
        self._built = None
        self._invalidate()
        self._emit("changed")

    def unsplit_across(self) -> None:
        """Fold a row of panes back into one box."""
        if S.PANE_SEP not in self.note.text:
            return
        self.editing = False
        self._pane = None
        self._edit = None
        self.note.text = S.unpane(self.note.text)
        self.note.fmt = {}
        self._built = None
        self._invalidate()
        self._emit("changed")

    def edit_position(self) -> int:
        return self._edit.edit_pos if self._edit else 0

    def mouse_event(self, size, event, button, col, row, focus):
        (maxcol,) = size
        editing_text = self.editing and self._pane is None
        # Dragging with the button down selects, but only inside a note that
        # is already open: elsewhere a drag is just the mouse moving.
        if event == "mouse drag" and editing_text:
            return self.drag_to(maxcol, col, row)
        if urwid.util.is_mouse_press(event) and button == 1 and editing_text:
            return self._click_in_halo(maxcol, event, button, col, row)
        if urwid.util.is_mouse_press(event) and button == 1:
            first, last = self.content_rows(maxcol)
            if not first <= row <= last:
                return False        # the page around the note, not the note
            row -= first
            pane = self.pane_at(maxcol, col)
            if pane is not None and (not self.editing or self._pane != pane):
                self.start_pane_edit(pane)
                widget = self._compose(maxcol, True)
                if hasattr(widget, "mouse_event"):
                    widget.mouse_event((maxcol,), event, button, col,
                                       min(row, max(0, widget.rows((maxcol,)) - 1)),
                                       True)
                return True
            if not self.editing:
                self.start_edit()
                # The click that opened the box also places the cursor: the
                # display had no halo, so shift the row into the open box.
                return self._click_in_halo(maxcol, event, button, col,
                                           row + HALO)
            widget = self._compose(maxcol, True)
            return bool(widget.mouse_event((maxcol,), event, button, col, row, True))
        return False


class Composer(Field):
    """The box at the bottom. Sentences leave it on their own."""

    signals = [*urwid.Edit.signals, "commit", "typed", "sink"]

    def __init__(self) -> None:
        super().__init__(("prompt", "▌ "), "", multiline=False, wrap="space")

    def keypress(self, size, key: str):
        if key == "enter":
            self.flush()
            return None
        if key in ("up", "page up") and not self.edit_text:
            self._emit("sink")
            return None
        result = super().keypress(size, key)
        if result is None:
            self._emit("typed")
            if S.should_commit(self.edit_text):
                self.flush()
        return result

    def flush(self) -> None:
        """File whatever is in the box, one note per sentence.

        Leading spaces are kept: that is how you nest a note by hand.
        """
        text = self.edit_text.rstrip()
        self.set_edit_text("")
        if text:
            for piece in S.split_sentences(text) or [text]:
                self._emit("commit", piece)


class Library(urwid.WidgetWrap):
    """The open dialog: the notebooks in the folder, and a way to start one."""

    signals = ["chosen", "closed"]

    def __init__(self, directory, current=None) -> None:
        self.directory = Path(directory)
        self.paths = store.notebooks(self.directory)
        self.current = Path(current) if current else None

        rows = [urwid.AttrMap(_Shelf(path, path == self.current),
                              "dialog_item", "dialog_focus")
                for path in self.paths]
        if not rows:
            rows = [urwid.AttrMap(urwid.Text("  (no notebooks yet)"), "dialog")]
        self.listing = urwid.ListBox(urwid.SimpleFocusListWalker(rows))
        if self.current in self.paths:      # open on the notebook you are in
            self.listing.set_focus(self.paths.index(self.current))
        self.naming = urwid.Edit(("dialog_title", "  new: "), "")
        height = max(1, min(len(rows), 12))
        self.body = urwid.Pile([
            urwid.BoxAdapter(self.listing, height),
            urwid.AttrMap(urwid.Divider("─"), "rule"),
            urwid.AttrMap(self.naming, "dialog"),
        ])
        shown = str(self.directory).replace(str(Path.home()), "~")
        if len(shown) > 34:
            shown = ".../" + "/".join(self.directory.parts[-2:])
        frame = urwid.LineBox(urwid.Padding(self.body, left=1, right=1),
                              title=shown)
        super().__init__(urwid.AttrMap(frame, "dialog"))

    def selected(self):
        widget = self.listing.focus
        shelf = widget.base_widget if widget else None
        return getattr(shelf, "path", None)

    def keypress(self, size, key):
        if key == "esc":
            return key              # up a level -- the app closes the dialog
        if key == "f2":
            self._emit("closed")    # ...f2 is a toggle, not a rung
            return None
        if key == "enter":
            typed = self.naming.edit_text.strip()
            naming = self.body.focus_position == 2
            if naming and not typed:
                self.body.focus_position = 0      # nothing typed: back to the list
                return None
            if typed and (naming or self.selected() is None):
                self._emit("chosen", store.path_for(typed, self.directory))
                return None
            chosen = self.selected()
            if chosen is not None:
                self._emit("chosen", chosen)
            return None
        return super().keypress(size, key)

    def mouse_event(self, size, event, button, col, row, focus):
        handled = super().mouse_event(size, event, button, col, row, focus)
        if urwid.util.is_mouse_press(event) and button == 1:
            chosen = self.selected()
            if chosen is not None and row <= len(self.paths) + 1:
                self._emit("chosen", chosen)
                return True
        return handled


class _Shelf(urwid.WidgetWrap):
    """One notebook in the open dialog: name, size, when it was last written."""

    _selectable = True

    def __init__(self, path: Path, current: bool = False) -> None:
        self.path = path
        notes = store.load(path)
        when = time.localtime(path.stat().st_mtime)
        today = time.localtime()
        stamp = (time.strftime("%H:%M", when)
                 if when[:3] == today[:3] else time.strftime("%d %b", when))
        title = ("▸ " if current else "  ") + store.title_of(path)
        count = f"{len(notes)} note{'' if len(notes) == 1 else 's'}"
        super().__init__(urwid.Columns([
            ("weight", 3, urwid.Text(title, wrap="clip")),
            ("weight", 1, urwid.Text(count, align="right")),
            (8, urwid.Text(stamp, align="right")),
        ], dividechars=1))

    def selectable(self) -> bool:
        return True

    def keypress(self, size, key):
        return key
