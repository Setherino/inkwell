import unittest

from .helpers import lines, retype  # noqa: F401
from inkwell import shaping as S
from inkwell import store
from inkwell import typography as T
from inkwell.app import Inkwell
from inkwell.document import MIN_PANE, Document
from inkwell.widgets import VIEW, NoteWidget


def page(*texts):
    notes = [store.Note(t) for t in texts]
    doc = Document()
    doc.rebuild(notes)
    return doc, notes


def rows(doc, note, maxcol=80):
    plan = doc.plan(note, maxcol)
    return ["".join(t for _a, t in row).rstrip() for row in plan.rows]


class ParseTests(unittest.TestCase):
    def test_two_bars_make_panes(self):
        self.assertEqual(S.classify("pros || cons").kind, S.PANES)
        self.assertNotEqual(S.classify("just | one bar").kind, S.PANES)

    def test_weights(self):
        self.assertEqual(S.panes("{2} wide || narrow"),
                         [(2.0, "wide"), (1.0, "narrow")])
        self.assertEqual(S.panes("a || b || c"),
                         [(1.0, "a"), (1.0, "b"), (1.0, "c")])

    def test_round_trip(self):
        self.assertEqual(S.repane([(2, "a"), (1, "b")]), "{2} a || b")
        self.assertEqual(S.unpane("{2} a || b"), "a b")


class LayoutTests(unittest.TestCase):
    def setUp(self):
        VIEW.rows, VIEW.unicode_ok, VIEW.big = 40, True, True

    def test_equal_panes_share_the_width(self):
        doc, notes = page("left || right")
        plan = doc.plan(notes[0], 80)
        self.assertEqual(len(plan.panes), 2)
        widths = [w for w, _r in plan.panes]
        self.assertLessEqual(abs(widths[0] - widths[1]), 2)

    def test_a_weight_makes_one_pane_wider(self):
        doc, notes = page("{3} wide || narrow")
        widths = [w for w, _r in doc.plan(notes[0], 80).panes]
        self.assertGreater(widths[0], widths[1] * 2)

    def test_three_panes(self):
        doc, notes = page("one || two || three")
        self.assertEqual(len(doc.plan(notes[0], 90).panes), 3)

    def test_dividers_line_up_across_a_run(self):
        doc, notes = page("**Ideal** || **Real**",
                          "no volume || molecules take up space",
                          "{2} a much longer first pane here || short")
        columns = [rows(doc, n)[0].index("│") for n in notes]
        self.assertEqual(len(set(columns)), 1, columns)

    def test_panes_stack_when_they_would_be_too_narrow(self):
        doc, notes = page("first pane || second pane || third pane")
        self.assertTrue(doc.plan(notes[0], 90).panes)
        self.assertFalse(doc.plan(notes[0], 30).panes)
        stacked = rows(doc, notes[0], 30)
        self.assertTrue(all(row.lstrip().startswith("▏") for row in stacked if row))

    def test_a_pane_grid_sits_in_the_text_column(self):
        doc, notes = page("left || right")
        plan = doc.plan(notes[0], 120)
        self.assertGreater(plan.indent, 10)
        self.assertLessEqual(plan.indent + sum(w for w, _r in plan.panes), 120)

    def test_a_pane_is_formatted_in_its_own_column(self):
        doc, notes = page("- an item || plain text")
        self.assertIn("•", rows(doc, notes[0], 80)[0])

    def test_a_short_pane_is_not_treated_as_a_heading(self):
        doc, notes = page("no volume of its own || molecules take up space")
        painted = rows(doc, notes[0], 80)[0]
        self.assertIn("no volume of its own", painted)   # not bolded

    def test_maths_works_inside_a_pane(self):
        doc, notes = page("$$PV = nRT$$ || $$E = mc^2$$")
        self.assertIn("PV = nRT", rows(doc, notes[0], 80)[0])
        self.assertIn("E = mc²", rows(doc, notes[0], 80)[0])

    def test_panes_never_overflow_the_width(self):
        doc, notes = page("a much longer left hand pane || and a right one too",
                          "{3} weighted || small", "a || b || c || d")
        for maxcol in range(20, 130, 7):
            for note in notes:
                for row in doc.plan(note, maxcol).rows:
                    self.assertLessEqual(sum(T.cols(t) for _a, t in row), maxcol)

    def test_min_pane_is_respected(self):
        doc, notes = page("left || right")
        for maxcol in range(20, 120, 3):
            plan = doc.plan(notes[0], maxcol)
            if plan.panes:
                self.assertGreaterEqual(min(w for w, _r in plan.panes), MIN_PANE)


class EditTests(unittest.TestCase):
    def setUp(self):
        VIEW.rows, VIEW.unicode_ok, VIEW.big = 40, True, True
        self.app = Inkwell(None, use_llm=False)
        self.app.commit("left pane text || right pane text")
        self.widget = self.app._notes[0]
        self.app.frame.render((80, 20), True)

    def test_clicking_a_pane_edits_that_pane_only(self):
        self.widget.mouse_event((80,), "mouse press", 1, 50, 0, True)
        self.assertEqual(self.widget._pane, 1)
        self.assertEqual(self.widget._edit.edit_text, "right pane text")

    def test_clicking_the_first_pane(self):
        self.widget.mouse_event((80,), "mouse press", 1, 5, 0, True)
        self.assertEqual(self.widget._pane, 0)

    def test_the_other_panes_stay_on_screen_while_you_type(self):
        self.widget.start_pane_edit(0)
        painted = lines(self.widget.render((80,), True))
        self.assertIn("right pane text", "".join(painted))

    def test_committing_writes_back_into_the_note(self):
        self.widget.start_pane_edit(1)
        retype(self.widget, "rewritten")
        self.widget.keypress((80,), "enter")
        self.assertEqual(self.widget.note.text, "left pane text || rewritten")

    def test_escape_is_handed_back_from_a_pane_too(self):
        """An open pane is a level of the tree; see test_escape.py."""
        self.widget.start_pane_edit(1)
        retype(self.widget, "rewritten")
        self.assertEqual(self.widget.keypress((80,), "esc"), "esc")
        self.assertTrue(self.widget.editing)

    def test_tab_walks_the_panes(self):
        self.widget.start_pane_edit(0)
        self.widget.keypress((80,), "tab")
        self.assertEqual(self.widget._pane, 1)
        self.widget.keypress((80,), "tab")
        self.assertEqual(self.widget._pane, 0)
        self.widget.keypress((80,), "shift tab")
        self.assertEqual(self.widget._pane, 1)

    def test_backspace_at_the_start_of_a_pane_does_not_eat_its_neighbour(self):
        self.widget.start_pane_edit(1)
        self.widget._edit.edit_pos = 0
        self.widget.keypress((80,), "backspace")
        self.assertEqual(self.widget.note.text, "left pane text || right pane text")
        self.assertEqual(len(self.app._notes), 1)

    def test_emptying_every_pane_removes_the_note(self):
        for pane in (0, 1):
            self.widget.start_pane_edit(pane)
            retype(self.widget, "")
            self.widget.keypress((80,), "enter")
        self.assertEqual(self.app._notes, [])


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.app = Inkwell(None, use_llm=False)
        self.app.frame.focus_position = "body"

    def focus(self, text):
        self.app.commit(text)
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(len(self.app._notes) - 1)
        return self.app._notes[-1]

    def test_f4_splits_a_note_across(self):
        widget = self.focus("ideal gas has no volume")
        self.app.unhandled("f4")
        self.assertEqual(widget.note.text, "ideal gas || has no volume")

    def test_f4_again_splits_the_last_pane(self):
        widget = self.focus("one two three four")
        self.app.frame.focus_position = "body"
        self.app.unhandled("f4")
        self.app.frame.focus_position = "body"
        self.app.unhandled("f4")
        self.assertEqual(widget.note.text, "one two || three || four")

    def test_f4_while_editing_splits_at_the_cursor(self):
        widget = self.focus("term and its meaning")
        widget.start_edit()
        widget._edit.edit_pos = len("term")
        self.app.frame.focus_position = "body"
        self.app.unhandled("f4")
        self.assertEqual(widget.note.text, "term || and its meaning")

    def test_f4_inside_a_pane_splits_that_pane(self):
        widget = self.focus("left || right side here")
        widget.start_pane_edit(1)
        widget._edit.edit_pos = len("right")
        self.app.frame.focus_position = "body"
        self.app.unhandled("f4")
        self.assertEqual(widget.note.text, "left || right || side here")

    def test_f3_folds_the_panes_back_into_one_box(self):
        widget = self.focus("{2} left || right")
        self.app.unhandled("f3")
        self.assertEqual(widget.note.text, "left right")

    def test_f3_on_a_plain_note_does_nothing(self):
        widget = self.focus("plain note here")
        self.app.unhandled("f3")
        self.assertEqual(widget.note.text, "plain note here")


if __name__ == "__main__":
    unittest.main()
