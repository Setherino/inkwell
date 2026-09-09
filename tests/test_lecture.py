"""A whole lecture, jotted the way a student types, checked as a page.

This is the end-to-end test: 57 things typed in a hurry -- fragments,
run-ons, LaTeX, a table, a comparison, todos -- and then assertions about
whether the result is a *document* someone would want to read back.
"""

import tempfile
import unittest
from pathlib import Path

from .helpers import retype  # noqa: F401
from .lecture_notes import STREAM
from inkwell import shaping as S
from inkwell import typography as T
from inkwell.app import Inkwell
from inkwell.widgets import VIEW

WIDTHS = (40, 56, 76, 92, 120)


def take_the_lecture(path=None):
    app = Inkwell(path, use_llm=False)
    VIEW.rows = 44
    for text, how in STREAM:
        if how == "compose":
            for ch in text:
                app.composer.keypress((60,), ch)
            if app.composer.edit_text.strip():
                app.composer.flush()
        else:
            app.commit(text)
    return app


def page(app, cols):
    """Every row of the finished document, as strings."""
    VIEW.cols = cols
    out = []
    for widget in app._notes:
        canvas = widget.render((cols,), False)
        out += [line.decode("utf-8").rstrip() for line in canvas.text]
    return out


def holes(app, cols):
    """Rows that are genuinely empty -- no text and no colour on them.

    A halo row around an open edit box is painted blue, so it is part of a
    box rather than a gap in the page.
    """
    VIEW.cols = cols
    out = []
    for widget in app._notes:
        canvas = widget.render((cols,), False)
        for text, runs in zip(canvas.text, canvas.content()):
            painted = any(name is not None for name, _cs, _t in runs)
            out.append(not text.decode("utf-8").strip() and not painted)
    return out


def kinds(app):
    return [b.kind for b in app.doc.blocks]


class LectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        VIEW.unicode_ok, VIEW.big, VIEW.rows = True, True, 44
        cls.app = take_the_lecture()

    def setUp(self):
        VIEW.unicode_ok, VIEW.big, VIEW.rows = True, True, 44

    # --- it all arrived ---------------------------------------------------
    def test_everything_typed_became_a_note(self):
        self.assertGreaterEqual(len(self.app._notes), len(STREAM))

    def test_the_prose_sentences_filed_themselves(self):
        texts = [w.note.text for w in self.app._notes]
        self.assertIn("entropy always increases in an isolated system.", texts)
        self.assertIn("so entropy can drive a reaction even when it costs energy.",
                      texts)

    def test_the_page_found_every_kind_of_box_the_student_used(self):
        found = set(kinds(self.app))
        for kind in (S.TITLE, S.SECTION, S.HEAD, S.PARA, S.ITEM, S.CHECK,
                     S.KV, S.TERM, S.TABLE, S.MATH, S.RULE, S.PANES, S.CALLOUT):
            self.assertIn(kind, found, kind)

    def test_exactly_one_title_at_the_top(self):
        self.assertEqual(kinds(self.app).count(S.TITLE), 1)
        self.assertEqual(kinds(self.app)[0], S.TITLE)

    def test_the_sections_are_the_ones_she_announced(self):
        sections = [b.shape.text for b in self.app.doc.blocks
                    if b.kind == S.SECTION]
        self.assertEqual(sections, ["The second law", "Clausius and heat flow",
                                    "Heat engines", "Statistical view"])

    def test_jotted_fragments_are_prose_not_headings(self):
        block = next(b for b in self.app.doc.blocks
                     if b.shape.text.startswith("prof started"))
        self.assertEqual(block.kind, S.PARA)

    def test_a_sentence_with_a_colon_is_not_mistaken_for_a_pair(self):
        block = next(b for b in self.app.doc.blocks
                     if b.shape.text.startswith("careful"))
        self.assertEqual(block.kind, S.PARA)

    # --- it fits ----------------------------------------------------------
    def test_no_line_overflows_at_any_width(self):
        for cols in WIDTHS + (34, 28):
            for line in page(self.app, cols):
                self.assertLessEqual(T.cols(line), cols, (cols, line))

    def test_the_page_is_mostly_content_not_whitespace(self):
        for cols in WIDTHS:
            rows = page(self.app, cols)
            filled = sum(1 for line in rows if line.strip())
            self.assertGreater(filled / len(rows), 0.55, cols)

    def test_never_more_than_two_blank_lines_together(self):
        for cols in WIDTHS:
            run = 0
            for empty in holes(self.app, cols):
                run = run + 1 if empty else 0
                self.assertLessEqual(run, 2, (cols, "too much air"))

    def test_prose_stops_widening_on_a_huge_terminal(self):
        rows = [line for line in page(self.app, 160) if line.strip()]
        self.assertLessEqual(max(T.cols(line) for line in rows), 160)
        prose = next(line for line in rows if "Boltzmann" in line)
        self.assertLess(T.cols(prose), 110)

    # --- the maths --------------------------------------------------------
    def test_no_latex_source_leaks_onto_the_page(self):
        painted = "\n".join(page(self.app, 92))
        for leak in ("\\frac", "\\int", "\\Delta", "\\ln", "$$", "\\times"):
            self.assertNotIn(leak, painted, leak)

    def test_the_formulae_are_typeset(self):
        painted = "\n".join(page(self.app, 92))
        for glyph in ("∑" if False else "∫", "Ω", "ΔS", "≈", "≥", "×", "─"):
            self.assertIn(glyph, painted, glyph)

    def test_display_maths_stacks_and_is_centred(self):
        block = next(b for b in self.app.doc.blocks
                     if b.kind == S.MATH and "C_p" in b.shape.text)
        rows = [" ".join(t for _a, t in row)
                for row in self.app.doc.plan(block.note, 92).rows]
        self.assertEqual(len(rows), 3)
        self.assertIn("T₂", rows[0])
        self.assertIn("∫", rows[1])
        self.assertIn("T₁", rows[2])
        self.assertGreater(len(rows[1]) - len(rows[1].lstrip()), 15)

    def test_inline_maths_reads_as_part_of_the_sentence(self):
        line = next(line for line in page(self.app, 92) if "Boltzmann" in line)
        self.assertIn("1.38 × 10⁻²³", line)

    def test_subscripts_are_consistent_between_similar_notes(self):
        painted = "\n".join(page(self.app, 92))
        # A subscript with no unicode form is set in tiny brackets, never as
        # the raw "_" the writer typed (see inkwell/latex.py).
        self.assertIn("ΔS₍ice₎", painted)
        self.assertIn("ΔS₍room₎", painted)

    # --- the structure ----------------------------------------------------
    def test_lists_are_tight_and_nesting_is_visible(self):
        rows = page(self.app, 92)
        first = rows.index("  • reversible: ΔS = 0")
        self.assertEqual(rows[first + 1], "  • irreversible: ΔS > 0")
        nested = rows[first + 2]
        self.assertIn("◦", nested)
        self.assertGreater(len(nested) - len(nested.lstrip()),
                           len(rows[first]) - len(rows[first].lstrip()))

    def test_every_section_gets_air_above_it_and_a_rule_below(self):
        rows = page(self.app, 92)
        for i, line in enumerate(rows):
            if "ꜱᴇᴄᴏɴᴅ" in line or "ᴇɴɢɪɴᴇꜱ" in line:
                self.assertFalse(rows[i - 1].strip())
                self.assertEqual(set(rows[i + 1].strip()), {"─"})

    def test_the_table_lines_up_and_has_a_header_rule(self):
        rows = page(self.app, 92)
        head = next(i for i, line in enumerate(rows) if "engine" in line
                    and "efficiency" in line)
        self.assertEqual(set(rows[head + 1].strip()), {"─"})
        body = rows[head + 2:head + 5]
        self.assertEqual(len({line.index("0.") for line in body}), 1, body)

    def test_the_comparison_is_a_grid_with_aligned_dividers(self):
        rows = [line for line in page(self.app, 92) if "│" in line]
        self.assertGreaterEqual(len(rows), 5)
        self.assertEqual(len({line.index("│") for line in rows}), 1)

    def test_timestamps_are_quiet(self):
        rows = page(self.app, 92)
        stamped = [line for line in rows if ":" in line[-6:]
                   and line[-5:-3].isdigit()]
        self.assertLessEqual(len(stamped), 3, stamped[:5])

    def test_narrow_terminals_stack_the_comparison_instead_of_squeezing(self):
        panes = [b for b in self.app.doc.blocks if b.kind == S.PANES]
        self.assertTrue(all(self.app.doc.plan(b.note, 92).panes for b in panes))
        self.assertFalse(any(self.app.doc.plan(b.note, 26).panes for b in panes))

    def test_a_comparison_never_goes_half_stacked(self):
        panes = [b for b in self.app.doc.blocks if b.kind == S.PANES]
        for cols in range(20, 120, 2):
            decisions = {bool(self.app.doc.plan(b.note, cols).panes)
                         for b in panes}
            self.assertEqual(len(decisions), 1, cols)

    def test_the_title_shrinks_rather_than_wrapping_forever(self):
        title = self.app.doc.blocks[0]
        heights = [len(self.app.doc.plan(title.note, cols, maxrow=44).rows
                       or self.app.doc.plan(title.note, cols, maxrow=44).big[1])
                   for cols in (120, 60, 30)]
        self.assertTrue(all(h <= 3 for h in heights), heights)

    # --- it stays put -----------------------------------------------------
    def test_rendering_twice_gives_the_same_page(self):
        self.assertEqual(page(self.app, 92), page(self.app, 92))

    def test_the_page_survives_a_trip_through_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            first = take_the_lecture(path)
            before = page(first, 92)
            again = Inkwell(path, use_llm=False)
            self.assertEqual(page(again, 92), before)

    def test_every_note_is_still_an_editable_box(self):
        for widget in self.app._notes:
            widget.start_edit()
            self.assertTrue(widget.editing, widget.note.text)
            self.assertIsNotNone(widget.get_cursor_coords((92,)))
            widget.stop_edit(keep=False)


class ReworkingTests(unittest.TestCase):
    """What the student does afterwards, tidying the notes up."""

    def setUp(self):
        VIEW.unicode_ok, VIEW.big, VIEW.rows = True, True, 44
        self.app = take_the_lecture()

    def find(self, fragment):
        for i, widget in enumerate(self.app._notes):
            if fragment in widget.note.text:
                self.app.frame.focus_position = "body"
                self.app.listbox.set_focus(i)
                return widget
        raise AssertionError(fragment)

    def test_fixing_a_typo_by_clicking_the_note(self):
        widget = self.find("problem set is due friday")
        text_row = widget.content_rows(92)[0]
        widget.mouse_event((92,), "mouse press", 1, 20, text_row, True)
        self.assertTrue(widget.editing)
        retype(widget, "the problem set is due friday, not thursday")
        widget.keypress((92,), "f12")
        self.assertIn("not thursday", widget.note.text)
        self.assertIn("the problem set is due friday, not thursday",
                      "\n".join(page(self.app, 92)))

    def test_promoting_a_jotted_line_to_a_heading(self):
        widget = self.find("area under the curve")
        widget.start_edit()
        retype(widget, "### T-S diagrams")
        widget.keypress((92,), "f12")
        self.assertEqual(self.app.doc.block_for(widget.note).kind, S.HEAD)

    def test_breaking_a_run_on_into_two_notes(self):
        widget = self.find("exam is the 14th")
        at = self.app._notes.index(widget)
        before = len(self.app._notes)
        widget.start_edit()
        widget._edit.edit_pos = len("exam is the 14th,")
        for key in ("enter", "enter"):       # a blank line splits the note
            widget.keypress((92,), key)
        widget.keypress((92,), "f12")
        self.assertEqual(len(self.app._notes), before + 1)
        self.assertEqual(self.app._notes[at].note.text, "exam is the 14th,")
        self.assertEqual(self.app._notes[at + 1].note.text,
                         "two of the five questions are entropy")

    def test_turning_two_notes_into_one(self):
        widget = self.find("extensive, it scales")
        before = len(self.app._notes)
        self.app.unhandled("f6")
        self.assertEqual(len(self.app._notes), before - 1)
        self.assertIn("extensive", "\n".join(page(self.app, 92)))

    def test_splitting_a_note_across_into_two_panes(self):
        widget = self.find("real ones lose to friction")
        self.app.unhandled("f4")
        self.assertEqual(self.app.doc.block_for(widget.note).kind, S.PANES)
        self.assertEqual(len(self.app.doc.plan(widget.note, 92).panes), 2)

    def test_folding_the_comparison_back_into_prose(self):
        widget = self.find("no attractions ||")
        self.app.unhandled("f3")
        self.assertEqual(widget.note.text,
                         "no attractions van der Waals forces matter")

    def test_ticking_off_a_todo(self):
        widget = self.find("email her about the extension")
        widget.keypress((92,), " ")
        self.assertTrue(widget.note.done)
        self.assertIn("☑ email her about the extension",
                      "\n".join(page(self.app, 92)))

    def test_deleting_a_note_she_does_not_want(self):
        widget = self.find("prof started 5 min late")
        before = len(self.app._notes)
        self.app.unhandled("f8")
        self.assertEqual(len(self.app._notes), before - 1)
        self.assertNotIn("prof started", "\n".join(page(self.app, 92)))

    def test_the_page_still_holds_together_afterwards(self):
        for fragment, key in (("area under the curve", "f4"),
                              ("net:", "f6"),
                              ("prof started", "f8")):
            self.find(fragment)
            self.app.unhandled(key)
        for cols in WIDTHS:
            rows = page(self.app, cols)
            for line in rows:
                self.assertLessEqual(T.cols(line), cols)
            run = 0
            for empty in holes(self.app, cols):
                run = run + 1 if empty else 0
                self.assertLessEqual(run, 2)


if __name__ == "__main__":
    unittest.main()
