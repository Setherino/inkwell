import unittest

import urwid

from . import helpers  # noqa: F401
from inkwell import typography as T


class WrapTests(unittest.TestCase):
    def test_wraps_on_words(self):
        self.assertEqual(T.wrap("one two three", 7), ["one two", "three"])

    def test_hard_splits_an_over_long_word(self):
        self.assertEqual(T.wrap("abcdefgh", 3), ["abc", "def", "gh"])

    def test_soft_mode_leaves_a_long_word_alone(self):
        self.assertEqual(T.wrap("abcdefgh", 3, hard=False), ["abcdefgh"])

    def test_measures_in_columns_not_characters(self):
        self.assertEqual(T.cols(T.transform("bold", "abc")), 3)


class InlineTests(unittest.TestCase):
    def test_markup_becomes_letterforms_and_the_markers_go(self):
        self.assertEqual(T.inline("a **bold** word"),
                         "a " + T.transform("bold", "bold") + " word")
        self.assertEqual(T.inline("an _italic_ word"),
                         "an " + T.transform("italic", "italic") + " word")
        self.assertEqual(T.inline("run `make test` now"),
                         "run " + T.transform("mono", "make test") + " now")

    def test_underscores_inside_words_are_left_alone(self):
        self.assertEqual(T.inline("call get_thing_now()"), "call get_thing_now()")

    def test_ascii_mode_keeps_the_text_plain(self):
        self.assertEqual(T.inline("a **bold** word", unicode_ok=False),
                         "a bold word")

    def test_letterforms_stay_one_column_wide(self):
        for name in ("bold", "italic", "mono", "smallcaps"):
            out = T.transform(name, "az09")
            self.assertEqual(urwid.calc_width(out, 0, len(out)), len(out), name)

    def test_emphasis_bolds_a_phrase_in_place(self):
        got = T.emphasise("cut the fin pitch in half", "fin pitch")
        self.assertEqual(got, "cut the " + T.transform("bold", "fin pitch")
                         + " in half")

    def test_emphasis_ignores_a_phrase_that_is_not_there(self):
        self.assertEqual(T.emphasise("some text", "absent"), "some text")


class TitleFontTests(unittest.TestCase):
    def test_the_title_steps_down_as_the_terminal_narrows(self):
        # "Inkwell" needs 41/27/21 columns in the three fonts.
        got = [T.title_font("Inkwell", cols, 40) for cols in (120, 40, 24, 20)]
        self.assertEqual([g[0] if g else None for g in got],
                         ["xl", "l", "m", None])

    def test_a_short_screen_refuses_tall_type(self):
        self.assertEqual(T.title_font("Inkwell", 120, 14)[0], "l")
        self.assertEqual(T.title_font("Inkwell", 120, 10)[0], "m")
        self.assertIsNone(T.title_font("Inkwell", 120, 6))

    def test_a_title_never_breaks_a_word_in_half(self):
        self.assertEqual(T.title_font("Inkwell", 40, 40)[1], ["Inkwell"])

    def test_no_title_may_eat_the_screen(self):
        size, lines = T.title_font("Cube Coffee Demo", 60, 40)
        self.assertLessEqual(len(lines) * T.height(size), int(40 * 0.45))

    def test_unsupported_characters_are_dropped_not_crashed(self):
        self.assertEqual(T.prepare("m", "a𝗯c"), "AC")


class ColumnTests(unittest.TestCase):
    def test_prose_stops_widening_and_then_centres(self):
        self.assertEqual(T.column(60), (60, 0))
        self.assertEqual(T.column(78), (78, 0))
        self.assertEqual(T.column(86), (78, 0))
        measure, offset = T.column(120)
        self.assertEqual(measure, 78)
        self.assertEqual(offset, 21)


if __name__ == "__main__":
    unittest.main()
