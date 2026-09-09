"""Selecting, copying and pasting -- text inside a note, and whole notes."""

import unittest

from .helpers import lines  # noqa: F401
from inkwell import clip
from inkwell import shaping as S
from inkwell import store
from inkwell.app import Inkwell
from inkwell.widgets import Field


class Offline(unittest.TestCase):
    """Never touch the real pasteboard from a test."""

    def setUp(self):
        self._was = clip.COPY, clip.PASTE
        clip.COPY, clip.PASTE = ["no-such-command"], ["no-such-command"]
        clip._held = ""

    def tearDown(self):
        clip.COPY, clip.PASTE = self._was


class ClipTests(Offline):
    def test_it_falls_back_when_there_is_no_pasteboard(self):
        self.assertFalse(clip.copy("some text"))
        self.assertEqual(clip.paste(), "some text")

    def test_the_fallback_survives_a_failed_read(self):
        clip.copy("held")
        self.assertEqual(clip.paste(), "held")


class FieldTests(Offline):
    def field(self, text="the quick brown fox", at=4):
        box = Field("", text)
        box.set_edit_pos(at)
        return box

    def reach(self, box, key, times=1):
        for _ in range(times):
            box.keypress((40,), key)

    def test_shift_and_an_arrow_selects(self):
        box = self.field()
        self.reach(box, "shift right", 5)
        self.assertEqual(box.selection(), (4, 9))
        self.assertEqual(box.selected_text(), "quick")

    def test_selecting_backwards(self):
        box = self.field(at=9)
        self.reach(box, "shift left", 5)
        self.assertEqual(box.selected_text(), "quick")

    def test_an_arrow_on_its_own_drops_the_selection(self):
        box = self.field()
        self.reach(box, "shift right", 3)
        box.keypress((40,), "left")
        self.assertIsNone(box.selection())

    def test_the_selection_is_drawn_highlighted(self):
        box = self.field()
        self.reach(box, "shift right", 5)
        _text, attrib = box.get_text()
        self.assertEqual(attrib, [(None, 4), ("selected", 5)])

    def test_copy_takes_the_selection(self):
        box = self.field()
        self.reach(box, "shift right", 5)
        box.keypress((40,), "ctrl c")
        self.assertEqual(clip.paste(), "quick")
        self.assertEqual(box.edit_text, "the quick brown fox")

    def test_copy_with_no_selection_takes_the_whole_note(self):
        box = self.field()
        box.keypress((40,), "ctrl c")
        self.assertEqual(clip.paste(), "the quick brown fox")

    def test_cut_removes_what_it_took(self):
        box = self.field()
        self.reach(box, "shift right", 6)
        box.keypress((40,), "ctrl x")
        self.assertEqual(clip.paste(), "quick ")
        self.assertEqual(box.edit_text, "the brown fox")
        self.assertEqual(box.edit_pos, 4)

    def test_paste_goes_in_at_the_cursor(self):
        clip.copy("slow ")
        box = self.field()
        box.keypress((40,), "ctrl v")
        self.assertEqual(box.edit_text, "the slow quick brown fox")

    def test_paste_replaces_a_selection(self):
        clip.copy("lazy")
        box = self.field()
        self.reach(box, "shift right", 5)
        box.keypress((40,), "ctrl v")
        self.assertEqual(box.edit_text, "the lazy brown fox")

    def test_typing_replaces_a_selection(self):
        box = self.field()
        self.reach(box, "shift right", 5)
        box.keypress((40,), "X")
        self.assertEqual(box.edit_text, "the X brown fox")

    def test_backspace_deletes_a_selection(self):
        box = self.field()
        self.reach(box, "shift right", 6)
        box.keypress((40,), "backspace")
        self.assertEqual(box.edit_text, "the brown fox")

    def test_select_all(self):
        box = self.field()
        box.keypress((40,), "ctrl a")
        self.assertEqual(box.selected_text(), "the quick brown fox")

    def test_a_key_the_box_cannot_use_is_handed_back(self):
        box = self.field()
        # a one-line box cannot go up, so the page gets the key instead
        self.assertEqual(box.keypress((40,), "shift up"), "shift up")
        self.assertIsNone(box.anchor)
        empty = Field("", "")
        self.assertEqual(empty.keypress((40,), "ctrl c"), "ctrl c")
        self.assertEqual(empty.keypress((40,), "ctrl a"), "ctrl a")


class PickTests(Offline):
    def setUp(self):
        super().setUp()
        self.app = Inkwell(None, use_llm=False)
        self.app.frame.render((80, 24), True)
        for text in ("# Notes", "1. first item", "2. second item",
                     "3. third item"):
            self.app.commit(text)
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(1)

    def texts(self):
        return [w.note.text for w in self.app._notes]

    def test_shift_down_picks_a_run(self):
        self.app.unhandled("shift down")
        self.assertEqual([w.note.text for w in self.app.picked()],
                         ["1. first item", "2. second item"])

    def test_shift_up_picks_upwards(self):
        self.app.listbox.set_focus(3)
        self.app.unhandled("shift up")
        self.assertEqual([w.note.text for w in self.app.picked()],
                         ["2. second item", "3. third item"])

    def test_a_picked_note_shows_it(self):
        widget = self.app._notes[1]
        self.app.unhandled("shift down")
        painted = lines(widget.render((80,), False))
        first, _last = widget.content_rows(80)
        self.assertTrue(painted[first].startswith("█"), painted[first])

    def test_escape_clears_the_picking(self):
        self.app.unhandled("shift down")
        self.app.unhandled("esc")
        self.assertEqual(self.app.picked(), [])

    def test_select_all_picks_the_page(self):
        self.app.unhandled("ctrl a")
        self.assertEqual(len(self.app.picked()), 4)

    def test_copy_joins_notes_with_a_blank_line(self):
        self.app.unhandled("shift down")
        self.app.unhandled("ctrl c")
        self.assertEqual(clip.paste(), "1. first item\n\n2. second item")
        self.assertIn("copied 2 notes", self.app.status.text)

    def test_copy_with_nothing_picked_takes_the_focused_note(self):
        self.app.unhandled("ctrl c")
        self.assertEqual(clip.paste(), "1. first item")

    def test_cut_takes_them_off_the_page(self):
        self.app.unhandled("shift down")
        self.app.unhandled("ctrl x")
        self.assertEqual(self.texts(), ["# Notes", "3. third item"])
        self.assertEqual(clip.paste(), "1. first item\n\n2. second item")

    def test_paste_puts_them_back_as_separate_notes(self):
        clip.copy("one thing\n\ntwo things")
        self.app.unhandled("ctrl v")
        self.assertEqual(self.texts()[2:4], ["one thing", "two things"])

    def test_a_paste_is_one_step_to_undo(self):
        before = self.texts()
        clip.copy("one\n\ntwo\n\nthree")
        self.app.unhandled("ctrl v")
        self.assertEqual(len(self.texts()), len(before) + 3)
        self.app.unhandled("ctrl z")
        self.assertEqual(self.texts(), before)

    def test_a_cut_is_one_step_to_undo(self):
        before = self.texts()
        self.app.unhandled("shift down")
        self.app.unhandled("ctrl x")
        self.app.unhandled("ctrl z")
        self.assertEqual(self.texts(), before)

    def test_pasted_text_is_formatted_like_anything_else(self):
        clip.copy("## A section\n\n- an item")
        self.app.unhandled("ctrl v")
        kinds = [self.app.doc.block_for(w.note).kind for w in self.app._notes]
        self.assertIn(S.SECTION, kinds)
        self.assertIn(S.ITEM, kinds)

    def test_copying_out_and_pasting_back_gives_the_same_notes(self):
        self.app.unhandled("ctrl a")
        self.app.unhandled("ctrl c")
        fresh = Inkwell(None, use_llm=False)
        fresh.frame.render((80, 24), True)
        fresh.unhandled("ctrl v")
        self.assertEqual([w.note.text for w in fresh._notes], self.texts())


class DragTests(Offline):
    """Click and drag selects text -- inside an open note, and only there."""

    def setUp(self):
        super().setUp()
        self.app = Inkwell(None, use_llm=False)
        self.app.commit("the quick brown fox jumps over the lazy dog")
        self.widget = self.app._notes[0]
        self.widget.start_edit()
        self.widget.render((70,), True)

    def press(self, col, row=1):
        self.widget.mouse_event((70,), "mouse press", 1, col, row, True)

    def drag(self, col, row=1):
        return self.widget.mouse_event((70,), "mouse drag", 1, col, row, True)

    def selected(self):
        return self.widget._edit.selected_text()

    def test_a_press_leaves_no_selection(self):
        self.press(6)
        self.assertIsNone(self.widget._edit.selection())

    def test_dragging_from_the_press_selects(self):
        self.press(6)
        self.drag(11)
        self.assertEqual(self.selected(), "e qui")

    def test_the_selection_follows_the_mouse(self):
        self.press(6)
        self.drag(11)
        self.drag(20)
        self.assertEqual(self.selected(), "e quick brown ")
        self.drag(8)
        self.assertEqual(self.selected(), "e ")

    def test_dragging_backwards_selects_too(self):
        self.press(20)
        self.drag(6)
        self.assertEqual(self.selected(), "e quick brown ")

    def test_a_drag_past_the_end_stops_at_the_end(self):
        self.press(6)
        self.drag(200)
        self.assertTrue(self.selected().endswith("dog"))

    def test_what_you_dragged_over_is_what_gets_copied(self):
        self.press(6)
        self.drag(11)
        self.widget.keypress((70,), "ctrl c")
        self.assertEqual(clip.paste(), "e qui")

    def test_a_fresh_press_clears_the_last_selection(self):
        self.press(6)
        self.drag(20)
        self.press(30)
        self.assertIsNone(self.widget._edit.selection())

    def test_the_selection_is_drawn(self):
        self.press(6)
        self.drag(11)
        canvas = self.widget.render((70,), True)
        attrs = {name for row in canvas.content() for name, _cs, _t in row}
        self.assertIn("selected", attrs)

    def test_a_drag_over_a_closed_note_does_nothing(self):
        self.widget.stop_edit()
        self.assertFalse(self.drag(20))
        self.assertFalse(self.widget.editing)

    def test_a_drag_does_not_disturb_a_pane(self):
        self.app.commit("left || right")
        panes = self.app._notes[1]
        panes.start_pane_edit(0)
        panes.render((70,), True)
        before = panes._edit.edit_pos
        panes.mouse_event((70,), "mouse drag", 1, 40, 0, True)
        self.assertEqual(panes._edit.edit_pos, before)


class BlockTests(unittest.TestCase):
    """A blank line inside a note means the next block starts."""

    def test_blocks_in(self):
        self.assertEqual(S.blocks_in("one\n\ntwo"), ["one", "two"])
        self.assertEqual(S.blocks_in("one\ntwo"), ["one\ntwo"])
        self.assertEqual(S.blocks_in("one\n \ntwo"), ["one", "two"])
        self.assertEqual(S.blocks_in("  \n\n  "), [])

    def test_a_note_typed_with_a_blank_line_becomes_two(self):
        app = Inkwell(None, use_llm=False)
        app.commit("first note.")
        widget = app._notes[0]
        widget.start_edit()
        widget._edit.set_edit_text("orthonormal :: a definition\n\n"
                                   "$$E = mc^2$$")
        widget._edit.edit_pos = len(widget._edit.edit_text)
        widget.keypress((80,), "f12")
        self.assertEqual(len(app._notes), 2)
        kinds = [app.doc.block_for(w.note).kind for w in app._notes]
        self.assertEqual(kinds, [S.TERM, S.MATH])

    def test_it_is_one_step_to_undo(self):
        app = Inkwell(None, use_llm=False)
        app.commit("a note.")
        widget = app._notes[0]
        widget.start_edit()
        widget._edit.set_edit_text("one\n\ntwo\n\nthree")
        widget._edit.edit_pos = len(widget._edit.edit_text)
        widget.keypress((80,), "f12")
        self.assertEqual(len(app._notes), 3)
        app.unhandled("ctrl z")
        self.assertEqual([w.note.text for w in app._notes], ["a note."])


if __name__ == "__main__":
    unittest.main()
