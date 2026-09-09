import unittest

from . import helpers  # noqa: F401
from inkwell import document, theme


class PaletteTests(unittest.TestCase):
    def test_both_palettes_define_every_attribute(self):
        for name in ("dark", "light"):
            self.assertEqual(set(theme.PALETTES[name]), set(theme.NAMES), name)

    def test_the_palette_is_in_urwid_form(self):
        for entry in theme.palette("dark"):
            self.assertEqual(len(entry), 6)
            self.assertIsInstance(entry[0], str)

    def test_every_attribute_the_document_asks_for_exists(self):
        used = set(document.ATTRS.values()) | {
            "marker", "leader", "rule", "meta", "tag", "kv_key", "kv_value",
            "term", "term_body", "table_head", "ask_mark", "math",
            "callout_bar", "check_done", "cursorbar", "editing", "prompt",
            "status", "ghost", "dialog", "dialog_item", "dialog_focus",
            "dialog_title", "title", "head", "section",
        }
        self.assertTrue(used <= set(theme.NAMES), used - set(theme.NAMES))


class ContrastTests(unittest.TestCase):
    """The point of two palettes is that neither one is a grey smudge."""

    QUIET = {"rule", "meta", "leader", "check_done", "tag", "ghost",
             "callout_bar", "status", "marker", "check", "code", "quote",
             "ask_mark", "kv_key", "section", "title", "math", "cursorbar",
             "prompt", "ask"}

    def ratio(self, name, key):
        _fg16, _bg16, _mono, fg, bg = theme.PALETTES[name][key]
        return theme.contrast(fg, bg or theme.BACKGROUND[name])

    def test_body_text_is_easy_to_read_in_both_themes(self):
        for name in ("dark", "light"):
            for key in ("body", "head", "kv_value", "term_body", "table_head",
                        "callout", "editing"):
                self.assertGreaterEqual(self.ratio(name, key), 7.0,
                                        f"{name}/{key}")

    def test_even_the_quiet_things_clear_the_minimum(self):
        for name in ("dark", "light"):
            for key in self.QUIET:
                self.assertGreaterEqual(self.ratio(name, key), 3.0,
                                        f"{name}/{key}")

    def test_the_two_themes_point_opposite_ways(self):
        self.assertGreater(theme.luminance(theme.PALETTES["dark"]["body"][3]),
                           theme.luminance(theme.PALETTES["light"]["body"][3]))

    def test_the_maths_is_known(self):
        self.assertAlmostEqual(theme.contrast("#000", "#fff"), 21.0, places=1)
        self.assertAlmostEqual(theme.contrast("#888", "#888"), 1.0, places=3)


class DetectionTests(unittest.TestCase):
    def test_an_explicit_choice_wins(self):
        self.assertEqual(theme.from_environment({"INKWELL_THEME": "light"}),
                         "light")
        self.assertEqual(theme.from_environment({"INKWELL_THEME": "nonsense"}),
                         None)

    def test_colorfgbg_says_which_way_round_the_terminal_is(self):
        self.assertEqual(theme.from_environment({"COLORFGBG": "15;0"}), "dark")
        self.assertEqual(theme.from_environment({"COLORFGBG": "0;15"}), "light")
        self.assertEqual(theme.from_environment({"COLORFGBG": "7;0"}), "dark")
        self.assertIsNone(theme.from_environment({"COLORFGBG": "default"}))

    def test_nothing_to_go_on_means_dark(self):
        self.assertEqual(theme.detect({}, ask=False), "dark")

    def test_toggling(self):
        self.assertEqual(theme.other("dark"), "light")
        self.assertEqual(theme.other("light"), "dark")


if __name__ == "__main__":
    unittest.main()
