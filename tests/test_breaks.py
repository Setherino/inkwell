"""Line breaks inside a note, and the buttons along the bottom of an open box."""

import json
import tempfile
import unittest
from pathlib import Path

from .helpers import lines, retype  # noqa: F401
from inkwell import shaping as S
from inkwell import store
from inkwell.app import Inkwell
from inkwell.document import Document
from inkwell.widgets import BUTTONS_AT, VIEW, NoteWidget


def rows(text, cols=60):
    note = store.Note(text)
    doc = Document()
    doc.rebuild([note])
    return ["".join(t for _a, t in row).rstrip()
            for row in doc.plan(note, cols).rows]


class ShapeTests(unittest.TestCase):
    def test_the_first_line_still_decides_what_the_note_is(self):
        self.assertEqual(S.classify("- an item\nand more of it").kind, S.ITEM)
        self.assertEqual(S.classify("## A section\nwith a second line").kind,
                         S.SECTION)
        self.assertEqual(S.classify("TODO a task\nwith detail").kind, S.CHECK)

    def test_the_marker_is_stripped_but_the_break_is_kept(self):
        shape = S.classify("- an item\nand more of it")
        self.assertEqual(shape.text, "an item\nand more of it")

    def test_one_line_markup_gives_way_to_prose(self):
        # "key: value" over two lines is not a table row any more.
        self.assertEqual(S.classify("fin pitch: 0.4mm\nmeasured cold").kind,
                         S.PARA)
        self.assertEqual(S.classify("a | b | c\nsecond line").kind, S.PARA)


class RenderTests(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows, VIEW.unicode_ok, VIEW.big = 60, 40, True, True

    def test_a_break_becomes_a_new_row(self):
        self.assertEqual(rows("first line\nsecond line"),
                         ["first line", "second line"])

    def test_a_broken_list_item_hangs_under_its_text(self):
        painted = rows("- perforated aluminium\nand 22ga CRS")
        self.assertEqual(painted[0], "• perforated aluminium")
        self.assertEqual(painted[1], "  and 22ga CRS")

    def test_a_blank_line_inside_a_note_is_kept(self):
        self.assertEqual(rows("above\n\nbelow"), ["above", "", "below"])

    def test_a_quotation_keeps_its_bar_on_every_line(self):
        painted = rows("> a quotation\nbroken here")
        self.assertTrue(all(line.startswith("│") for line in painted), painted)

    def test_a_callout_keeps_its_bar_too(self):
        painted = rows("!careful\nvery careful")
        self.assertTrue(all(line.startswith("▍") for line in painted), painted)

    def test_each_piece_wraps_on_its_own(self):
        painted = rows("short\n" + "word " * 30, cols=40)
        self.assertEqual(painted[0], "short")
        self.assertGreater(len(painted), 3)
        for line in painted:
            self.assertLessEqual(len(line), 40)

    def test_breaks_survive_a_trip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            store.save([store.Note("one\ntwo")], path)
            self.assertIn("\\n", path.read_text())
            self.assertEqual(store.load(path)[0].text, "one\ntwo")


class ButtonTests(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows = 70, 40
        self.app = Inkwell(None, use_llm=False)
        self.app.commit("perforated aluminium and 22ga CRS as the fallback")
        self.widget = self.app._notes[0]
        self.widget.start_edit()
        self.widget._edit.edit_pos = len("perforated aluminium")

    def press(self, name, cols=70):
        first, _last = self.widget.buttons(cols)[name]
        row = self.widget.rows((cols,)) - 1
        self.widget.mouse_event((cols,), "mouse press", 1, first, row, True)

    def test_the_strip_sits_at_the_bottom_right_of_the_open_box(self):
        spans = self.widget.buttons(70)
        self.assertEqual(list(spans), ["break", "done", "drop"])
        self.assertLess(spans["break"][0], spans["done"][0])
        self.assertLessEqual(spans["drop"][1], 69)
        painted = lines(self.widget.render((70,), True))
        self.assertIn("⏎", painted[-1])
        self.assertIn("✓", painted[-1])

    def test_clicking_the_break_button_inserts_a_newline_at_the_cursor(self):
        self.press("break")
        self.assertEqual(self.widget._edit.edit_text,
                         "perforated aluminium\n and 22ga CRS as the fallback")
        self.assertTrue(self.widget.editing, "still open, ready to keep typing")

    def test_f1_does_the_same_thing(self):
        self.widget.keypress((70,), "f1")
        self.assertIn("\n", self.widget._edit.edit_text)

    def test_typing_after_a_break_keeps_the_break(self):
        """A click leaves a selection anchor; inserting must settle it.

        Otherwise the anchor sits just behind the new line break and the
        next character typed swallows it -- which looks exactly like line
        breaks not working at all.
        """
        self.widget.render((70,), True)
        self.widget.mouse_event((70,), "mouse press", 1, 10, 1, True)
        self.widget.keypress((70,), "f1")
        self.assertIsNone(self.widget._edit.anchor)
        for character in "xyz":
            self.widget.keypress((70,), character)
        self.assertIn("\nxyz", self.widget._edit.edit_text)

    def test_the_break_button_survives_typing_too(self):
        self.widget.render((70,), True)
        self.widget.mouse_event((70,), "mouse press", 1, 10, 1, True)
        first, _last = self.widget.buttons(70)["break"]
        self.widget.mouse_event((70,), "mouse press", 1, first,
                                self.widget.rows((70,)) - 1, True)
        self.widget.keypress((70,), "z")
        self.assertIn("\nz", self.widget._edit.edit_text)

    def test_pasting_settles_the_selection_too(self):
        from inkwell import clip
        was = clip.COPY, clip.PASTE
        clip.COPY, clip.PASTE = ["no-such-command"], ["no-such-command"]
        try:
            clip.copy("pasted")
            self.widget.render((70,), True)
            self.widget.mouse_event((70,), "mouse press", 1, 10, 1, True)
            self.widget.keypress((70,), "ctrl v")
            self.widget.keypress((70,), "!")
            self.assertIn("pasted!", self.widget._edit.edit_text)
        finally:
            clip.COPY, clip.PASTE = was

    def test_the_done_button_files_a_multi_line_note_as_one_note(self):
        self.press("break")
        self.press("done")
        self.assertEqual(len(self.app._notes), 1)
        self.assertIn("\n", self.widget.note.text)
        self.assertFalse(self.widget.editing)

    def test_f12_is_the_done_key(self):
        self.press("break")
        self.widget.keypress((70,), "f12")
        self.assertFalse(self.widget.editing)
        self.assertIn("\n", self.widget.note.text)

    def test_the_discard_button_puts_the_note_back(self):
        before = self.widget.note.text
        retype(self.widget, "something else entirely")
        self.press("drop")
        self.assertEqual(self.widget.note.text, before)

    def test_the_strip_hides_itself_in_a_narrow_box(self):
        self.assertEqual(self.widget.buttons(BUTTONS_AT - 4), {})
        painted = lines(self.widget.render((BUTTONS_AT - 4,), True))
        self.assertNotIn("⏎", "".join(painted))

    def test_clicking_next_to_the_strip_still_moves_the_cursor(self):
        self.widget._edit.edit_pos = 0
        self.widget.mouse_event((70,), "mouse press", 1, 10,
                                self.widget.rows((70,)) - 1, True)
        self.assertGreater(self.widget._edit.edit_pos, 0)

    def test_a_broken_note_still_becomes_two_and_joins_back(self):
        self.press("break")
        self.press("break")                        # a blank line: two blocks
        self.press("done")
        self.assertEqual(len(self.app._notes), 2)
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(1)
        self.app.unhandled("f6")
        self.assertEqual(len(self.app._notes), 1)


if __name__ == "__main__":
    unittest.main()
