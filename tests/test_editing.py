"""Breaking one box into two, and joining two back into one.

Enter puts in a line break. A *blank* line -- Enter twice -- is where one
note becomes two, when the note is filed.
"""

import unittest

from .helpers import retype  # noqa: F401
from inkwell import shaping as S
from inkwell.app import Inkwell


class Fixture(unittest.TestCase):
    def setUp(self):
        self.app = Inkwell(None, use_llm=False)

    def texts(self):
        return [w.note.text for w in self.app._notes]

    def focus(self, index):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(index)
        return self.app._notes[index]

    def open_at(self, index, at):
        widget = self.focus(index)
        widget.start_edit()
        widget._edit.edit_pos = at
        return widget

    def finish(self, widget):
        widget.keypress((80,), "f12")


class BreakTests(Fixture):
    def test_enter_puts_in_a_line_break(self):
        self.app.commit("first line")
        widget = self.open_at(0, len("first line"))
        widget.keypress((80,), "enter")
        for character in "second line":
            widget.keypress((80,), character)
        self.assertTrue(widget.editing, "still the same note")
        self.assertEqual(widget._edit.edit_text, "first line\nsecond line")
        self.finish(widget)
        self.assertEqual(self.texts(), ["first line\nsecond line"])

    def test_a_blank_line_is_where_one_note_becomes_two(self):
        self.app.commit("first thought.")
        widget = self.open_at(0, len("first thought."))
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "second thought.":
            widget.keypress((80,), character)
        self.finish(widget)
        self.assertEqual(self.texts(), ["first thought.", "second thought."])

    def test_a_new_block_in_a_list_stays_in_the_list(self):
        self.app.commit("- perforated alu")
        widget = self.open_at(0, len("- perforated alu"))
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "22ga CRS":
            widget.keypress((80,), character)
        self.finish(widget)
        self.assertEqual(self.texts(), ["- perforated alu", "- 22ga CRS"])

    def test_a_numbered_list_carries_on_counting(self):
        self.app.commit("1. cut the plate")
        widget = self.open_at(0, len("1. cut the plate"))
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "bend it":
            widget.keypress((80,), character)
        self.finish(widget)
        rows = [self.app.doc.plan(w.note, 80).rows[0] for w in self.app._notes]
        marks = ["".join(t for _a, t in row).strip()[:2] for row in rows]
        self.assertEqual(marks, ["1.", "2."])

    def test_a_nested_item_keeps_its_depth(self):
        self.app.commit("  - one in")
        widget = self.open_at(0, len("  - one in"))
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "and another":
            widget.keypress((80,), character)
        self.finish(widget)
        self.assertEqual(self.app.doc.block_for(self.app._notes[1].note).level, 1)

    def test_the_new_block_is_formatted_from_scratch(self):
        self.app.commit("prose the model formatted, twice over.")
        self.app._notes[0].note.tag = "old"
        self.app._notes[0].note.fmt = {"block": S.CHECK}
        widget = self.open_at(0, len("prose the model formatted,"))
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "more":
            widget.keypress((80,), character)
        self.finish(widget)
        self.assertEqual(self.app._notes[0].note.fmt, {})
        self.assertEqual(self.app._notes[0].note.tag, "")

    def test_escape_keeps_what_you_typed(self):
        self.app.commit("a note")
        widget = self.open_at(0, len("a note"))
        for character in " and more":
            widget.keypress((80,), character)
        widget.keypress((80,), "esc")
        self.assertEqual(self.texts(), ["a note and more"])

    def test_the_discard_button_throws_it_away(self):
        self.app.commit("a note")
        widget = self.open_at(0, len("a note"))
        widget.render((80,), True)
        for character in " and more":
            widget.keypress((80,), character)
        first, _last = widget.buttons(80)["drop"]
        widget.mouse_event((80,), "mouse press", 1, first,
                           widget.rows((80,)) - 1, True)
        self.assertEqual(self.texts(), ["a note"])
        self.assertFalse(widget.editing)


class JoinTests(Fixture):
    def test_backspace_at_the_start_joins_with_the_note_above(self):
        self.app.commit("first half")
        self.app.commit("second half")
        self.open_at(1, 0).keypress((80,), "backspace")
        self.assertEqual(self.texts(), ["first half second half"])

    def test_the_cursor_lands_on_the_seam(self):
        self.app.commit("first half")
        self.app.commit("second half")
        self.open_at(1, 0).keypress((80,), "backspace")
        above = self.app._notes[0]
        self.assertTrue(above.editing)
        self.assertEqual(above.edit_position(), len("first half"))

    def test_joining_drops_the_second_marker(self):
        self.app.commit("- one")
        self.app.commit("- two")
        self.open_at(1, 0).keypress((80,), "backspace")
        self.assertEqual(self.texts(), ["- one two"])

    def test_backspace_at_the_top_of_the_page_does_nothing(self):
        self.app.commit("only note")
        widget = self.open_at(0, 0)
        widget.keypress((80,), "backspace")
        self.assertEqual(self.texts(), ["only note"])

    def test_delete_at_the_end_pulls_the_next_note_up(self):
        self.app.commit("first half")
        self.app.commit("second half")
        widget = self.open_at(0, len("first half"))
        widget.keypress((80,), "delete")
        self.assertEqual(self.texts(), ["first half second half"])
        self.assertTrue(widget.editing)
        self.assertEqual(widget.edit_position(), len("first half"))

    def test_delete_at_the_end_of_the_last_note_does_nothing(self):
        self.app.commit("only note")
        widget = self.open_at(0, len("only note"))
        widget.keypress((80,), "delete")
        self.assertEqual(self.texts(), ["only note"])

    def test_f6_joins_the_focused_note_upwards_without_editing(self):
        self.app.commit("first half")
        self.app.commit("second half")
        self.focus(1)
        self.app.unhandled("f6")
        self.assertEqual(self.texts(), ["first half second half"])

    def test_a_join_survives_a_round_trip_through_the_formatter(self):
        self.app.commit("- one")
        self.app.commit("- two")
        self.focus(1)
        self.app.unhandled("f6")
        block = self.app.doc.block_for(self.app._notes[0].note)
        self.assertEqual(block.kind, S.ITEM)

    def test_breaking_then_joining_gets_you_back_where_you_started(self):
        self.app.commit("a sentence")
        widget = self.open_at(0, len("a sentence"))
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "with several words":
            widget.keypress((80,), character)
        self.finish(widget)
        self.assertEqual(len(self.app._notes), 2)
        self.focus(1)
        self.app.unhandled("f6")
        self.assertEqual(self.texts(), ["a sentence with several words"])


if __name__ == "__main__":
    unittest.main()
