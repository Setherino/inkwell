import unittest

import urwid

from .helpers import render_flow, retype  # noqa: F401
from inkwell import shaping as S
from inkwell import store
from inkwell.document import Document
from inkwell.widgets import VIEW, Composer, NoteWidget


def note(text, **kw):
    """One note, in a one-note document."""
    item = store.Note(text, **kw)
    doc = Document()
    doc.rebuild([item])
    return NoteWidget(item, doc)


class RenderTests(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows, VIEW.unicode_ok, VIEW.big = 80, 40, True, True

    def test_rows_matches_the_canvas_it_renders(self):
        for text in ("# Big Title", "SHIP IT", "- item", "prose " * 30,
                     "Ideas:", "> quoted", "TODO thing", "key: value",
                     "`code/path.py`", "1. numbered"):
            widget = note(text)
            for cols in (18, 40, 80, 200):
                self.assertEqual(widget.rows((cols,)),
                                 len(render_flow(widget, cols)),
                                 f"{text!r} at {cols}")

    def test_never_overflows_the_width_it_was_given(self):
        for text in ("# An Unusually Long Title Indeed", "prose " * 40,
                     "- " + "listitem " * 10, "WHY IS EVERYTHING ON FIRE"):
            for cols in range(8, 140, 7):
                for line in render_flow(note(text), cols):
                    self.assertLessEqual(len(line), cols, f"{text!r} at {cols}")

    def test_the_words_actually_appear(self):
        text = "the fins are half a millimetre apart in the exchanger core."
        self.assertIn("millimetre", "".join(render_flow(note(text), 80)))

    def test_focus_draws_a_cursor_bar(self):
        widget = note("- a bullet")
        self.assertTrue(render_flow(widget, 60, focus=True)[0].startswith("▌"))
        self.assertFalse(render_flow(widget, 60, focus=False)[0].startswith("▌"))

    def test_timestamp_gutter_only_when_there_is_room(self):
        widget = note("prose that is long enough to matter here.")
        stamp = widget.note.stamp()
        self.assertIn(stamp, "".join(render_flow(widget, 100)))
        self.assertNotIn(stamp, "".join(render_flow(widget, 60)))

    def test_short_screens_get_smaller_type(self):
        widget = note("# Inkwell")
        VIEW.rows = 40
        tall = widget.rows((100,))
        VIEW.rows = 8
        self.assertLess(widget.rows((100,)), tall)

    def test_ascii_mode_drops_the_fancy_letterforms(self):
        widget = note("> borrowed words")
        VIEW.unicode_ok = False
        self.assertIn("borrowed words", "".join(render_flow(widget, 60)))

    def test_model_formatting_shows_up_in_the_render(self):
        widget = note("we should cut the fin pitch in half before tapeout.",
                      emphasis="cut the fin pitch")
        self.assertIn("𝗰𝘂𝘁 𝘁𝗵𝗲 𝗳𝗶𝗻 𝗽𝗶𝘁𝗰𝗵", "".join(render_flow(widget, 90)))
        widget.note.fmt = {"block": S.CHECK}
        widget.doc.rebuild([widget.note])
        widget._built = None
        self.assertIn("☐", "".join(render_flow(widget, 90)))

    def test_tag_is_shown_when_wide_enough(self):
        widget = note("prose about cooling.", tag="thermal")
        self.assertIn("thermal", "".join(render_flow(widget, 90)))
        self.assertNotIn("thermal", "".join(render_flow(widget, 40)))


class EditTests(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows, VIEW.unicode_ok, VIEW.big = 80, 40, True, True

    def signals(self, widget):
        import urwid
        seen = []
        for name in ("changed", "removed", "leave"):
            urwid.connect_signal(widget, name,
                                 lambda _w, n=name: seen.append(n))
        return seen

    def test_click_opens_an_edit_box_with_a_cursor(self):
        widget = note("# Inkwell")
        self.assertIsNone(widget.get_cursor_coords((60,)))
        widget.mouse_event((60,), "mouse press", 1, 5, 1, True)
        self.assertTrue(widget.editing)
        self.assertIsNotNone(widget.get_cursor_coords((60,)))
        canvas = widget.render((60,), True)
        self.assertIsNotNone(canvas.cursor)

    def test_click_places_the_cursor_where_you_clicked(self):
        widget = note("the quick brown fox jumps over it.")
        widget.mouse_event((80,), "mouse press", 1, 6, 0, True)
        self.assertNotEqual(widget._edit.edit_pos, len(widget.note.text))

    def test_typing_on_a_focused_note_starts_editing_with_that_character(self):
        widget = note("hello")
        widget.keypress((60,), "!")
        self.assertTrue(widget.editing)
        self.assertEqual(widget._edit.edit_text, "hello!")

    def test_enter_breaks_the_line_and_f12_files_it(self):
        widget = note("hello")
        seen = self.signals(widget)
        widget.keypress((60,), "enter")     # open it
        widget._edit.insert_text(" there")
        widget.keypress((60,), "f12")
        self.assertFalse(widget.editing)
        self.assertEqual(widget.note.text, "hello there")
        self.assertEqual(seen, ["changed", "leave"])

    def test_enter_inside_an_open_note_is_a_line_break(self):
        widget = note("hello")
        widget.start_edit()
        widget.keypress((60,), "enter")
        self.assertTrue(widget.editing)
        self.assertEqual(widget._edit.edit_text, "hello\n")

    def test_escape_is_handed_back_rather_than_answered(self):
        """Esc means "up a level", and a note cannot know what is above it.

        What going up actually does to an open box is in test_escape.py,
        where the app that owns the tree can be asked.
        """
        widget = note("hello")
        widget.start_edit()
        retype(widget, "kept")
        self.assertEqual(widget.keypress((60,), "esc"), "esc")
        self.assertTrue(widget.editing)
        self.assertEqual(widget._edit.edit_text, "kept")

    def test_the_discard_button_abandons_it(self):
        widget = note("hello")
        widget.start_edit()
        widget.render((60,), True)
        retype(widget, "nope")
        first, _last = widget.buttons(60)["drop"]
        widget.mouse_event((60,), "mouse press", 1, first,
                           widget.rows((60,)) - 1, True)
        self.assertEqual(widget.note.text, "hello")

    def test_emptying_a_note_removes_it(self):
        widget = note("hello")
        seen = self.signals(widget)
        widget.start_edit()
        retype(widget, "   ")
        widget.keypress((60,), "f12")
        self.assertIn("removed", seen)

    def test_editing_a_note_lets_it_re_format(self):
        widget = note("some ordinary prose that runs on a while, honestly.")
        self.assertIsNone(widget.layout(80).big)
        widget.start_edit()
        retype(widget, "# New Title")
        widget.keypress((80,), "f12")
        widget.doc.rebuild([widget.note])
        widget._built = None
        self.assertIsNotNone(widget.layout(80).big)

    def test_space_toggles_a_check(self):
        widget = note("TODO ship it")
        widget.keypress((60,), " ")
        self.assertTrue(widget.note.done)
        self.assertIn("☑", "".join(render_flow(widget, 60)))

    def test_arrows_pass_through_so_the_list_can_scroll(self):
        widget = note("hello")
        self.assertEqual(widget.keypress((60,), "up"), "up")

    def test_an_arrow_off_the_end_of_a_note_steps_to_the_next(self):
        widget = note("hello")
        stepped = []
        urwid.connect_signal(widget, "step",
                             lambda _w, direction: stepped.append(direction))
        widget.start_edit()
        widget.keypress((60,), "up")
        self.assertEqual(stepped, [-1])
        self.assertFalse(widget.editing, "it closes on the way out")


class ComposerTests(unittest.TestCase):
    def collect(self):
        import urwid
        box, out = Composer(), []
        urwid.connect_signal(box, "commit", lambda _w, text: out.append(text))
        return box, out

    def type(self, box, text):
        for ch in text:
            box.keypress((40,), " " if ch == " " else ch)

    def test_a_finished_sentence_files_itself(self):
        box, out = self.collect()
        self.type(box, "the fins are close. ")
        self.assertEqual(out, ["the fins are close."])
        self.assertEqual(box.edit_text, "")

    def test_an_unfinished_thought_stays_in_the_box(self):
        box, out = self.collect()
        self.type(box, "the fins are close")
        self.assertEqual(out, [])
        self.assertEqual(box.edit_text, "the fins are close")

    def test_enter_files_whatever_is_there(self):
        box, out = self.collect()
        self.type(box, "no punctuation")
        box.keypress((40,), "enter")
        self.assertEqual(out, ["no punctuation"])

    def test_pasted_multi_sentence_text_splits(self):
        box, out = self.collect()
        box.set_edit_text("one. two. three")
        box.keypress((40,), "enter")
        self.assertEqual(out, ["one.", "two.", "three"])

    def test_an_empty_box_reports_an_arrow_up_as_a_sink(self):
        import urwid
        box = Composer()
        seen = []
        urwid.connect_signal(box, "sink", lambda _w: seen.append("sink"))
        box.keypress((40,), "up")
        self.assertEqual(seen, ["sink"])
        # ...and esc is not the composer's to answer: it goes up the tree.
        self.assertEqual(box.keypress((40,), "esc"), "esc")


if __name__ == "__main__":
    unittest.main()
