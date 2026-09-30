"""The escape principle: esc always takes you up the tree.

The UI is a tree whether we like it or not, so it is written down as one:

    0  shelf      which book       (the reader only -- see test_shelf.py)
    1  root       the folder of notebooks (the reader: one book's contents)
    2  composer   the box at the bottom
    3  page       a note has the cursor bar; arrows scroll
    4  editing    an open box -- the halo, or one of its panes

esc is one step up, from wherever you are. No widget decides what "up"
means from where it sits: they hand the key back and the app, which is the
only thing that knows the whole tree, moves the cursor.

A tree can be taller in one app than another: plain inkwell tops out at
ROOT, the reader has the shelf above it. Same ladder either way, which is
the point -- tests/test_shelf.py walks all five rungs.
"""

import tempfile
import unittest
from pathlib import Path

from .helpers import retype  # noqa: F401
from inkwell import store
from inkwell.app import COMPOSER, EDITING, PAGE, ROOT, Inkwell
from inkwell.document import Document
from inkwell.widgets import Composer, Library, NoteWidget

SIZE = (70, 18)


def lone(text):
    """One note in a one-note document, with no app above it."""
    item = store.Note(text)
    doc = Document()
    doc.rebuild([item])
    return NoteWidget(item, doc)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "notes.json"
        store.save([store.Note("# A notebook"),
                    store.Note("- first item"),
                    store.Note("- second item"),
                    store.Note("a plain paragraph.")], self.tmp)
        self.app = Inkwell(self.tmp, use_llm=False)
        self.app.frame.render(SIZE, True)

    def esc(self):
        """What the real key does: nobody claims it, so the app gets it."""
        return self.app.unhandled("esc")

    def at(self, index: int):
        """Stand on a note in the page (level 2)."""
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(index)
        self.app.frame.render(SIZE, True)
        return self.app._notes[index]


class LadderTests(Fixture):
    """The path, exactly as it was asked for."""

    def test_the_whole_way_up_from_the_deepest_place(self):
        self.at(2).start_edit()
        self.assertEqual(self.app.depth(), EDITING)

        self.esc()
        self.assertEqual(self.app.depth(), PAGE)
        self.assertFalse(any(w.editing for w in self.app._notes))
        self.assertIs(self.app.listbox.focus, self.app._notes[2],
                      "the note you were in keeps the cursor")

        self.esc()
        self.assertEqual(self.app.depth(), COMPOSER)
        self.assertEqual(self.app.frame.focus_position, "footer")

        self.esc()
        self.assertEqual(self.app.depth(), ROOT)
        self.assertIsNotNone(self.app.library)

    def test_esc_never_takes_you_deeper(self):
        """The invariant, from every rung: esc strictly ascends."""
        self.at(1).start_edit()
        for _ in range(3):
            before = self.app.depth()
            self.esc()
            self.assertLess(self.app.depth(), before,
                            f"esc did not ascend from level {before}")
        self.assertEqual(self.app.depth(), ROOT)

    def test_the_root_has_no_parent_so_it_steps_aside(self):
        self.app.frame.focus_position = "footer"
        self.esc()
        self.assertEqual(self.app.depth(), ROOT)
        self.esc()
        self.assertIsNone(self.app.library)
        self.assertEqual(self.app.depth(), COMPOSER,
                         "back to the level the root covered, not deeper")

    def test_the_root_puts_you_back_in_the_page_if_that_is_where_you_were(self):
        self.at(2)
        self.app.open_root()
        self.assertEqual(self.app.depth(), ROOT)
        self.esc()
        self.assertEqual(self.app.depth(), PAGE)

    def test_f2_out_and_back_lands_on_the_level_it_left(self):
        """f2 is the other way to the root, so it uses the same memory."""
        for level, arrange in ((COMPOSER, self.app.to_composer),
                               (PAGE, lambda: self.at(1))):
            arrange()
            self.assertEqual(self.app.depth(), level)
            self.app.unhandled("f2")
            self.assertEqual(self.app.depth(), ROOT)
            self.app.unhandled("f2")
            self.assertEqual(self.app.depth(), level)

    def test_opening_the_root_from_an_open_box_never_puts_you_back_in_it(self):
        """f2 out of a note closes it: esc must not re-open an edit box."""
        widget = self.at(3)
        widget.start_edit()
        self.app.open_root()
        self.assertFalse(widget.editing, "f2 out of a note closes the note")
        self.esc()
        self.assertEqual(self.app.depth(), PAGE)

    def test_with_no_notes_the_composer_is_the_only_rung_below_the_root(self):
        app = Inkwell(None, use_llm=False)
        self.assertEqual(app.depth(), COMPOSER)
        app.unhandled("esc")
        self.assertEqual(app.depth(), ROOT)
        app.unhandled("esc")
        self.assertEqual(app.depth(), COMPOSER)


class KeepingTests(Fixture):
    """Going up keeps your work. Throwing it away is the ✕ button's job."""

    def test_esc_out_of_an_open_box_keeps_what_it_says(self):
        widget = self.at(3)
        widget.start_edit()
        retype(widget, "rewritten on the way out")
        self.esc()
        self.assertFalse(widget.editing)
        self.assertEqual(widget.note.text, "rewritten on the way out")

    def test_esc_out_of_a_pane_keeps_what_it_says(self):
        widget = self.at(3)
        widget.note.text = "left pane || right pane"
        widget._built = None
        self.app.reformat()
        widget.start_pane_edit(1)
        retype(widget, "rewritten")
        self.esc()
        self.assertFalse(widget.editing)
        self.assertEqual(widget.note.text, "left pane || rewritten")

    def test_an_empty_box_still_goes_away_on_the_way_up(self):
        widget = self.at(1)
        widget.start_edit()
        retype(widget, "")
        self.esc()
        self.assertNotIn(widget, self.app._notes)
        self.assertEqual(self.app.depth(), PAGE)


class DecorationTests(Fixture):
    """A pick, a selection, a filter: attributes of a level, not levels.

    They do not earn a rung of their own -- they go when you leave the
    level they belong to, so the ladder stays four deep.
    """

    def test_esc_in_the_page_drops_a_picked_run_and_still_ascends(self):
        self.at(1)
        self.app.unhandled("shift down")
        self.assertEqual(len(self.app.picked()), 2)
        self.esc()
        self.assertEqual(self.app.picked(), [])
        self.assertEqual(self.app.depth(), COMPOSER)

    def test_a_selection_inside_a_box_does_not_cost_a_rung(self):
        widget = self.at(2)
        widget.start_edit()
        widget._edit.select_all()
        self.esc()
        self.assertEqual(self.app.depth(), PAGE)


class HandingBackTests(unittest.TestCase):
    """No widget interprets esc. They pass it up; the app owns the tree."""

    def test_a_note_hands_esc_back(self):
        widget = lone("hello")
        self.assertEqual(widget.keypress((60,), "esc"), "esc")
        widget.start_edit()
        self.assertEqual(widget.keypress((60,), "esc"), "esc")
        self.assertTrue(widget.editing, "the widget did not decide by itself")

    def test_the_composer_hands_esc_back(self):
        box = Composer()
        self.assertEqual(box.keypress((40,), "esc"), "esc")

    def test_the_folder_dialog_hands_esc_back(self):
        folder = Path(tempfile.mkdtemp())
        store.save([store.Note("# One")], folder / "one.json")
        dialog = Library(folder)
        self.assertEqual(dialog.keypress((54,), "esc"), "esc")

    def test_f2_still_closes_the_folder_dialog_itself(self):
        """f2 is a toggle, not a rung: the dialog keeps that one."""
        folder = Path(tempfile.mkdtemp())
        store.save([store.Note("# One")], folder / "one.json")
        dialog = Library(folder)
        closed = []
        import urwid
        urwid.connect_signal(dialog, "closed", lambda _w: closed.append(True))
        dialog.keypress((54,), "f2")
        self.assertEqual(closed, [True])


class RealKeyTests(Fixture):
    """The key really does reach the ladder, through every widget above it."""

    def test_esc_comes_back_out_of_the_frame_unclaimed(self):
        self.at(2).start_edit()
        self.app.frame.render(SIZE, True)
        self.assertEqual(self.app.frame.keypress(SIZE, "esc"), "esc")

    def test_esc_comes_back_out_of_the_root_overlay_unclaimed(self):
        import urwid
        self.app.open_root()
        overlay = urwid.Overlay(self.app.library, self.app.frame,
                                align="center", width=("relative", 66),
                                min_width=46, valign="middle", height="pack")
        self.assertEqual(overlay.keypress(SIZE, "esc"), "esc")


class ReaderTests(unittest.TestCase):
    """The reader is the same ladder: its root is the contents, not a folder."""

    def setUp(self):
        from .test_reader import make_book
        from inkwell import reader
        self.folder = make_book(Path(tempfile.mkdtemp()))
        self.app = reader.Reader(self.folder / "iar-00-preface.json",
                                 theme="dark")
        self.app.frame.render(SIZE, True)

    def test_esc_from_the_composer_opens_the_contents(self):
        self.assertEqual(self.app.depth(), COMPOSER)
        self.app.unhandled("esc")
        self.assertEqual(self.app.depth(), ROOT)
        self.assertIsNotNone(self.app.menu)
        self.assertIsNone(self.app.library, "the folder is not the reader's root")

    def test_esc_closes_the_contents_back_to_where_it_came_from(self):
        self.app.unhandled("esc")
        self.app.unhandled("esc")
        self.assertIsNone(self.app.menu)
        self.assertEqual(self.app.depth(), COMPOSER)

    def test_the_whole_ladder_in_the_reader(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(1)
        self.app.frame.render(SIZE, True)
        self.app.listbox.focus.start_edit()
        for expected in (PAGE, COMPOSER, ROOT):
            self.app.unhandled("esc")
            self.assertEqual(self.app.depth(), expected)

    def test_the_contents_menu_hands_esc_back(self):
        from inkwell import reader
        menu = reader.Menu(reader.contents(self.folder, "iar"))
        self.assertEqual(menu.keypress((70, 20), "esc"), "esc")

    def test_a_typed_filter_does_not_cost_a_rung(self):
        self.app.unhandled("esc")
        for character in "kine":
            self.app.menu.keypress((70, 20), character)
        self.assertEqual(self.app.menu.query, "kine")
        self.app.unhandled("esc")
        self.assertIsNone(self.app.menu, "esc leaves the level, filter and all")


if __name__ == "__main__":
    unittest.main()
