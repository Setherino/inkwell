import unittest

import urwid

from . import helpers  # noqa: F401
from inkwell import latex as L


def width(text):
    return urwid.calc_width(text, 0, len(text))


class InlineTests(unittest.TestCase):
    def test_symbols_and_greek(self):
        self.assertEqual(L.inline(r"\alpha + \beta = \gamma"), "α + β = γ")
        self.assertEqual(L.inline(r"x \in \mathbb{R}^n"), "x ∈ ℝⁿ")
        self.assertEqual(L.inline(r"\Delta S \geq 0"), "ΔS ≥ 0")

    def test_a_command_swallows_its_space_but_an_operator_keeps_it(self):
        self.assertEqual(L.inline(r"2\pi f"), "2πf")
        self.assertEqual(L.inline(r"\sin\theta \cos\phi"), "sin θ cos φ")
        self.assertEqual(L.inline(r"S = k_B \ln \Omega"), "S = k₍B₎ ln Ω")

    def test_scripts_use_unicode_when_they_can(self):
        self.assertEqual(L.inline("x^2 + y^2"), "x² + y²")
        self.assertEqual(L.inline("x_{i+1}"), "xᵢ₊₁")
        self.assertEqual(L.inline("x_i^2"), "xᵢ²")     # subscript first

    def test_scripts_fall_back_to_tiny_parentheses(self):
        """A script with no unicode form is wrapped in ⁽ ⁾ / ₍ ₎ rather than
        leaking the raw ^ or _ the writer typed."""
        self.assertEqual(L.inline("e^{i\\pi}"), "e⁽iπ⁾")
        self.assertEqual(L.inline("k_B"), "k₍B₎")

    def test_fractions(self):
        self.assertEqual(L.inline(r"\frac{1}{2}mv^2"), "½mv²")
        self.assertEqual(L.inline(r"\frac{n}{2}"), "n/2")
        self.assertEqual(L.inline(r"\frac{f(x+h)-f(x)}{h}"), "(f(x+h)-f(x))/h")

    def test_roots(self):
        self.assertEqual(L.inline(r"\sqrt{2}"), "√2̄")
        self.assertEqual(L.inline(r"\sqrt{x^2+y^2}"), "√(x²+y²)")

    def test_accents(self):
        self.assertEqual(L.inline(r"\vec{F} = m\vec{a}"), "F⃗ = ma⃗")
        self.assertEqual(L.inline(r"\bar{x}"), "x̄")

    def test_a_closing_delimiter_hugs_what_it_closes(self):
        self.assertEqual(L.inline(r"\langle 3, -1, 3 \rangle"), "⟨3, -1, 3⟩")

    def test_matrices_collapse_onto_one_line(self):
        self.assertEqual(L.inline(r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}"),
                         "[a  b; c  d]")

    def test_text_and_fonts(self):
        self.assertEqual(L.inline(r"\text{if } x > 0"), "if  x > 0")
        # \mathcal has no monospace glyph anywhere, so it sets plain capitals
        # rather than a row of boxes the font cannot fill.
        self.assertEqual(L.inline(r"\mathcal{L}"), "L")
        self.assertEqual(L.inline(r"\mathbb{R}"), "ℝ")

    def test_everything_stays_one_column_per_character(self):
        for src in (r"\sum_{i=1}^{n} x_i", r"\frac{1}{2}", r"\vec{v}",
                    r"\mathbb{R}^3", r"\sqrt{2}", r"\theta \approx \pi"):
            out = L.inline(src)
            self.assertEqual(width(out), len(out) - out.count("⃗")
                             - out.count("̄"), src)

    def test_unknown_commands_come_back_verbatim(self):
        # Better to show the writer exactly what they typed than to guess.
        self.assertEqual(L.inline(r"\bogus{x}"), r"\bogus{x}")
        self.assertEqual(L.inline("50\\% of \\$5"), "50% of $5")

    def test_malformed_input_never_raises(self):
        for src in (r"\frac{1", "x^", "_", r"\begin{bmatrix} a", "{{{", "$"):
            L.inline(src)
            L.display(src)


class DisplayTests(unittest.TestCase):
    def test_a_fraction_stacks_over_a_rule(self):
        lines = L.display(r"\frac{n(n+1)}{2}")
        self.assertEqual(len(lines), 3)
        self.assertIn("n(n+1)", lines[0])
        self.assertTrue(set(lines[1].strip()) == {"─"})
        self.assertIn("2", lines[2])

    def test_sum_limits_go_above_and_below(self):
        lines = L.display(r"\sum_{i=1}^{n} i")
        self.assertEqual(len(lines), 3)
        self.assertIn("n", lines[0])
        self.assertIn("∑", lines[1])
        self.assertIn("i=1", lines[2])

    def test_integral_limits_too(self):
        lines = L.display(r"\int_{T_1}^{T_2} \frac{C_p}{T} dT")
        self.assertIn("T₂", lines[0])
        self.assertIn("∫", lines[1])
        self.assertIn("T₁", lines[2])

    def test_a_root_gets_a_rule_over_it(self):
        lines = L.display(r"\sqrt{x^2+y^2}")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].strip().startswith("─"))
        self.assertIn("√", lines[1])

    def test_a_fraction_in_a_matrix_stays_on_its_line(self):
        """A three-row cell would drag the whole grid apart, and the
        precomposed ⅔ glyph is tiny beside an ordinary letter."""
        lines = L.display(r"\begin{bmatrix} \frac{2}{3} \\ x \\ "
                          r"\frac{1}{3} \end{bmatrix}")
        self.assertEqual(len(lines), 3)
        self.assertIn("2/3", lines[0])
        self.assertNotIn("⅔", "".join(lines))
        self.assertIn("x", lines[1])

    def test_the_brackets_of_a_matrix_line_up(self):
        # The rows are not all the same length -- only the middle one carries
        # the "⋅ ... = 0" -- but the brackets must sit in the same columns.
        lines = L.display(r"\begin{bmatrix} \frac{2}{3} \\ x \end{bmatrix} "
                          r"\cdot \begin{bmatrix} z \\ \frac{1}{3} "
                          r"\end{bmatrix} = 0")
        opens = [min(line.index(c) for c in "⎡⎢⎣" if c in line) for line in lines]
        closes = [min(line.index(c) for c in "⎤⎥⎦" if c in line) for line in lines]
        self.assertEqual(len(set(opens)), 1, lines)
        self.assertEqual(len(set(closes)), 1, lines)

    def test_brackets_line_up_with_a_tall_cell(self):
        lines = L.display(r"\begin{bmatrix} \sum_{i=1}^{n} x_i & 0 \\ "
                          r"0 & 1 \end{bmatrix}")
        self.assertTrue(lines[0].startswith("⎡"), lines[0])
        self.assertTrue(lines[-1].startswith("⎣"), lines[-1])
        for line in lines[1:-1]:
            self.assertTrue(line.startswith("⎢"), line)

    def test_a_fraction_on_its_own_still_stacks(self):
        lines = L.display(r"\frac{2}{3}")
        self.assertEqual(len(lines), 3)
        self.assertEqual(set(lines[1].strip()), {"─"})

    def test_inline_prose_still_gets_the_compact_form(self):
        self.assertEqual(L.inline(r"\frac{2}{3} of it"), "⅔ of it")

    def test_a_matrix_comes_out_square_and_bracketed(self):
        lines = L.display(r"A = \begin{bmatrix} a & b \\ c & d \end{bmatrix}")
        self.assertEqual(len(lines), 2)
        self.assertIn("⎡", lines[0])
        self.assertIn("⎦", lines[1])
        self.assertEqual(len(set(len(x) for x in lines)), 1)

    def test_lines_are_padded_to_one_width(self):
        for src in (r"\frac{1}{2}", r"\sum_{i=1}^{n} i", r"e^{i\pi}+1=0"):
            lines = L.display(src)
            self.assertEqual(len({len(x.rstrip()) > 0 for x in lines}), 1, src)

    def test_short_maths_is_still_one_line(self):
        self.assertEqual(L.display("E = mc^2"), ["E = mc²"])



class PrescriptTests(unittest.TestCase):
    """``^A_B R`` -- the coordinate-frame transform. The scripts belong to the
    R that follows them, not to whatever came before."""

    def test_display_puts_them_in_a_column_against_the_base(self):
        self.assertEqual(L.display(r"^A_BR"), ["A", " R", "B"])

    def test_the_column_is_right_aligned_so_it_hugs_the_base(self):
        lines = L.display(r"^{AB}_CR")
        self.assertEqual(lines, ["AB", "  R", " C"])

    def test_either_order_reads_the_same(self):
        self.assertEqual(L.display(r"_B^AR"), L.display(r"^A_BR"))
        self.assertEqual(L.inline(r"_B^AR"), L.inline(r"^A_BR"))

    def test_inline_uses_tiny_parentheses_before_the_base(self):
        # Documented in the module docstring: a prescript is always
        # parenthesised, so it cannot be misread as the previous atom's script.
        self.assertEqual(L.inline(r"^A_BR"), "⁽ᴬ⁾₍B₎R")
        self.assertEqual(L.inline(r"^AP"), "⁽ᴬ⁾P")

    def test_the_convention_is_documented(self):
        self.assertIn("⁽", L.__doc__)
        self.assertIn("₍", L.__doc__)

    def test_a_prescript_after_a_relation_is_still_a_prescript(self):
        self.assertEqual(L.inline(r"^AQ=^BQ+^AP"), "⁽ᴬ⁾Q=⁽ᴮ⁾Q+⁽ᴬ⁾P")

    def test_a_prescript_keeps_its_bases_own_scripts(self):
        self.assertEqual(L.inline(r"^AP_B"), "⁽ᴬ⁾P₍B₎")

    def test_a_prescript_nested_in_brackets_does_not_leak(self):
        out = "\n".join(L.display(r"^A_BR=[^A\hat{X}_B \quad ^A\hat{Y}_B]"))
        self.assertNotIn("^", out)
        self.assertNotIn("_", out)
        self.assertIn("X̂", out)

    def test_a_prescript_inside_a_matrix_cell_stays_flat(self):
        lines = L.display(r"\begin{bmatrix} ^A_BR & ^AP \\ 0 & 1 \end{bmatrix}")
        self.assertEqual(len(lines), 2)
        self.assertIn("⁽ᴬ⁾₍B₎R", "".join(lines))

    def test_a_trailing_script_is_not_mistaken_for_a_prescript(self):
        self.assertEqual(L.inline("x^2"), "x²")
        self.assertEqual(L.inline(r"(x+y)^2"), "(x+y)²")


class ScriptFallbackTests(unittest.TestCase):
    """No script may ever put a bare ^ or _ on the page."""

    def test_display_sets_it_beside_the_base_like_inline(self):
        # It used to park the script on its own row. Beside a fraction that
        # row is the numerators', so the letter read as one of them.
        self.assertEqual(L.display(r"w_{i,j}^k"), ["w₍i,j₎ᵏ"])

    def test_display_and_inline_agree_on_a_cluster(self):
        for src in (r"w_{i,j}^k", r"\dot{x}_R", r"S_{r,\alpha}", r"e^{i\pi}"):
            self.assertEqual(L.display(src), [L.inline(src)], src)

    def test_inline_and_matrix_cells_use_tiny_parentheses(self):
        self.assertEqual(L.inline(r"w_{i,j}^k"), "w₍i,j₎ᵏ")
        lines = L.display(r"\begin{bmatrix} w_{i,j} \\ 0 \end{bmatrix}")
        self.assertEqual(len(lines), 2)
        self.assertIn("w₍i,j₎", "".join(lines))

    def test_greek_subscripts(self):
        self.assertEqual(L.inline(r"c_{\alpha\beta}"), "c₍αβ₎")
        self.assertEqual(L.inline(r"\sigma_{\dot{\phi}}"), "σ₍φ̇₎")

    def test_a_subscript_on_an_accented_base(self):
        self.assertEqual(L.inline(r"\hat{X}_B"), "X̂₍B₎")

    def test_a_braced_subscript_on_a_big_operator(self):
        # The outer _ used to be printed as well as applied.
        self.assertEqual(L.inline(r"\sum_{x_{t-1}}"), "∑₍xₜ₋₁₎")

    def test_the_whole_corpus_convention_holds_for_every_shape(self):
        for src in (r"S_{r,\alpha}", "E_d", "w_{0,j}", r"\hat{X}_B",
                    r"c_{\alpha\beta}", r"e^{i\pi}", r"^A_BR",
                    r"\sum_{x_{t-1}}", r"\nabla_{\Delta_{r,l}}f"):
            for out in (L.inline(src), "\n".join(L.display(src))):
                self.assertNotIn("_", out, src)
                self.assertNotIn("^", out, src)


class OnlyLimitsGoAboveAndBelow(unittest.TestCase):
    r"""A script sits beside its base unless the base takes limits.

    A capital has no unicode subscript, so display used to park it on the row
    below. Next to a fraction that row holds the denominators, and the row
    above holds the numerators, so ``\frac{r\dot\phi_L}{2}`` put a lone ``L``
    over the rule and the equation could not be read. ``\sum``, ``\int``,
    ``\lim`` and an already-tall base still take limits over and under.
    """

    NUMERATOR = r"\frac{r\dot{\phi}_L}{2}"

    def test_a_subscript_in_a_numerator_stays_beside_its_base(self):
        lines = L.display(self.NUMERATOR)
        self.assertEqual(len(lines), 3, lines)     # numerator, rule, denominator
        self.assertIn("φ̇₍L₎", lines[0])
        self.assertIn("─", lines[1])
        self.assertEqual(lines[2].strip(), "2")

    def test_no_stray_letter_is_left_on_a_row_of_its_own(self):
        self.assertNotIn("L", L.display(self.NUMERATOR)[1])
        self.assertNotIn("L", L.display(self.NUMERATOR)[2])

    def test_an_exponent_no_longer_shares_the_numerator_row(self):
        # The Gaussian: the "1" over the root, and e's exponent, both used to
        # land on the top row with nothing to say which owned which.
        lines = L.display(r"f(x)=\frac{1}{\sqrt{2\pi\sigma^2}}"
                          r"e^{-\frac{(x-\mu)^2}{2\sigma^2}}")
        top = [line for line in lines if "(x-μ)" in line]
        self.assertTrue(all("e⁽" in line for line in top), lines)

    def test_a_big_operator_still_takes_limits(self):
        for src in (r"\sum_{i=1}^{n} x_i", r"\int_{T_1}^{T_2} f dT",
                    r"\prod_{k=1}^{m} a_k"):
            self.assertEqual(len(L.display(src)), 3, src)

    def test_a_limit_word_still_takes_limits(self):
        lines = L.display(r"\lim_{x \to 0} \frac{\sin x}{x}")
        self.assertTrue(any("x → 0" in line for line in lines), lines)
        self.assertTrue(any(line.strip().startswith("lim") for line in lines))

    def test_a_tall_base_still_takes_its_script_above(self):
        lines = L.display(r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}^T")
        self.assertEqual(lines[0].strip(), "T")

    def test_the_equation_from_the_homework_reads_in_three_rows(self):
        lines = L.display(r"\dot{x}_R = \frac{r\dot{\phi}_L}{2} "
                          r"+ \frac{r\dot{\phi}_R}{2} "
                          r"= \frac{r}{2}\left( \dot{\phi}_L "
                          r"+ \dot{\phi}_R \right)")
        self.assertEqual(len(lines), 3, lines)
        # \dot{x} is emitted decomposed, as a terminal wants it, so compare
        # the composed forms rather than the code points.
        import unicodedata
        self.assertIn("ẋ₍R₎", unicodedata.normalize("NFC", lines[1]))


class AccentTests(unittest.TestCase):
    def test_a_point_accent_marks_only_the_first_character(self):
        # \hat{q_i} is one hat over the q, not a hat on every glyph.
        self.assertEqual(L.inline(r"\hat{q_i}"), "q̂ᵢ")

    def test_an_overline_still_covers_the_whole_group(self):
        self.assertEqual(L.inline(r"\overline{AB}"), "A\u0304B\u0304")

    def test_a_font_command_does_not_leak_its_braces(self):
        self.assertEqual(L.inline(r"\boldsymbol{\hat{x}_{k}}"), "x̂ₖ")
        self.assertNotIn("{", L.inline(r"\boldsymbol{\hat{x}_{k|k-1}}"))

    def test_an_accent_then_a_script_composes(self):
        self.assertEqual(L.inline(r"\hat{x}_k"), "x̂ₖ")
        self.assertNotIn("hat", L.inline(r"\hat{x}_k"))


class TallInsideAScriptTests(unittest.TestCase):
    def test_a_fraction_in_an_exponent_goes_linear(self):
        # The point is that no rule character gets into a script.
        lines = L.display(r"e^{-\frac{(x-\mu)^2}{2\sigma^2}}")
        self.assertEqual(lines, ["e⁽-(x-μ)²/2σ²⁾"])
        self.assertNotIn("─", "".join(lines))

    def test_the_normal_distribution_is_not_mangled(self):
        out = "\n".join(L.display(
            r"f(x)=\frac{1}{\sqrt{2\pi\sigma^2}}"
            r"e^{-\frac{(x-\mu)^2}{2\sigma^2}}"))
        self.assertIn("(x-μ)²/2σ²", out)
        # exactly one rule -- the outer fraction's; the inner one went linear
        self.assertEqual(sum("─" in line for line in out.split("\n")), 2)


class ArrayRuleTests(unittest.TestCase):
    def test_hline_draws_a_rule(self):
        lines = L.display(r"\begin{bmatrix} a & b \\ \hline c & d "
                          r"\end{bmatrix}")
        self.assertEqual(len(lines), 3)
        self.assertNotIn("hline", "".join(lines))
        self.assertIn("─", lines[1])

    def test_a_partitioned_transform_matrix(self):
        lines = L.display(r"\begin{bmatrix} R & t \\ \hline 0 & 1 "
                          r"\end{bmatrix}")
        self.assertNotIn("\\", "".join(lines))
        self.assertTrue(any(set(l.strip("⎡⎢⎣⎤⎥⎦ ")) == {"─"} for l in lines))

    def test_a_closing_hline_rules_under_the_last_row(self):
        lines = L.display(r"\begin{matrix} 1 & 1 \\ \hline 1 & 2 \\ \hline "
                          r"\end{matrix}")
        # ... and does not leave an empty row behind it
        self.assertEqual(len(lines), 4)
        self.assertEqual(set(lines[-1].strip("⎡⎢⎣⎤⎥⎦ ")), {"─"})

    def test_one_hline_draws_exactly_one_rule(self):
        lines = L.display(r"\begin{matrix} R & t \\ \hline 0 & 1 \end{matrix}")
        self.assertEqual(sum("─" in line for line in lines), 1)

    def test_hline_vanishes_inline(self):
        self.assertEqual(
            L.inline(r"\begin{bmatrix} a \\ \hline b \end{bmatrix}"),
            "[a; b]")


class SymbolTests(unittest.TestCase):
    def test_the_book_symbols_it_was_missing(self):
        self.assertEqual(L.inline(r"\Diamond"), "◇")
        self.assertEqual(L.inline(r"\rightrightarrows"), "⇉")

    def test_no_op_commands_vanish(self):
        self.assertEqual(L.inline(r"\displaystyle x"), "x")
        self.assertEqual(L.inline(r"a\enskip b"), "a b")
        self.assertEqual(L.inline(r"\arraycolsep=2pt x"), "x")

    def test_text_fonts_work_inside_maths(self):
        self.assertEqual(L.inline(r"\textbf{q}=1"), "q=1")
        self.assertEqual(L.inline(r"\textsl{calibrated}"), "calibrated")

    def test_overrightarrow_draws_an_arrow_over_its_argument(self):
        lines = L.display(r"\overrightarrow{AB}")
        self.assertEqual(lines, ["─→", "AB"])
        self.assertNotIn("overrightarrow", L.inline(r"\overrightarrow{AB}"))


class SmallFractionsAreDigitsOnly(unittest.TestCase):
    r"""The one-line fraction is tiny only where unicode does it well.

    ``0-9`` have a complete, well-drawn super/subscript set, so ``¹∕₇`` reads
    like the precomposed ``½`` beside it. The letter forms are patchy and
    small enough to misread -- ``\frac{r}{2}`` came out ``ʳ∕₂`` and
    ``\frac{a+b}{2}`` came out ``ᵃ⁺ᵇ∕₂`` -- so those are set plainly.
    """

    def test_a_precomposed_fraction_still_wins(self):
        self.assertEqual(L.inline(r"\frac{2}{3}"), "⅔")
        self.assertEqual(L.inline(r"\frac{1}{2}"), "½")

    def test_digits_are_set_tiny(self):
        self.assertEqual(L.inline(r"\frac{1}{7}"), "¹∕₇")
        self.assertEqual(L.inline(r"\frac{3}{16}"), "³∕₁₆")
        self.assertEqual(L.inline(r"\frac{12}{25}"), "¹²∕₂₅")

    def test_letters_are_set_plainly(self):
        self.assertEqual(L.inline(r"\frac{r}{2}"), "r/2")
        self.assertEqual(L.inline(r"\frac{n}{2}"), "n/2")
        self.assertEqual(L.inline(r"\frac{m}{s}"), "m/s")

    def test_anything_but_digits_is_plain_even_when_it_is_short(self):
        self.assertEqual(L.inline(r"\frac{2x}{3}"), "2x/3")
        self.assertEqual(L.inline(r"\frac{a+b}{2}"), "(a+b)/2")

    def test_digits_unicode_calls_digits_are_not_shrunk_again(self):
        # "²" and "٣" both satisfy str.isdigit(), so the rule is explicit
        # about ASCII rather than trusting that method.
        self.assertEqual(L.inline(r"\frac{²}{2}"), "²/2")
        self.assertEqual(L.inline(r"\frac{٣}{2}"), "٣/2")

    def test_a_long_run_of_digits_stays_plain(self):
        self.assertEqual(L.inline(r"\frac{1}{1000}"), "1/1000")

    def test_display_still_stacks_them_all(self):
        for src in (r"\frac{1}{7}", r"\frac{r}{2}", r"\frac{a+b}{2}"):
            lines = L.display(src)
            self.assertEqual(len(lines), 3, src)
            self.assertIn("─", lines[1], src)


class GlyphCoverageTests(unittest.TestCase):
    """A character Menlo cannot draw is an empty box to the reader."""

    MENLO = "/System/Library/Fonts/Menlo.ttc"

    def setUp(self):
        import os
        if not os.path.exists(self.MENLO):
            self.skipTest("Menlo not installed")

    def test_every_newly_emitted_character_is_drawable(self):
        from inkwell.sfnt import Face
        face = Face(self.MENLO, 0)
        emitted = set("".join(L.SUPER_CAPS.values()) + "".join(L.SUP_PAREN)
                      + "".join(L.SUB_PAREN) + "◇⇉─→")
        missing = sorted(c for c in emitted if not face.has(c))
        self.assertEqual(missing, [])

    # Symbols with no drawable monospace equivalent. Every one of these is a
    # character Menlo will not draw; they stay because the alternative is to
    # throw the meaning away, and no corpus note uses one. Anything NEW that
    # lands here has to be justified the same way.
    KNOWN_GAPS = set("∮⋃⋂≪≫∖⟹⟺⊥∥ℏℓℜℑℵ∴∵⊨⊢⋄") | {L.ACCENTS["vec"]}

    def test_no_new_undrawable_symbol_creeps_into_the_tables(self):
        from inkwell.sfnt import Face
        face = Face(self.MENLO, 0)
        from inkwell import pdf
        emitted = set()
        for table in (L.GREEK, L.SYMBOLS, L.ACCENTS, L.BLACKBOARD,
                      L.SUPERS, L.SUBS, L.VULGAR, L.SUPER_CAPS, L.SPACES):
            emitted.update("".join(table.values()))
        emitted.update(L.BIG_OPS, L.RELATIONS, L.SUP_PAREN, L.SUB_PAREN)
        emitted.update("".join("".join(v) for v in L.BRACKETS.values()))
        missing = {c for c in emitted
                   if c.strip() and not face.has(c) and c not in pdf.INSTEAD}
        self.assertEqual(missing, self.KNOWN_GAPS)

    def test_the_new_output_shapes_are_drawable(self):
        from inkwell.sfnt import Face
        face = Face(self.MENLO, 0)
        for src in (r"^A_BR", r"w_{i,j}^k", r"c_{\alpha\beta}", "E_d",
                    r"\Diamond", r"\rightrightarrows",
                    r"\begin{bmatrix} a & b \\ \hline c & d \end{bmatrix}",
                    r"e^{-\frac{(x-\mu)^2}{2\sigma^2}}"):
            text = L.inline(src) + "".join(L.display(src))
            bad = sorted({c for c in text if c.strip() and not face.has(c)})
            self.assertEqual(bad, [], src)


class ProseTests(unittest.TestCase):
    def test_dollar_spans_are_typeset_in_place(self):
        got = L.substitute(r"the law says $\Delta S \geq 0$ for isolated systems")
        self.assertEqual(got, "the law says ΔS ≥ 0 for isolated systems")

    def test_prose_without_maths_is_untouched(self):
        text = "costs $5 and change"
        self.assertEqual(L.substitute(text), text)

    def test_has_math(self):
        self.assertTrue(L.has_math("energy is $E=mc^2$ here"))
        self.assertFalse(L.has_math("no math at all"))


if __name__ == "__main__":
    unittest.main()


class GrownDelimiters(unittest.TestCase):
    r"""``\left[ ... \right]`` sizes to its contents, and only once.

    The book writes its homogeneous transforms as ``\left[\begin{array}
    ...\end{array}\right]``. A plain ``matrix`` carries no delimiters of its
    own in LaTeX, so the brackets must come from ``\left``/``\right`` -- and
    exactly one pair of them.
    """

    def page(self, src):
        return "\n".join(L.display(src))

    def test_left_right_round_a_matrix_do_not_double_up(self):
        page = self.page(r"\left[\begin{matrix}1 & 0\\0 & 1\end{matrix}\right]")
        self.assertNotIn("[", page)          # no flat bracket beside the tall one
        self.assertNotIn("]", page)
        self.assertIn("⎡", page)
        self.assertIn("⎦", page)

    def test_a_plain_matrix_brings_no_delimiters_of_its_own(self):
        page = self.page(r"\begin{matrix}1 & 0\\0 & 1\end{matrix}")
        for bracket in "[]⎡⎣⎤⎦":
            self.assertNotIn(bracket, page)

    def test_bmatrix_still_brings_its_own(self):
        self.assertIn("⎡", self.page(r"\begin{bmatrix}1\\0\end{bmatrix}"))

    def test_the_grown_bracket_is_as_tall_as_the_body(self):
        page = self.page(r"\left[\begin{matrix}1\\2\\3\end{matrix}\right]")
        self.assertEqual(len([r for r in page.split("\n") if "⎢" in r or "⎡" in r
                              or "⎣" in r]), 3)

    def test_inline_left_right_round_a_matrix_is_one_pair(self):
        out = L.inline(r"\left[\begin{matrix}a & b\end{matrix}\right]")
        self.assertEqual((out.count("["), out.count("]")), (1, 1))

    def test_a_dot_delimiter_is_invisible(self):
        page = self.page(r"\left.\begin{matrix}1\\2\end{matrix}\right]")
        self.assertNotIn(".", page)
        self.assertIn("⎤", page)

    def test_an_unmatched_right_still_prints_its_delimiter(self):
        self.assertIn(")", L.inline(r"a\right)"))


class SourceCharacters(unittest.TestCase):
    """Characters typed straight into the source that no face can draw."""

    def test_a_divides_sign_becomes_a_drawable_bar(self):
        out = L.inline("P(x∣y)")
        self.assertNotIn("∣", out)
        self.assertIn("|", out)

    def test_everything_that_survives_can_be_drawn(self):
        from inkwell.sfnt import Face
        from . import helpers
        face = Face(*helpers.a_monospace_face())
        for ch in L.inline("P(x∣y) and ∥v∥"):
            self.assertTrue(face.has(ch), f"U+{ord(ch):04X} {ch!r} has no glyph")
