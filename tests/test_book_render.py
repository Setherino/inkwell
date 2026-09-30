"""tools/audit_book.py is the quality gate for a converted book.

It renders every note through the real widget stack and looks for the
handful of things that mean the conversion went wrong: a character the
font cannot draw, a LaTeX command that survived, a raw ``^``/``_`` from
math, a row wider than the terminal, and math whose brackets do not
close.

Two kinds of test live here.

*Detector tests* feed hand-built rows to one detector each. They are
fast, hermetic, and never touch the disk.

*Corpus tests* take real note text lifted out of Correll et al.,
``Introduction to Autonomous Robots`` -- embedded here as literal
strings, so nothing depends on ``~/Documents`` or on the 24 chapter
files existing -- render it, and assert it comes out clean.

Snippets that do NOT yet come out clean are listed in ``KNOWN_BAD``
below, one entry per snippet, each naming the defect and whose file has
to change to fix it. Those tests are marked ``unittest.expectedFailure``
so the suite stays green today; when a fix lands the test reports an
UNEXPECTED SUCCESS, which is the signal to delete the KNOWN_BAD entry.
Grep for ``KNOWN_BAD``.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import audit_book as A          # noqa: E402


def row(text, *attrs):
    return A.Row(text, frozenset(attrs))


def kinds(findings):
    return sorted({f.kind for f in findings})


# --- the look-alike decoder -------------------------------------------------
class Intended(unittest.TestCase):
    """Which letter, in which face, a character will really be drawn as."""

    def test_plain_letter_is_itself_in_the_regular_face(self):
        self.assertEqual(A.intended("a"), ("a", "regular"))

    def test_bold_lookalike_decodes_to_the_plain_letter_in_bold(self):
        self.assertEqual(A.intended("\U0001d5e5"), ("R", "bold"))

    def test_italic_lookalike_decodes_to_the_plain_letter_in_italic(self):
        self.assertEqual(A.intended("\U0001d62c"), ("k", "italic"))

    def test_smallcaps_lookalike_decodes_to_a_capital(self):
        self.assertEqual(A.intended("ᴏ"), ("O", "regular"))

    def test_mono_lookalike_decodes_to_the_plain_letter(self):
        self.assertEqual(A.intended("\U0001d68a"), ("a", "regular"))


class Oracle:
    """A stand-in font: it knows exactly the characters it is told."""

    def __init__(self, known="abcdefghijklmnopqrstuvwxyz"
                            "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,()[]{}^_|"):
        self.known = set(known)

    def has(self, character, face="regular"):
        return character in self.known


# --- 1. font coverage -------------------------------------------------------
class FontCoverage(unittest.TestCase):

    def test_a_character_the_face_cannot_draw_is_reported(self):
        found = A.font_findings([row("a ∣ b", "body")], Oracle())
        self.assertEqual(kinds(found), ["font.glyph"])
        self.assertIn("U+2223", found[0].key)
        self.assertIn("DIVIDES", found[0].key)

    def test_a_bold_lookalike_is_not_a_false_positive(self):
        """The heading glyph is absent from Menlo but its letter is not.

        pdf.py draws these with the real Bold face, so checking the raw
        code point would cry wolf on every bold heading in the book.
        """
        heading = "\U0001d5e5\U0001d5fc\U0001d5ef\U0001d5fc\U0001d601"   # Robot
        self.assertEqual(A.font_findings([row(heading, "head")], Oracle()), [])

    def test_the_replacement_character_is_its_own_class(self):
        found = A.font_findings([row("bad � here", "body")], Oracle())
        self.assertEqual(kinds(found), ["font.replacement"])

    def test_glyphs_pdf_substitutes_are_reported_separately(self):
        """pdf.INSTEAD already names these as undrawable; paper swaps them."""
        found = A.font_findings([row("vₜ", "body")], Oracle())
        self.assertEqual(kinds(found), ["font.substituted"])

    def test_block_art_is_reported_separately_from_text(self):
        """A block-font title is inkwell's own design, not a conversion bug."""
        found = A.font_findings([row(" \U0001fb02\U0001fb01 █ ")], Oracle())
        self.assertEqual(kinds(found), ["font.art"])

    def test_a_row_of_ordinary_text_is_clean(self):
        self.assertEqual(A.font_findings([row("plain words (here).")],
                                         Oracle()), [])

    def test_spaces_are_never_reported(self):
        self.assertEqual(A.font_findings([row("   ")], Oracle(known="")), [])

    def test_the_finding_carries_the_row_and_its_index(self):
        found = A.font_findings([row("ok"), row("x ∣")], Oracle())
        self.assertEqual((found[0].row, found[0].text), (1, "x ∣"))


# --- 2. LaTeX leaks ---------------------------------------------------------
class LatexLeaks(unittest.TestCase):

    def test_a_surviving_command_is_reported(self):
        found = A.latex_findings([row("0 0 0 1 \\hline", "math")])
        self.assertEqual(kinds(found), ["latex"])
        self.assertEqual(found[0].key, "\\hline")

    def test_several_commands_on_one_row_are_all_reported(self):
        found = A.latex_findings([row("[ \\arraycolsep=2pt \\hline ]", "math")])
        self.assertEqual([f.key for f in found], ["\\arraycolsep", "\\hline"])

    def test_prose_without_a_backslash_is_clean(self):
        self.assertEqual(A.latex_findings([row("a well set sentence.")]), [])

    def test_a_verbatim_code_row_is_left_alone(self):
        """Pseudocode listings quote LaTeX on purpose; that is not a leak."""
        self.assertEqual(
            A.latex_findings([row("Bel(x) = $\\sum_{x}$P(x)", "code")]), [])

    def test_a_bare_double_backslash_is_reported(self):
        found = A.latex_findings([row("row one \\\\ row two", "math")])
        self.assertEqual([f.key for f in found], ["\\\\"])


# --- 3. raw script markers --------------------------------------------------
class ScriptMarkers(unittest.TestCase):

    def test_a_raw_superscript_marker_is_reported(self):
        found = A.script_findings([row("elements ^AP=[p]", "body")])
        self.assertEqual(kinds(found), ["script"])
        self.assertEqual(found[0].key, "^")

    def test_a_raw_subscript_marker_is_reported(self):
        found = A.script_findings([row("with p_x and p_y", "body")])
        self.assertEqual([f.key for f in found], ["_", "_"])

    def test_an_underscore_inside_a_url_is_not_a_defect(self):
        self.assertEqual(
            A.script_findings([row("• Video: http://youtu.be/_lHSaw", "body")]),
            [])

    def test_a_bare_domain_url_is_not_a_defect(self):
        self.assertEqual(
            A.script_findings([row("see youtu.be/QdHO_9M8-UI", "body")]), [])

    def test_a_file_name_is_not_a_defect(self):
        self.assertEqual(
            A.script_findings([row("built by tools/tex2ink.py, see my_notes.tex")]),
            [])

    def test_a_verbatim_code_row_is_left_alone(self):
        self.assertEqual(
            A.script_findings([row("q_rand = SampleRandomState(X);", "code")]), [])

    def test_a_mono_identifier_in_prose_is_left_alone(self):
        """Inline code is set in mono look-alikes; q_rand is a name."""
        mono = "\U0001d68a_\U0001d68b"       # 𝚊_𝚋
        self.assertEqual(A.script_findings([row("near " + mono, "body")]), [])

    def test_clean_prose_is_clean(self):
        self.assertEqual(A.script_findings([row("a well set sentence.")]), [])


# --- 4. layout faults -------------------------------------------------------
class Layout(unittest.TestCase):

    def test_a_row_wider_than_the_terminal_is_reported(self):
        found = A.wide_findings([row("x" * 11)], 10)
        self.assertEqual(kinds(found), ["wide"])

    def test_a_row_exactly_the_terminal_width_is_fine(self):
        self.assertEqual(A.wide_findings([row("x" * 10)], 10), [])

    def test_combining_accents_are_measured_by_display_width(self):
        """len() counts five combining marks that take up no columns."""
        text = "X̂" * 5                     # X̂ five times: 5 columns
        self.assertEqual(len(text), 10)
        self.assertEqual(A.wide_findings([row(text)], 6), [])

    def test_wide_glyphs_are_measured_by_display_width(self):
        text = "漢" * 5                      # 5 characters, 10 columns
        self.assertEqual(len(text), 5)
        self.assertEqual(kinds(A.wide_findings([row(text)], 6)), ["wide"])

    def test_three_blank_rows_in_a_row_are_reported(self):
        rows = [row("a"), row(""), row("  "), row(""), row("b")]
        found = A.blank_findings(rows)
        self.assertEqual(kinds(found), ["blank"])
        self.assertEqual(len(found), 1)

    def test_two_blank_rows_are_ordinary_spacing(self):
        self.assertEqual(A.blank_findings([row("a"), row(""), row(""), row("b")]),
                         [])

    def test_trailing_blank_rows_do_not_count(self):
        """The gap after the last note is the walker's, not the note's."""
        self.assertEqual(A.blank_findings([row("a"), row(""), row(""), row("")]),
                         [])

    def test_content_ratio_ignores_the_padding_around_a_note(self):
        rows = [row(""), row("a"), row("b"), row("")]
        self.assertEqual(A.content_ratio(rows), 1.0)

    def test_content_ratio_counts_interior_gaps(self):
        rows = [row("a"), row(""), row("b"), row(""), row("c")]
        self.assertAlmostEqual(A.content_ratio(rows), 0.6)

    def test_a_sparse_block_is_reported(self):
        rows = [row("a"), row(""), row(""), row("b"), row(""), row(""),
                row("c"), row(""), row(""), row("d"), row("")]
        self.assertEqual(kinds(A.sparse_findings(rows, floor=0.6)), ["sparse"])

    def test_a_short_block_is_never_called_sparse(self):
        """A two-line heading is half rule, half blank, and that is right."""
        rows = [row("1.1 Title"), row("─" * 20), row(""), row("")]
        self.assertEqual(A.sparse_findings(rows, floor=0.6), [])

    def test_an_empty_block_has_a_ratio_of_zero(self):
        self.assertEqual(A.content_ratio([row(""), row("")]), 0.0)


# --- 5. unbalanced delimiters ----------------------------------------------
class Delimiters(unittest.TestCase):

    def test_an_unclosed_paren_in_maths_is_reported(self):
        found = A.delimiter_findings([row("h=[r_i-(x cos(a_i)+y sin(a_i) ]", "math")])
        self.assertEqual(kinds(found), ["delim"])

    def test_balanced_maths_is_clean(self):
        self.assertEqual(
            A.delimiter_findings([row("f(x) = [a + b] * {c}", "math")]), [])

    def test_a_paren_closed_on_the_next_maths_row_is_not_a_defect(self):
        """One equation wrapped over two rows still balances as a block."""
        rows = [row("y = (a + b +", "math"), row("c + d)", "math")]
        self.assertEqual(A.delimiter_findings(rows), [])

    def test_prose_wrapped_mid_parenthesis_is_not_maths(self):
        """Most of the book's parens open on one line and close on the next."""
        rows = [row("they decide (rather than simply", "body"),
                row("following a set of motions). They achieve this", "body")]
        self.assertEqual(A.delimiter_findings(rows), [])

    def test_a_stray_closing_brace_is_reported(self):
        found = A.delimiter_findings([row("v_i=v_x-h}", "math")])
        self.assertEqual(kinds(found), ["delim"])

    def test_two_maths_blocks_are_balanced_apart(self):
        rows = [row("y = (a", "math"), row("prose", "body"),
                row("b)", "math")]
        self.assertEqual(len(A.delimiter_findings(rows)), 2)


# --- the renderer ----------------------------------------------------------
class Rendering(unittest.TestCase):

    def test_a_note_renders_to_rows_carrying_their_attributes(self):
        rows = A.render_notes([("# 1  Kinematics", {})], 60)[0]
        self.assertTrue(rows)
        self.assertTrue(any("title" in r.attrs for r in rows))

    def test_display_maths_is_tagged_math(self):
        rows = A.render_notes([("$$x = 1$$", {})], 60)[0]
        self.assertTrue(any("math" in r.attrs for r in rows))

    def test_rendering_never_exceeds_the_width_asked_for(self):
        note = ("Sentences of ordinary prose that have to be wrapped by the "
                "document into a column that is narrower than they are.",
                {"block": "para"})
        for width in (40, 60, 92, 120):
            rows = A.render_notes([note], width)[0]
            self.assertEqual(A.wide_findings(rows, width), [], width)


# --- the bundled corpus -----------------------------------------------------
# Real note text from Correll et al., "Introduction to Autonomous Robots",
# as tools/tex2ink.py emits it. Embedded so this file needs no book on disk.
CORPUS = {
    # --- prose, headings, figures, tables: expected to be clean -------------
    "chapter-heading": ("# 3  Kinematics", {}),
    "section-heading": ("## 3.1  Forward Kinematics", {}),
    "prose-with-emphasis": (
        "In order to plan a robot’s movements, we have to understand the "
        "relationship between our control variables (i.e. the input to the "
        "motors that we can control at any given time) and the effect of these "
        "control variables on the motion of the robot, known as the field of "
        "_kinematics_.", {"block": "para"}),
    "figure-caption": (
        "> Figure 1.1: A wind-up toy that does not fall off the table using "
        "purely mechanical control. A fly-wheel that turns orthogonal to the "
        "robot’s motion induces a right turn as soon as it hits the "
        "ground once the front caster wheel goes off the edge.", {}),
    "table-row": ("Wheel type | Example | Degrees of Freedom", {}),
    "bullet": ("- Introduce the forward kinematics of simple arms and mobile "
               "robots, and understand the concept of holonomy", {}),
    "video-link": ("- Video: http://youtu.be/QdHO_9M8-UI", {}),
    "simple-equation": ("$$\\tan \\phi = \\frac{L}{R} \\qquad (3.37)$$", {}),
    "greek-subscripts": (
        "$$x_1 = l_1 \\cos\\alpha \\qquad y_1 = l_1 \\sin\\alpha$$", {}),
    "hat-in-prose": (
        "In order to describe the orientation of a point, we will attach a "
        "coordinate system to it. Let $ \\hat{X}_B, \\hat{Y}_B$ and "
        "$ \\hat{Z}_B$ be unit vectors that correspond to the principal axes "
        "of a coordinate system.", {"block": "para"}),
    "sqrt-and-fractions": (
        "$$f_{x,y}(\\alpha,\\beta)=\\sqrt{\\left(s_{\\alpha\\beta} + s_\\alpha"
        " - y\\right)^2 + \\left(c_{\\alpha\\beta}+c_\\alpha - x\\right)^2} "
        "\\qquad (3.16)$$", {}),
    "nested-fraction": (
        "$$c_\\alpha = \\frac{c_{\\alpha\\beta}l_2-x}{l_1}="
        "\\frac{c_\\theta l_2-x}{l_1}$$", {}),

    # --- the hard cases: prescripts, matrices, mathcal, verbatim ------------
    "prescript-matrix": (
        "$$^A_BR=[^A\\hat{X}_B \\quad ^A\\hat{Y}_B \\quad ^A\\hat{Z}_B] ,$$",
        {}),
    "prescript-in-prose": (
        "A point is related to the coordinate system it belongs to by a "
        "preceding super-script, e.g., $^AP$ to indicate a point $P$ in "
        "coordinate system $\\{A\\}$.", {"block": "para"}),
    "matrix-with-arraycolsep": (
        "$$^AP=\\left[ \\arraycolsep=2pt \\begin{matrix}1 & 0 & 0\\\\0 & 1 & 0"
        "\\\\0 & 0 & 1\\end{matrix}\\right]\\left[\\begin{matrix}p_x\\\\p_y"
        "\\\\p_z\\end{matrix} \\right],$$", {}),
    "matrix-with-hline": (
        "$$\\left[\\begin{matrix}^AQ\\\\1\\end{matrix}\\right]="
        "\\left[\\arraycolsep=2pt\\begin{matrix} & ^A_BR & & ^AP "
        "\\\\\\hline 0 & 0 & 0 & 1\\end{matrix}\\right]"
        "\\left[\\begin{matrix}^BQ\\\\1\\end{matrix}\\right]$$", {}),
    "matrix-with-ellipses": (
        "$$J= \\frac{\\partial \\bf{f}}{\\partial \\bf{X}} =\\left[ "
        "\\begin{matrix} \\frac{\\partial f_1}{\\partial X_1} & \\ldots & "
        "\\frac{\\partial f_1}{\\partial X_I}\\\\ \\vdots & \\ddots & \\vdots"
        "\\\\ \\frac{\\partial f_K}{\\partial X_1} & \\ldots & "
        "\\frac{\\partial f_K}{\\partial X_I} \\end{matrix} \\right] .$$", {}),
    "textbf-in-prose": (
        "Given such an axis $ \\hat{K}=[k_x k_y k_z]^T$ and an angle "
        "$\\theta$, one can calculate the so-called Euler parameters or unit "
        "quaternion $\\textbf{q}=(\\epsilon_1,\\epsilon_2,\\epsilon_3,"
        "\\epsilon_4)$.", {"block": "para"}),
    "mathcal-in-prose": (
        "Let $ \\mathcal{X}$ be a $d$-dimensional state space, e.g. "
        "$\\mathcal{O}(N)$ for a tree of size $N$.", {"block": "para"}),
    "transpose-and-bars": (
        "The covariance of the innovation $\\boldsymbol{S}_{k}="
        "{\\boldsymbol{H}_{k}}\\boldsymbol{P}_{k|k-1}"
        "{\\boldsymbol{H}_{k}^\\top}+\\boldsymbol{R}_{k}$", {}),
    "conditional-probability": (
        "Here, $P(B∣A)$ is the _conditional probability_ that $B$ "
        "happens, knowing that event $A$ happens.", {"block": "para"}),
    "pseudocode-listing": (
        "```\nTree=Init(X, G, start, max_dist, t, k, goal_bias);\n"
        "  q_rand = SampleRandomState(X);\n"
        "  q_new = Extend(q_nearest, q_rand, max_dist)\n```", {}),
    "table-with-symbol": ("Decorator | Decorator | $\\Diamond$", {}),
    "displaystyle-sum": (
        "$$S=\\displaystyle\\sum_{i=1}^{n}\\frac{1}{\\sigma_i} "
        "(q-\\hat{q_i})^2 .$$", {}),
}

# --- KNOWN_BAD: snippets that do not render clean yet. -----------------------
# One entry per snippet: the defect classes it currently trips, and the file
# whose fix should clear it. These are marked unittest.expectedFailure, so the
# suite is green today; an UNEXPECTED SUCCESS means the fix landed and the
# entry should be deleted. Counts were taken at widths 60/92/120 on
# 2026-09-04 against the 24-chapter conversion.
KNOWN_BAD: dict = {
    # Empty: every snippet in the corpus renders clean as of 2026-09-04.
    # The mechanism stays for the next defect -- add an entry naming the
    # snippet, the defect classes it trips, and the file that owns the fix.
}

WIDTHS = (60, 92, 120)

# Flip every KNOWN_BAD entry on at once, without editing this file:
#     INKWELL_STRICT_CORPUS=1 python3 -m unittest tests.test_book_render
STRICT = os.environ.get("INKWELL_STRICT_CORPUS") == "1"


def _audit(name, width, glyphs):
    text, fmt = CORPUS[name]
    rows = A.render_notes([(text, fmt)], width)[0]
    return A.note_findings(rows, width, glyphs)


class Corpus(unittest.TestCase):
    """Real book text, rendered, checked by every detector."""

    @classmethod
    def setUpClass(cls):
        cls.glyphs = A.Glyphs.system()      # None if no TrueType font is here

    def check(self, name):
        for width in WIDTHS:
            found = _audit(name, width, self.glyphs)
            self.assertEqual(
                kinds(found), [],
                "%s at %d columns: %s" % (
                    name, width,
                    "; ".join("%s %s %r" % (f.kind, f.key, f.text)
                              for f in found[:4])))

    def test_every_corpus_entry_renders_something(self):
        for name in CORPUS:
            with self.subTest(name=name):
                rows = A.render_notes([CORPUS[name]], 92)[0]
                self.assertTrue(any(r.text.strip() for r in rows))

    def test_known_bad_names_are_all_in_the_corpus(self):
        self.assertEqual(sorted(set(KNOWN_BAD) - set(CORPUS)), [])

    def test_clean_entries_stay_clean(self):
        for name in sorted(set(CORPUS) - set(KNOWN_BAD)):
            with self.subTest(name=name):
                self.check(name)

    def test_layout_holds_at_every_width(self):
        """Width and blank-run faults are not allowed, known-bad or not."""
        for name in sorted(CORPUS):
            for width in WIDTHS:
                with self.subTest(name=name, width=width):
                    rows = A.render_notes([CORPUS[name]], width)[0]
                    self.assertEqual(A.wide_findings(rows, width), [])
                    self.assertEqual(A.blank_findings(rows), [])


def _known_bad_test(name, expected):
    """The same "renders clean" expectation, marked as not met yet."""

    def test(self):
        for width in WIDTHS:
            found = _audit(name, width, self.glyphs)
            self.assertEqual(
                kinds(found), [],
                "%s at %d columns (KNOWN_BAD: %s): %s" % (
                    name, width, ", ".join(expected),
                    "; ".join("%s %s %r" % (f.kind, f.key, f.text)
                              for f in found[:4])))

    test.__name__ = "test_known_bad_" + name.replace("-", "_")
    test.__doc__ = "KNOWN_BAD %s: %s" % (name, ", ".join(expected))
    return test if STRICT else unittest.expectedFailure(test)


class KnownBad(unittest.TestCase):
    """One expected failure per unfixed defect. See KNOWN_BAD above.

    Each of these asserts exactly what the clean entries assert -- that the
    snippet renders with no findings -- and is marked expectedFailure
    because it does not yet. An UNEXPECTED SUCCESS here means a fix landed
    in inkwell/latex.py or tools/tex2ink.py: delete that KNOWN_BAD entry.
    Set INKWELL_STRICT_CORPUS=1 to run them all for real instead.
    """

    @classmethod
    def setUpClass(cls):
        cls.glyphs = A.Glyphs.system()

    def test_every_known_bad_kind_is_a_real_defect_class(self):
        for name, expected in KNOWN_BAD.items():
            with self.subTest(name=name):
                self.assertEqual(sorted(set(expected) - set(A.KINDS)), [])


for _name, _expected in KNOWN_BAD.items():
    _test = _known_bad_test(_name, _expected)
    setattr(KnownBad, _test.__name__, _test)


# --- the whole book, if it happens to be here -------------------------------
class WholeBook(unittest.TestCase):
    """Skipped unless a converted book happens to be on this machine.

    A smoke test only, over the first few chapters -- sweeping all 24 at
    three widths is the CLI's job, not the unit suite's.
    """

    SAMPLE = 3

    def setUp(self):
        self.chapters = A.find_chapters()
        if not self.chapters:
            raise unittest.SkipTest("no converted book on this machine")

    def test_the_audit_reports_notes_and_rows(self):
        report = A.audit(self.chapters[:1], widths=(92,),
                         glyphs=A.Glyphs.system())
        self.assertTrue(report.notes)
        self.assertTrue(report.rows)
        self.assertTrue(report.ratios)

    def test_no_row_is_wider_than_the_terminal(self):
        report = A.audit(self.chapters[:self.SAMPLE], widths=WIDTHS,
                         glyphs=None)
        self.assertEqual([f.where for f in report.findings
                          if f.kind == "wide"], [])

    def test_no_run_of_three_blank_rows(self):
        report = A.audit(self.chapters[:self.SAMPLE], widths=WIDTHS,
                         glyphs=None)
        self.assertEqual([f.where for f in report.findings
                          if f.kind == "blank"], [])


if __name__ == "__main__":
    unittest.main()
