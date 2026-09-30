import unittest

from . import helpers  # noqa: F401  (path + encoding)
from inkwell import shaping as S


class CommitTests(unittest.TestCase):
    def test_terminator_then_space_commits(self):
        self.assertTrue(S.should_commit("ship the exchanger. "))
        self.assertTrue(S.should_commit("does it fit? "))

    def test_no_space_yet_means_still_typing(self):
        self.assertFalse(S.should_commit("ship the exchanger."))

    def test_abbreviations_and_initials_do_not_commit(self):
        for buf in ("fins e.g. ", "see fig. ", "Dr. ", "Seth J. ", "well... "):
            self.assertFalse(S.should_commit(buf), buf)

    def test_bare_punctuation_ignored(self):
        self.assertFalse(S.should_commit(". "))
        self.assertFalse(S.should_commit("  "))

    def test_closing_quote_after_terminator(self):
        self.assertTrue(S.should_commit('he said "go." '))

    def test_a_list_number_is_not_the_end_of_a_sentence(self):
        self.assertFalse(S.should_commit("3. "))
        self.assertFalse(S.should_commit("42. "))
        self.assertTrue(S.should_commit("the answer is 3. "))

    def test_idle_commit_needs_something_worth_keeping(self):
        self.assertTrue(S.is_idle_commit("half a thought"))
        self.assertFalse(S.is_idle_commit("a "))


class BlockTests(unittest.TestCase):
    def kind(self, text):
        return S.classify(text).kind

    def test_headings_and_sections(self):
        self.assertEqual(self.kind("# Cube Coffee"), S.TITLE)
        self.assertEqual(self.kind("## Thermals"), S.SECTION)
        self.assertEqual(self.kind("### details"), S.HEAD)
        self.assertEqual(self.kind("Open questions:"), S.HEAD)
        # A heading is short, terse and capitalised; a jotted lower-case
        # fragment is prose.
        self.assertEqual(self.kind("Heat Engines"), S.HEAD)
        self.assertEqual(self.kind("short fragment"), S.PARA)
        self.assertEqual(self.kind("prof started 5 min late again"), S.PARA)

    def test_lists(self):
        self.assertEqual(self.kind("- perforated alu"), S.ITEM)
        self.assertEqual(self.kind("* perforated alu"), S.ITEM)
        numbered = S.classify("2. bend the flange")
        self.assertEqual((numbered.kind, numbered.numbered, numbered.text),
                         (S.ITEM, True, "bend the flange"))

    def test_checks(self):
        for text in ("TODO email the vendor", "- [ ] email the vendor",
                     "[] email the vendor"):
            shape = S.classify(text)
            self.assertEqual((shape.kind, shape.done), (S.CHECK, False), text)
        self.assertTrue(S.classify("- [x] email the vendor").done)

    def test_key_value_pairs(self):
        shape = S.classify("fin pitch: 0.4mm")
        self.assertEqual((shape.kind, shape.key, shape.value),
                         (S.KV, "fin pitch", "0.4mm"))

    def test_a_sentence_with_a_colon_is_not_a_pair(self):
        self.assertEqual(self.kind("the plan: we ship it on friday, "
                                   "assuming the vendor delivers."), S.PARA)

    def test_quotes_code_and_callouts(self):
        self.assertEqual(self.kind("> borrowed words"), S.QUOTE)
        self.assertEqual(S.classify("`partkit/src/clinch.py`").text,
                         "partkit/src/clinch.py")
        self.assertEqual(self.kind("`partkit/src/clinch.py`"), S.CODE)
        self.assertEqual(self.kind("!do not ship without the gasket"), S.CALLOUT)
        self.assertEqual(self.kind("DO NOT SHIP"), S.CALLOUT)

    def test_prose(self):
        self.assertEqual(self.kind("the plate stack needs to shed 180W "
                                   "without a fan."), S.PARA)

    def test_leading_spaces_are_nesting(self):
        self.assertEqual(S.classify("- top").level, 0)
        self.assertEqual(S.classify("  - one in").level, 1)
        self.assertEqual(S.classify("    - two in").level, 2)
        self.assertEqual(S.classify(" " * 20 + "- far in").level, S.MAX_LEVEL)

    def test_markers_are_stripped_from_display_text(self):
        self.assertEqual(S.classify("## Thermals").text, "Thermals")
        self.assertEqual(S.classify("  - nested item").text, "nested item")
        self.assertEqual(S.classify("> quoted").text, "quoted")

    def test_typed_markup_is_flagged_as_the_users_own(self):
        self.assertTrue(S.classify("- an item").explicit)
        self.assertTrue(S.classify("fin pitch: 0.4mm").explicit)
        self.assertFalse(S.classify("just some prose about it all here.").explicit)
        self.assertFalse(S.classify("DO NOT SHIP").explicit)


class SplitTests(unittest.TestCase):
    def test_multiple_sentences(self):
        self.assertEqual(S.split_sentences("one thing happened. then another. "),
                         ["one thing happened.", "then another."])

    def test_lines_with_markup_stay_whole(self):
        self.assertEqual(S.split_sentences("# Title\n- a. b\nplain text here."),
                         ["# Title", "- a. b", "plain text here."])

    def test_decimals_and_versions_stay_whole(self):
        self.assertEqual(S.split_sentences("fin pitch: 0.4mm"),
                         ["fin pitch: 0.4mm"])
        self.assertEqual(S.split_sentences("we ship v1.2 today. then v1.3."),
                         ["we ship v1.2 today.", "then v1.3."])

    def test_a_numbered_item_is_not_split_at_its_number(self):
        self.assertEqual(S.split_sentences("1. cut the plate"),
                         ["1. cut the plate"])

    def test_indentation_survives_the_split(self):
        self.assertEqual(S.split_sentences("  - a nested item"),
                         ["  - a nested item"])
        self.assertEqual(S.split_sentences("  first. second."),
                         ["  first.", "  second."])


if __name__ == "__main__":
    unittest.main()


class MathsIsNotATable(unittest.TestCase):
    """Bars in a formula are math, not column separators.

    ``$|y|$`` is an absolute value and ``$\\|x\\|$`` a norm; counting those
    pipes made a paragraph into a table row and a norm into panes.
    """

    def test_bars_inside_inline_maths_do_not_make_a_table(self):
        shape = S.classify(r"It follows that $\|x\|$ and $|y|$ agree.")
        self.assertEqual(shape.kind, S.PARA)

    def test_norm_bars_in_display_maths_do_not_make_panes(self):
        self.assertEqual(S.classify(r"$$\|x\|_2 = 1$$").kind, S.MATH)
        self.assertEqual(S.classify(r"$$||x||_2 = 1$$").kind, S.MATH)

    def test_a_real_table_row_is_still_a_table(self):
        self.assertEqual(S.classify("engine | T_h | efficiency").kind, S.TABLE)

    def test_columns_outside_maths_still_count(self):
        self.assertEqual(S.classify("speed | $v=1$ | fast").kind, S.TABLE)

    def test_real_panes_still_win(self):
        self.assertEqual(S.classify("left || right").kind, S.PANES)


class AnEquationMayWrapInTheSource(unittest.TestCase):
    r"""A whole-note formula stays math even when the source breaks a line.

    LaTeX does not care where a newline falls inside ``$...$``, but a note
    broken over two lines was demoted to prose -- and prose sets its math
    inline, one line, small. A homework sheet writes exactly this shape, so
    every stacked fraction in it came out as ``r/2``.
    """

    EQUATION = ("$\\dot{x}_R = \\frac{r\\dot{\\phi}_L}{2}\n"
                "            = \\frac{r}{2}\\left( \\dot{\\phi}_L \\right)$")

    def test_a_formula_broken_over_two_lines_is_still_maths(self):
        self.assertEqual(S.classify(self.EQUATION).kind, S.MATH)

    def test_display_maths_broken_over_two_lines_is_still_maths(self):
        self.assertEqual(S.classify("$$a =\n  b$$").kind, S.MATH)

    def test_the_newline_does_not_reach_the_typesetter(self):
        self.assertNotIn("\n", S.classify(self.EQUATION).text)

    def test_the_indent_of_the_first_line_still_sets_the_level(self):
        self.assertEqual(S.classify("  $$a =\n b$$").level, 1)

    def test_maths_followed_by_prose_is_still_prose(self):
        self.assertEqual(S.classify("$a$\nand then some words").kind, S.PARA)

    def test_a_table_broken_over_two_lines_is_still_demoted(self):
        self.assertEqual(S.classify("a | b | c\nsecond line").kind, S.PARA)
