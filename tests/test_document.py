import unittest

from . import helpers  # noqa: F401
from inkwell import shaping as S
from inkwell import store
from inkwell import typography as T
from inkwell.document import Document, indent_unit


def page(*texts, fmt=None):
    """A document built from typed lines; fmt maps index -> model formatting."""
    notes = [store.Note(t) for t in texts]
    for index, fields in (fmt or {}).items():
        notes[index].fmt = fields
    doc = Document()
    doc.rebuild(notes)
    return doc, notes


def render(doc, note, maxcol=80, **kw):
    """The plan's rows as plain strings, the way they will be drawn."""
    plan = doc.plan(note, maxcol, **kw)
    return ["".join(text for _attr, text in row).rstrip() for row in plan.rows]


class StructureTests(unittest.TestCase):
    def test_the_first_heading_names_the_document(self):
        doc, notes = page("Cube Coffee Demo", "some prose about it, at length.")
        self.assertEqual(doc.block_for(notes[0]).kind, S.TITLE)

    def test_only_one_title(self):
        doc, notes = page("# First", "# Second")
        self.assertEqual(doc.block_for(notes[1]).kind, S.SECTION)

    def test_indented_notes_nest(self):
        doc, notes = page("- top", "  - one in", "    - two in")
        self.assertEqual([doc.block_for(n).level for n in notes], [0, 1, 2])

    def test_nesting_shows_a_different_marker_at_each_depth(self):
        doc, notes = page("- top", "  - one in", "    - two in")
        marks = [render(doc, n)[0].lstrip()[0] for n in notes]
        self.assertEqual(marks, ["•", "◦", "‣"])

    def test_a_list_is_packed_tight_and_opens_up_again_after(self):
        doc, notes = page("- one", "- two", "  - nested", "prose after it all, here.")
        # Spacing lives above each block, so gaps can never stack up.
        self.assertEqual([doc.plan(n, 80).blank_before for n in notes],
                         [0, 0, 0, 1])
        self.assertEqual([doc.plan(n, 80).blank_after for n in notes],
                         [0, 0, 0, 1])

    def test_a_section_gets_air_above_it_and_a_rule_below(self):
        doc, notes = page("prose to sit above it, at some length.", "## Thermals")
        plan = doc.plan(notes[1], 80)
        self.assertEqual(plan.blank_before, 2)     # a section gets real air
        self.assertTrue(render(doc, notes[1])[-1].strip().startswith("─"))

    def test_a_heading_has_no_rule(self):
        doc, notes = page("Open questions:")
        self.assertNotIn("─", "".join(render(doc, notes[0])))


class NumberingTests(unittest.TestCase):
    def test_a_run_counts_on_from_the_number_you_typed(self):
        # The first item sets where the list starts -- write "2." and it
        # stays 2 -- and the rest of the run just keeps counting.
        doc, notes = page("1. cut", "1. bend", "9. clinch")
        self.assertEqual([render(doc, n)[0].strip().split(".")[0] for n in notes],
                         ["1", "2", "3"])
        doc, notes = page("3. cut", "1. bend")
        self.assertEqual([render(doc, n)[0].strip().split(".")[0] for n in notes],
                         ["3", "4"])

    def test_a_single_numbered_note_keeps_its_own_number(self):
        doc, notes = page("2. [7 pts] the matrix below is orthonormal")
        self.assertEqual(render(doc, notes[0])[0].strip()[:2], "2.")

    def test_numbers_are_right_aligned_in_a_long_list(self):
        doc, notes = page(*[f"1. step {i}" for i in range(12)])
        rows = [render(doc, n)[0] for n in notes]
        # Single and double digits share one decimal point column...
        self.assertEqual(len({row.index(".") for row in rows}), 1, rows)
        # ...and one text column.
        self.assertEqual(len({row.index("step") for row in rows}), 1, rows)

    def test_numbering_carries_on_past_its_own_sub_items(self):
        doc, notes = page("1. first problem", "  - a note about it",
                          "  - another note", "2. second problem")
        marks = [render(doc, n)[0].strip()[:2] for n in notes]
        self.assertEqual([marks[0], marks[3]], ["1.", "2."])
        self.assertEqual(marks[1][0], "◦")

    def test_a_new_list_after_prose_starts_again_at_one(self):
        doc, notes = page("1. first", "2. second",
                          "some prose in between, long enough to be prose.",
                          "1. fresh list")
        self.assertEqual(render(doc, notes[3])[0].strip()[:2], "1.")

    def test_lettered_lists(self):
        doc, notes = page("(a) don't go out of bounds", "(b) don't revisit",
                          "(c) stop when there is nothing left")
        marks = [render(doc, n)[0].strip()[:3] for n in notes]
        self.assertEqual(marks, ["(a)", "(b)", "(c)"])

    def test_lettered_items_count_on_from_the_letter_you_typed(self):
        doc, notes = page("(a) first", "(a) second")
        self.assertEqual([render(doc, n)[0].strip()[:3] for n in notes],
                         ["(a)", "(b)"])
        doc, notes = page("(c) third", "(a) fourth")
        self.assertEqual([render(doc, n)[0].strip()[:3] for n in notes],
                         ["(c)", "(d)"])

    def test_bullets_stay_bullets(self):
        doc, notes = page("- one", "- two")
        self.assertTrue(all(render(doc, n)[0].lstrip().startswith("•") for n in notes))


class KeyValueTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.notes = page("fin pitch: 0.4mm", "open area: 23%",
                                    "vendor lead time: 3 weeks")

    def test_a_run_shares_one_key_column(self):
        rows = [render(self.doc, n)[0] for n in self.notes]
        leaders = [row.index("·") for row in rows]
        self.assertEqual(len(set(leaders)), 1, rows)

    def test_leaders_join_the_key_to_the_value(self):
        row = render(self.doc, self.notes[0])[0]
        self.assertRegex(row, r"fin pitch\s+·+\s+0\.4mm")

    def test_numeric_values_line_up_on_their_right_edge(self):
        rows = [render(self.doc, n, 60)[0] for n in self.notes]   # no stamps
        self.assertEqual(len({len(row) for row in rows}), 1, rows)

    def test_word_values_line_up_on_their_left_edge(self):
        doc, notes = page("material: 6061-T6 aluminium", "finish: clear anodise")
        starts = [len(row) - len(row.lstrip()) for row in
                  [render(doc, n)[0].split("· ")[-1] for n in notes]]
        self.assertEqual(starts, [0, 0])

    def test_the_table_keeps_its_size_until_the_terminal_forces_it_smaller(self):
        wide = render(self.doc, self.notes[0], 90)[0]
        same = render(self.doc, self.notes[0], 44)[0]
        squeezed = render(self.doc, self.notes[0], 36)[0]
        self.assertEqual(wide.count("·"), same.count("·"))
        self.assertLess(squeezed.count("·"), wide.count("·"))
        self.assertRegex(squeezed, r"fin pitch\s+·+\s+0\.4mm")

    def test_a_run_too_wide_to_align_stacks_instead_of_going_ragged(self):
        doc, notes = page("a really quite long key here: and a long value too")
        rows = render(doc, notes[0], 30)
        self.assertGreater(len(rows), 1)
        self.assertNotIn("·", "".join(rows))


class FlowTests(unittest.TestCase):
    def test_wrapped_lines_hang_under_the_text_not_the_marker(self):
        doc, notes = page("- " + "word " * 30)
        rows = render(doc, notes[0], 40)
        self.assertGreater(len(rows), 1)
        first_text = rows[0].index("word")
        for row in rows[1:]:
            self.assertEqual(row.index("word"), first_text)

    def test_nothing_overflows_the_width_it_was_given(self):
        doc, notes = page("# A Title", "## A Section", "Heading here",
                          "- an item that is quite long indeed, going on",
                          "  - a nested item, also rather long for its depth",
                          "1. numbered", "TODO a task", "key: value",
                          "> a quotation that runs on for a good while yet",
                          "`some/path/to/a/file.py`", "!SHOUTED WARNING",
                          "prose " * 30)
        for maxcol in range(12, 130, 6):
            for note in notes:
                plan = doc.plan(note, maxcol, maxrow=40)
                for row in plan.rows:
                    width = sum(T.cols(text) for _attr, text in row)
                    self.assertLessEqual(width, maxcol, (maxcol, row))

    def test_indentation_gets_cheaper_as_the_terminal_narrows(self):
        self.assertEqual(indent_unit(80), 2)
        self.assertEqual(indent_unit(40), 1)
        self.assertEqual(indent_unit(24), 0)

    def test_the_page_centres_itself_when_the_terminal_is_very_wide(self):
        doc, notes = page("prose " * 20)
        narrow = render(doc, notes[0], 70)[0]
        wide = render(doc, notes[0], 130)[0]
        self.assertEqual(len(narrow) - len(narrow.lstrip()), 0)
        self.assertGreater(len(wide) - len(wide.lstrip()), 10)

    def test_timestamps_only_when_there_is_room(self):
        doc, notes = page("prose that is long enough to matter here.")
        stamp = notes[0].stamp()
        self.assertIn(stamp, "".join(render(doc, notes[0], 100)))
        self.assertNotIn(stamp, "".join(render(doc, notes[0], 60)))

    def test_a_title_uses_a_font_when_it_fits_and_a_rule_when_it_does_not(self):
        doc, notes = page("# Inkwell")
        self.assertEqual(doc.plan(notes[0], 100, maxrow=40).big[0], "xl")
        plain = doc.plan(notes[0], 100, maxrow=40, big=False)
        self.assertIsNone(plain.big)
        self.assertTrue("".join(t for _a, t in plain.rows[-1]).strip().startswith("━"))


class VerbatimTests(unittest.TestCase):
    def test_code_keeps_its_own_spacing_and_is_not_re_wrapped(self):
        doc, notes = page("`grid = [[0,0],`", "`        [0,0]]`")
        body = [render(doc, n, 60)[0].split("▏ ", 1)[1] for n in notes]
        self.assertTrue(body[1].startswith(" " * 8), body[1])
        self.assertFalse(body[0].startswith(" "), body[0])

    def test_a_run_of_code_lines_is_one_block(self):
        doc, notes = page("`one`", "`two`", "prose after it, at some length.")
        self.assertEqual([doc.plan(n, 60).blank_before for n in notes],
                         [0, 0, 1])

    def test_a_long_code_line_is_clipped_into_rows_not_re_flowed(self):
        doc, notes = page("`" + "x" * 90 + "`")
        rows = render(doc, notes[0], 40)
        self.assertGreater(len(rows), 1)
        for row in rows:
            self.assertLessEqual(len(row), 40)


class NewBlockTests(unittest.TestCase):
    def test_display_maths_is_typeset_and_centred(self):
        doc, notes = page("$$\\frac{n(n+1)}{2}$$")
        rows = render(doc, notes[0], 80)
        self.assertEqual(len(rows), 3)
        self.assertTrue(set(rows[1].strip()) == {"─"})
        indents = [len(r) - len(r.lstrip()) for r in rows]
        self.assertTrue(all(i > 10 for i in indents), indents)

    def test_a_maths_block_is_centred_as_one_piece(self):
        doc, notes = page("$$\\begin{bmatrix} a \\\\ bb \\end{bmatrix} = 0$$")
        rows = render(doc, notes[0], 80)
        indents = {len(row) - len(row.lstrip()) for row in rows}
        self.assertEqual(len(indents), 1, rows)

    def test_maths_too_wide_to_stack_falls_back_and_still_fits(self):
        doc, notes = page("$$\\sum_{i=1}^{n} \\frac{x_i - \\mu}{\\sigma}$$")
        self.assertEqual(len(render(doc, notes[0], 80)), 3)   # stacked
        narrow = render(doc, notes[0], 11)
        self.assertNotIn("─", "".join(narrow))                # not stacked
        for row in narrow:
            self.assertLessEqual(len(row), 11, narrow)

    def test_inline_maths_inside_prose(self):
        doc, notes = page("the law says $\\Delta S \\geq 0$ for isolated systems.")
        self.assertIn("ΔS ≥ 0", "".join(render(doc, notes[0], 80)))

    def test_a_rule_spans_the_measure(self):
        doc, notes = page("prose above it, at some length here.", "---")
        row = render(doc, notes[1], 60)[0]
        self.assertEqual(set(row.strip()), {"─"})
        self.assertGreater(len(row.strip()), 40)

    def test_a_term_is_bold_with_a_dash_and_a_hanging_indent(self):
        doc, notes = page("entropy :: a measure of how many microstates "
                          "match a macrostate")
        rows = render(doc, notes[0], 50)
        self.assertIn("—", rows[0])
        self.assertGreater(len(rows), 1)
        # The second line starts under the definition, not under the term.
        self.assertEqual(len(rows[1]) - len(rows[1].lstrip()),
                         rows[0].index("—") + 2)

    def test_a_narrow_term_stacks_instead(self):
        doc, notes = page("a rather long term indeed :: and its meaning")
        rows = render(doc, notes[0], 30)
        self.assertNotIn("—", rows[0])

    def test_a_table_run_shares_its_columns_and_gets_a_header_rule(self):
        doc, notes = page("system | S (J/K) | note",
                          "ideal gas | 12.4 | textbook",
                          "crystal | 0.8 | near zero")
        head = render(doc, notes[0], 80)
        self.assertEqual(len(head), 2)
        self.assertEqual(set(head[1].strip()), {"─"})
        body = [render(doc, n, 80)[0] for n in notes[1:]]
        self.assertEqual(len({row.index("textbook") if "textbook" in row
                              else row.index("near") for row in body}), 1)

    def test_table_numbers_are_right_aligned(self):
        doc, notes = page("gas | 12.4 | a", "ice | 0.8 | b")
        rows = [render(doc, n, 60)[0] for n in notes]
        self.assertEqual(rows[0].index("12.4") + 4, rows[1].index("0.8") + 3)

    def test_a_column_of_numbers_aligns_even_with_a_negative_in_it(self):
        doc, notes = page("case | grid | answer", "a | 4x4 | 8", "b | 2x2 | -1")
        rows = [render(doc, n, 60)[0] for n in notes]
        self.assertEqual(rows[1].rstrip()[-1], "8")
        self.assertEqual(rows[2].rstrip()[-1], "1")
        self.assertEqual(len(rows[1].rstrip()), len(rows[2].rstrip()))
        # ...and a column of words still starts on the left.
        self.assertEqual(rows[1].index("4x4"), rows[2].index("2x2"))

    def test_a_single_table_row_has_no_header_rule(self):
        doc, notes = page("just | one | row")
        self.assertEqual(len(render(doc, notes[0], 60)), 1)


class TagTests(unittest.TestCase):
    """A tag names the thing it sits on."""

    def test_a_tag_that_repeats_the_notes_own_words_moves_to_the_figure(self):
        doc, notes = page("2. the matrix below is orthonormal - find x, y, z",
                          "$$M = \\begin{bmatrix} a & b \\\\ c & d \\end{bmatrix}$$")
        notes[0].tag = "matrix"
        doc.rebuild(notes)
        self.assertEqual(doc.block_for(notes[0]).tag, "")
        self.assertEqual(doc.block_for(notes[1]).tag, "matrix")
        self.assertIn("matrix", "".join(render(doc, notes[1], 92)))

    def test_the_moved_tag_is_centred_under_the_maths(self):
        doc, notes = page("the matrix below", "$$E = mc^2$$")
        notes[0].tag = "matrix"
        doc.rebuild(notes)
        rows = render(doc, notes[1], 92)
        self.assertIn("matrix", rows[-1])
        self.assertGreater(len(rows[-1]) - len(rows[-1].lstrip()), 20)

    def test_a_redundant_tag_with_nothing_to_move_to_is_dropped(self):
        doc, notes = page("some prose about thermals, at length.")
        notes[0].tag = "thermals"
        doc.rebuild(notes)
        self.assertEqual(doc.block_for(notes[0]).tag, "")

    def test_a_tag_that_adds_something_stays_put(self):
        doc, notes = page("we should cut the fin pitch before tapeout.")
        notes[0].tag = "thermal"
        doc.rebuild(notes)
        self.assertEqual(doc.block_for(notes[0]).tag, "thermal")
        self.assertIn("thermal", "".join(render(doc, notes[0], 92)))

    def test_headings_are_never_tagged(self):
        doc, notes = page("## Thermals", "prose under it, at some length.")
        notes[0].tag = "cooling"
        doc.rebuild(notes)
        self.assertEqual(doc.block_for(notes[0]).tag, "")

    def test_a_figure_that_has_its_own_tag_is_not_overwritten(self):
        doc, notes = page("the matrix below", "$$E = mc^2$$")
        notes[0].tag = "matrix"
        notes[1].tag = "energy"
        doc.rebuild(notes)
        self.assertEqual(doc.block_for(notes[1]).tag, "energy")

    def test_a_regular_plural_counts_as_the_same_word(self):
        # "vectors" mentions "vector". Irregular plurals (matrices) are not
        # something a suffix rule should pretend to know.
        doc, notes = page("the vectors below are orthogonal", "$$E = mc^2$$")
        notes[0].tag = "vector"
        doc.rebuild(notes)
        self.assertEqual(doc.block_for(notes[1]).tag, "vector")


class ModelFormattingTests(unittest.TestCase):
    def test_the_model_can_make_prose_into_a_check(self):
        doc, notes = page("remember to email the vendor about stock",
                          fmt={0: {"block": S.CHECK}})
        self.assertEqual(doc.block_for(notes[0]).kind, S.CHECK)
        self.assertTrue(render(doc, notes[0])[0].lstrip().startswith("☐"))

    def test_the_model_can_nest_a_note_under_the_one_above(self):
        doc, notes = page("- perforated aluminium",
                          "only if the vendor has it in stock this month",
                          fmt={1: {"block": S.ITEM, "continues": True}})
        self.assertEqual(doc.block_for(notes[1]).level, 1)

    def test_the_model_can_split_a_run_on_into_items(self):
        doc, notes = page("cut the plate then bend it then clinch it",
                          fmt={0: {"block": S.ITEM,
                                   "items": ["cut the plate", "bend it",
                                             "clinch it"]}})
        rows = render(doc, notes[0])
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.lstrip().startswith("•") for row in rows))

    def test_the_model_can_pair_a_fact_it_recognises(self):
        doc, notes = page("lead time is about three weeks",
                          fmt={0: {"block": S.KV, "key": "lead time",
                                   "value": "three weeks"}})
        self.assertRegex(render(doc, notes[0])[0], r"lead time\s+·+\s+three weeks")

    def test_a_kv_the_model_cannot_halve_falls_back_to_prose(self):
        doc, notes = page("just some prose here, nothing pair-like about it.",
                          fmt={0: {"block": S.KV}})
        self.assertEqual(doc.block_for(notes[0]).kind, S.PARA)

    def test_the_model_never_overrides_typed_markup(self):
        doc, notes = page("- an item the model wants to shout",
                          fmt={0: {"block": S.CALLOUT}})
        self.assertEqual(doc.block_for(notes[0]).kind, S.ITEM)

    def test_the_model_never_makes_a_title(self):
        doc, notes = page("prose about the plate stack, at some length.",
                          "more prose here, also at some length.",
                          fmt={1: {"block": S.TITLE}})
        self.assertEqual(doc.block_for(notes[1]).kind, S.PARA)

    def test_emphasis_is_bolded_inside_prose(self):
        doc, notes = page("we should cut the fin pitch in half before tapeout.")
        notes[0].emphasis = "cut the fin pitch"
        doc.rebuild(notes)
        self.assertIn(T.transform("bold", "cut the fin pitch"),
                      "".join(render(doc, notes[0], 90)))

    def test_a_tag_is_shown_when_there_is_room(self):
        doc, notes = page("prose about cooling, at some length.")
        notes[0].tag = "thermal"
        doc.rebuild(notes)
        self.assertIn("thermal", "".join(render(doc, notes[0], 90)))
        self.assertNotIn("thermal", "".join(render(doc, notes[0], 40)))


if __name__ == "__main__":
    unittest.main()
