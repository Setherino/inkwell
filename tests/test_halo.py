"""The blue block around an open edit box, and clicking about inside it."""

import unittest

from .helpers import lines  # noqa: F401
from inkwell import store
from inkwell.document import Document
from inkwell.widgets import GUTTER, HALO, VIEW, NoteWidget

SENTENCE = "the plate stack needs to shed 180 watts without a fan at all."


def note(text=SENTENCE):
    item = store.Note(text)
    doc = Document()
    doc.rebuild([item])
    return NoteWidget(item, doc)


def attrs(widget, cols=70, focus=True):
    """The attribute names on each rendered row (bare padding aside)."""
    canvas = widget.render((cols,), focus)
    return [[name for name, _cs, _text in row if name is not None]
            for row in canvas.content()]


class HaloTests(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows, VIEW.unicode_ok, VIEW.big = 70, 40, True, True

    def test_an_open_box_is_wrapped_in_blue(self):
        widget = note()
        widget.start_edit()
        painted = attrs(widget)
        self.assertEqual(set(painted[0]), {"halo"}, "a blue row above")
        # The row below is the same blue, plus the little button strip.
        self.assertLessEqual(set(painted[-1]), {"halo", "halo_button"})
        self.assertEqual(painted[1][0], "halo", "blue to the left")
        self.assertEqual(painted[1][-1], "halo", "blue to the right")
        self.assertIn("editing", painted[1])

    def test_the_halo_is_one_character_wide_on_each_side(self):
        widget = note()
        widget.start_edit()
        runs = [run for run in list(widget.render((70,), True).content())[1]
                if run[0] is not None]
        self.assertEqual(runs[0][0], "halo")
        self.assertEqual(len(runs[0][2].decode()), HALO)
        self.assertEqual(runs[-1][0], "halo")

    def test_it_sits_around_the_text_column(self):
        widget = note()
        widget.start_edit()
        left, width = widget.halo_box(70)
        self.assertEqual(left, GUTTER - HALO)
        self.assertLessEqual(left + width, 70)

    def test_the_open_box_is_the_text_plus_a_row_above_and_below(self):
        widget = note()
        widget.start_edit()
        text_rows = widget._edit.rows((66,))
        self.assertEqual(widget.rows((70,)), text_rows + 2 * HALO)

    def test_a_closed_note_has_no_halo(self):
        painted = attrs(note())
        self.assertNotIn("halo", [name for row in painted for name in row])

    def test_the_halo_follows_the_terminal_width(self):
        widget = note()
        widget.start_edit()
        for cols in (30, 60, 100, 160):
            left, width = widget.halo_box(cols)
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(left + width, cols)
            for row in widget.render((cols,), True).content():
                self.assertEqual(
                    sum(len(text.decode()) for _n, _cs, text in row), cols)


class ClickTests(unittest.TestCase):
    """The halo is part of the target, not a dead border."""

    def setUp(self):
        VIEW.cols, VIEW.rows = 70, 40
        self.widget = note()
        self.widget.start_edit()

    def click(self, col, row):
        self.widget._edit.edit_pos = 0
        self.widget.mouse_event((70,), "mouse press", 1, col, row, True)
        return self.widget._edit.edit_pos

    def test_clicking_the_text_puts_the_cursor_there(self):
        self.assertEqual(self.click(20, 1), 16)

    def test_clicking_the_row_above_uses_the_first_line(self):
        self.assertEqual(self.click(20, 0), self.click(20, 1))

    def test_clicking_the_row_below_uses_the_last_line(self):
        widget = self.widget
        below = self.click(30, 2)
        self.assertGreater(below, 0)
        self.assertLessEqual(below, len(widget._edit.edit_text))

    def test_clicking_the_left_edge_goes_to_the_start(self):
        self.assertEqual(self.click(0, 1), 0)
        self.assertEqual(self.click(1, 1), 0)

    def test_clicking_past_the_end_of_the_line_goes_to_the_end(self):
        self.assertEqual(self.click(69, 1), len(self.widget._edit.edit_text))

    def test_clicking_a_corner_is_still_a_click(self):
        # The bottom right corner belongs to the button strip now, so the
        # corners that are still halo are the other three.
        for col, row in ((0, 0), (69, 0), (0, 2)):
            self.click(col, row)          # must not raise or lose the edit
            self.assertTrue(self.widget.editing, (col, row))

    def test_the_button_strip_is_not_part_of_the_text_target(self):
        spans = self.widget.buttons(70)
        self.assertTrue(spans)
        self.widget.mouse_event((70,), "mouse press", 1, spans["drop"][0],
                                self.widget.rows((70,)) - 1, True)
        self.assertFalse(self.widget.editing, "✕ closed it")

    def test_a_wrapped_note_maps_rows_to_lines(self):
        widget = note(SENTENCE + " " + SENTENCE)
        widget.start_edit()
        widget._edit.edit_pos = 0
        widget.mouse_event((40,), "mouse press", 1, 5, 3, True)
        self.assertGreater(widget._edit.edit_pos, 40)


class PaneHaloTests(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows = 80, 40

    def test_an_edited_pane_gets_a_side_halo_without_moving_the_grid(self):
        widget = note("Copper || Aluminium")
        shut = widget.rows((80,))
        widget.start_pane_edit(1)
        self.assertEqual(widget.rows((80,)), shut)
        painted = attrs(widget, 80)
        self.assertIn("halo", painted[0])
        self.assertIn("editing", painted[0])

    def test_the_other_pane_is_still_readable(self):
        widget = note("Copper || Aluminium")
        widget.start_pane_edit(1)
        self.assertIn("Copper", "".join(lines(widget.render((80,), True))))


if __name__ == "__main__":
    unittest.main()
