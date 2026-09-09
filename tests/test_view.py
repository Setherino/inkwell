"""The page must not move under the reader."""

import tempfile
import unittest
from pathlib import Path

from .helpers import retype  # noqa: F401
from inkwell import store
from inkwell.app import Inkwell

SIZE = (70, 16)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "notes.json"
        store.save([store.Note("# A long notebook")]
                   + [store.Note(f"note number {i:02d} on a long page.")
                      for i in range(1, 31)], self.tmp)
        self.app = Inkwell(self.tmp, use_llm=False)
        self.app.frame.render(SIZE, True)
        self.scroll_to_the_middle()

    def screen(self):
        """What the page says, ignoring the gutter and the status line.

        The focus bar in the gutter marks where you are, which is allowed to
        change; where the page is scrolled to is not.
        """
        rows = [line.decode("utf-8")[2:].rstrip()
                for line in self.app.frame.render(SIZE, True).text]
        return rows[:-2]

    def top(self):
        return next((line for line in self.screen() if line.strip()), "")

    def scroll_to_the_middle(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(15)
        self.app.frame.render(SIZE, True)
        self.app.frame.focus_position = "footer"
        self.anchor = self.screen()

    def assertStill(self, what):
        self.assertEqual(self.screen(), self.anchor, f"the view moved: {what}")


class HoldTests(Fixture):
    def test_the_fixture_really_is_scrolled_up(self):
        self.assertNotIn("note number 30", "\n".join(self.anchor))
        self.assertIn("note number 1", "\n".join(self.anchor))

    def test_leaving_a_note_does_not_jump_to_the_bottom(self):
        widget = self.app.listbox.focus
        widget.start_edit()
        self.app.frame.render(SIZE, True)
        self.app.to_composer()
        self.assertStill("after leaving a note")

    def test_escape_does_not_jump(self):
        widget = self.app.listbox.focus
        widget.start_edit()
        self.app.frame.render(SIZE, True)
        self.app.unhandled("esc")
        self.assertFalse(widget.editing)
        self.assertStill("after escape")

    def test_committing_a_note_while_scrolled_up_leaves_you_where_you_are(self):
        self.app.commit("something typed while reading further up.")
        self.assertStill("after committing a note")

    def test_deleting_a_note_does_not_jump(self):
        self.app.frame.focus_position = "body"
        before = self.top()
        self.app.unhandled("f8")
        self.app.frame.focus_position = "footer"
        self.assertEqual(self.top(), before)

    def test_the_model_answering_does_not_tug_the_page(self):
        note = self.app._notes[20].note
        self.app.muse._out.put((id(note), {"block": "check", "tag": "later"}))
        self.app._absorb()
        self.assertStill("after the copy editor answered")

    def test_flipping_the_theme_does_not_jump(self):
        self.app.set_theme("light")
        self.assertStill("after the theme changed")

    def test_undo_does_not_jump(self):
        self.app.frame.focus_position = "body"
        self.app.unhandled("f8")
        self.app.unhandled("ctrl z")
        self.app.frame.focus_position = "footer"
        self.assertStill("after undo")

    def test_reformatting_does_not_jump(self):
        self.app.reformat()
        self.assertStill("after a reformat")

    def test_a_pane_split_does_not_jump(self):
        self.app.frame.focus_position = "body"
        self.app.unhandled("f4")
        self.app.frame.focus_position = "footer"
        top_after = self.top()
        self.app.unhandled("f3")
        self.assertEqual(self.top(), top_after)


class FollowTests(Fixture):
    """...but typing at the foot of the page still follows along."""

    def go_to_the_end(self):
        self.app.listbox.set_focus(len(self.app._notes) - 1)
        self.app.frame.render(SIZE, True)

    def test_at_the_end_a_new_note_comes_into_view(self):
        self.go_to_the_end()
        self.assertTrue(self.app.at_the_end())
        self.app.commit("the newest thought of all.")
        self.assertIn("the newest thought of all.", "\n".join(self.screen()))

    def test_scrolled_up_it_does_not(self):
        self.assertFalse(self.app.at_the_end())
        self.app.commit("a thought filed while reading the middle.")
        self.assertNotIn("a thought filed while reading",
                         "\n".join(self.screen()))
        self.assertIn("a thought filed while reading the middle.",
                      [w.note.text for w in self.app._notes])


class SpacingClickTests(Fixture):
    """The blank lines between notes belong to the page, not to a note."""

    def widget_rows(self, index):
        row = 0
        for i, widget in enumerate(self.app._notes):
            if i == index:
                return row, widget
            row += widget.rows((SIZE[0],))
        raise AssertionError(index)

    def test_clicking_a_notes_own_text_opens_it(self):
        widget = self.app._notes[3]
        first, _last = widget.content_rows(SIZE[0])
        widget.mouse_event((SIZE[0],), "mouse press", 1, 10, first, True)
        self.assertTrue(widget.editing)

    def test_clicking_the_gap_around_a_note_does_not(self):
        widget = self.app._notes[3]
        first, last = widget.content_rows(SIZE[0])
        for row in range(widget.rows((SIZE[0],))):
            if first <= row <= last:
                continue
            widget.stop_edit(keep=False)
            took = widget.mouse_event((SIZE[0],), "mouse press", 1, 10, row, True)
            self.assertFalse(took, f"row {row} was claimed")
            self.assertFalse(widget.editing, f"row {row} opened the note")


if __name__ == "__main__":
    unittest.main()
