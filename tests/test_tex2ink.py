"""tools/tex2ink.py turns a LaTeX textbook into inkwell notebooks.

The contract is the *markup* it emits: every note has to be something a
person could have typed into the composer, so shaping.classify reads it
the way we intend (a section is a section, an equation is one line of
display math, a figure is not a table because its caption had two pipes).
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inkwell import shaping as S           # noqa: E402
from inkwell import store                  # noqa: E402
from tools import tex2ink                  # noqa: E402


def texts(notes):
    return [n.text for n in notes]


def kinds(notes):
    return [S.classify(n.text).kind for n in notes]


class Headings(unittest.TestCase):
    def test_chapter_section_subsection_are_numbered_markup(self):
        notes = tex2ink.notes(r"""
\chapter{Introduction}\label{chap:intro}
\section{Intelligence}
\subsection{Embodiment}
\subsubsection{Deeper}
""", chapter="1")
        self.assertEqual(texts(notes), ["# 1  Introduction",
                                        "## 1.1  Intelligence",
                                        "### 1.1.1  Embodiment",
                                        "### Deeper"])
        self.assertEqual(kinds(notes), [S.TITLE, S.SECTION, S.HEAD, S.HEAD])

    def test_starred_sections_are_not_numbered(self):
        notes = tex2ink.notes(r"\section*{Take-home lessons}", chapter="1")
        self.assertEqual(texts(notes), ["## Take-home lessons"])

    def test_appendix_chapters_are_lettered(self):
        notes = tex2ink.notes(r"\chapter{Trigonometry}\section{Sine}",
                              chapter="A")
        self.assertEqual(texts(notes), ["# A  Trigonometry", "## A.1  Sine"])

    def test_paragraph_command_is_a_bold_lead_in(self):
        notes = tex2ink.notes(r"\paragraph{Odometry} Counting wheel turns.")
        self.assertEqual(texts(notes), ["**Odometry.** Counting wheel turns."])
        self.assertEqual(kinds(notes), [S.PARA])


class Prose(unittest.TestCase):
    def test_blank_lines_split_paragraphs_and_comments_vanish(self):
        notes = tex2ink.notes("First para % a comment\nstill first.\n\n"
                              "Second para with 100\\% of it.\n%whole line\n")
        self.assertEqual(texts(notes), ["First para still first.",
                                        "Second para with 100% of it."])

    def test_inline_styling_becomes_inkwell_markup(self):
        notes = tex2ink.notes(r"Robots are \textsl{autonomous} and "
                              r"\emph{clever}, see \textbf{bold} "
                              r"and \texttt{code} and \textsc{Small}.")
        self.assertEqual(texts(notes), ["Robots are _autonomous_ and _clever_, "
                                        "see **bold** and `code` and Small."])

    def test_tex_ligatures_and_quotes(self):
        notes = tex2ink.notes("``Tonight Show'' appearance---so 1961--1966 "
                              "and `one' more~thing\\ldots")
        self.assertEqual(texts(notes), ["“Tonight Show” appearance—so "
                                        "1961–1966 and ‘one’ more thing…"])

    def test_index_and_label_are_dropped(self):
        notes = tex2ink.notes(r"An end-effector \index{End-effector} "
                              r"is a tool.\label{sec:x}")
        self.assertEqual(texts(notes), ["An end-effector is a tool."])

    def test_prose_is_pinned_to_para_so_heuristics_stay_out(self):
        # A short capitalised line would otherwise become a heading, and a
        # line ending in ":" a heading too -- these are prose in a book.
        notes = tex2ink.notes("See below.\n\nThe position is given by:")
        self.assertEqual([n.fmt for n in notes],
                         [{"block": S.PARA}, {"block": S.PARA}])
        self.assertEqual([S.classify(n.text).explicit for n in notes],
                         [False, False])
        # The trailing colon is U+A789 MODIFIER LETTER COLON: same look, not a heading.
        self.assertEqual(notes[1].text, "The position is given by\ua789")

    def test_pipes_in_prose_never_make_a_table_or_panes(self):
        notes = tex2ink.notes(r"The norm $||x||$ and $|y|$ and $|z|$ agree.")
        self.assertEqual(kinds(notes), [S.PARA])

    def test_maths_bars_are_left_for_the_typesetter(self):
        # They used to be swapped for U+2016 / U+2223 to stop the line
        # reading as a table -- but Menlo cannot draw either, so the reader
        # got an empty box. Shaping now ignores bars inside $...$ instead.
        notes = tex2ink.notes(r"Here $|\cdot|$ is the absolute value.")
        self.assertEqual(texts(notes), [r"Here $|\cdot|$ is the absolute value."])
        self.assertEqual(kinds(notes), [S.PARA])

    def test_every_character_the_converter_emits_can_be_drawn(self):
        from inkwell.sfnt import Face
        from . import helpers
        face = Face(*helpers.a_monospace_face())
        made = tex2ink.notes(r"""
The norm $\|x\|$ and $|y|$ agree.
\begin{tabular}{ll}
a $|v|$ b & c\\
\end{tabular}
""")
        for note in made:
            for ch in note.text:
                if ch in "\n\t":
                    continue
                self.assertTrue(face.has(ch),
                                f"U+{ord(ch):04X} {ch!r} has no glyph in Menlo")

    def test_footnote_url_and_href(self):
        notes = tex2ink.notes(r"See the site\footnote{Really.} at "
                              r"\url{http://x.org} or \href{http://y.org}{Y}.")
        self.assertEqual(texts(notes), ["See the site (Really.) at "
                                        "http://x.org or Y (http://y.org)."])

    def test_screencast_is_a_video_link_item(self):
        notes = tex2ink.notes(r"Text.\n\n\screencast{http://youtu.be/Q}{frame}")
        self.assertEqual(texts(notes)[-1], "- Video: http://youtu.be/Q")

    def test_forced_break_stays_inside_the_note(self):
        notes = tex2ink.notes(r"one line\\ next line")
        self.assertEqual(texts(notes), ["one line\nnext line"])

    def test_layout_only_commands_vanish(self):
        notes = tex2ink.notes(r"\noindent\small Words here.\normalsize"
                              r"\vspace{1cm}\newpage\centering")
        self.assertEqual(texts(notes), ["Words here."])


class Lists(unittest.TestCase):
    def test_itemize_and_enumerate(self):
        notes = tex2ink.notes(r"""
\begin{itemize}
\item drive
\item bounce
\end{itemize}
\begin{enumerate}
\item first
\item second
\end{enumerate}
""")
        self.assertEqual(texts(notes), ["- drive", "- bounce",
                                        "1. first", "2. second"])
        self.assertEqual(kinds(notes), [S.ITEM] * 4)

    def test_nested_lists_indent_two_spaces_per_level(self):
        notes = tex2ink.notes(r"""
\begin{itemize}
\item outer
  \begin{enumerate}
  \item inner one
  \item inner two
  \end{enumerate}
\item outer again
\end{itemize}
""")
        # A list inside a list is lettered, the way LaTeX prints it.
        self.assertEqual(texts(notes), ["- outer", "  (a) inner one",
                                        "  (b) inner two", "- outer again"])
        self.assertEqual([S.classify(t).level for t in texts(notes)],
                         [0, 1, 1, 0])

    def test_item_spanning_lines_is_one_note(self):
        notes = tex2ink.notes("\\begin{itemize}\n\\item a long\nitem here\n"
                              "\\end{itemize}")
        self.assertEqual(texts(notes), ["- a long item here"])

    def test_nested_enumerate_is_lettered_and_an_empty_item_keeps_its_number(self):
        # The book writes "\item" followed straight by a sub-list; LaTeX shows
        # "1. (a) ..." and so do we, rather than losing the 1.
        notes = tex2ink.notes(r"""
\begin{enumerate}
\item
\begin{enumerate}
\item first sub
\item second sub
\end{enumerate}
\item second
\end{enumerate}
""")
        self.assertEqual(texts(notes), ["1. (a) first sub", "  (b) second sub",
                                        "2. second"])
        self.assertEqual(kinds(notes), [S.ITEM] * 3)

    def test_item_options_are_dropped(self):
        notes = tex2ink.notes("\\begin{itemize}[noitemsep]\n\\item x\n"
                              "\\end{itemize}")
        self.assertEqual(texts(notes), ["- x"])


class Math(unittest.TestCase):
    def test_equation_is_one_line_of_display_maths(self):
        notes = tex2ink.notes("\\begin{equation}\n  x = \n \\frac{a}{b}\n"
                              "\\end{equation}")
        self.assertEqual(texts(notes), ["$$x = \\frac{a}{b}$$"])
        self.assertEqual(kinds(notes), [S.MATH])

    def test_labelled_equation_carries_its_number(self):
        notes = tex2ink.notes("\\begin{equation}\nx=1\\label{eq:one}\n"
                              "\\end{equation}", chapter="2")
        self.assertEqual(texts(notes), ["$$x=1 \\qquad (2.1)$$"])

    def test_eqnarray_splits_into_rows_without_ampersands(self):
        notes = tex2ink.notes(r"""
\begin{eqnarray}\label{eq:cos}
x_1 &=&l_1 \cos \alpha \nonumber \\
y_1 &=&l_1 \sin \alpha
\end{eqnarray}
""", chapter="3")
        self.assertEqual(texts(notes), ["$$x_1 = l_1 \\cos \\alpha$$",
                                        "$$y_1 = l_1 \\sin \\alpha \\qquad (3.1)$$"])
        self.assertEqual(kinds(notes), [S.MATH, S.MATH])

    def test_array_becomes_matrix_the_typesetter_knows(self):
        notes = tex2ink.notes(r"\begin{equation}p=\left[\begin{array}{c}1\\0"
                              r"\end{array}\right]\end{equation}")
        self.assertEqual(texts(notes),
                         [r"$$p=\left[\begin{matrix}1\\0\end{matrix}\right]$$"])

    def test_inline_maths_is_kept_verbatim(self):
        notes = tex2ink.notes(r"Let $\hat{X}_B$ be a unit vector, 100\%.")
        self.assertEqual(texts(notes), [r"Let $\hat{X}_B$ be a unit vector, 100%."])

    def test_boldsymbol_survives_inside_maths(self):
        notes = tex2ink.notes(r"\begin{equation}\boldsymbol{x}\end{equation}")
        self.assertEqual(texts(notes), [r"$$\boldsymbol{x}$$"])

    def test_display_dollar_pairs(self):
        notes = tex2ink.notes("Then\n$$ a = b $$\nnext.")
        self.assertEqual(texts(notes), ["Then", "$$a = b$$", "next."])


class MathsTypographicNoise(unittest.TestCase):
    """Print-only commands must not reach the reader's page.

    A terminal has no column spacing, no display/text style split and no
    bold inside math, so those commands carry no meaning here -- but
    anything that *does* mean something (a real accent, a real symbol) is
    left alone for inkwell.latex, which is the math typesetter.
    """

    def test_arraycolsep_assignment_is_dropped_from_display_maths(self):
        notes = tex2ink.notes(r"\begin{equation}A=\left[ \arraycolsep=2pt "
                              r"\begin{array}{c}1\\0\end{array}\right]"
                              r"\end{equation}")
        self.assertEqual(texts(notes),
                         [r"$$A=\left[ \begin{matrix}1\\0\end{matrix}\right]$$"])

    def test_dimension_assignments_are_handled_in_their_general_form(self):
        for src, want in [
            (r"x=1 \arraycolsep=2pt y", "x=1 y"),
            (r"x=1 \tabcolsep = 6pt y", "x=1 y"),
            (r"x=1 \baselineskip=1.5em y", "x=1 y"),
            (r"x=1 \parindent=0pt y", "x=1 y"),
            (r"x=1 \abovedisplayskip=10pt plus 2pt minus 3pt y", "x=1 y"),
            (r"x=1 \parskip=-.5ex y", "x=1 y"),
            (r"x=1 \textwidth=12cm y", "x=1 y"),
            (r"x=1 \fboxsep=2mm y", "x=1 y"),
            (r"x=1 \hoffset=1in y", "x=1 y"),
        ]:
            with self.subTest(src=src):
                notes = tex2ink.notes("\\begin{equation}%s\\end{equation}" % src)
                self.assertEqual(texts(notes), ["$$%s$$" % want])

    def test_a_real_equation_is_not_mistaken_for_a_dimension(self):
        notes = tex2ink.notes(r"\begin{equation}\lambda=2\pi\end{equation}")
        self.assertEqual(texts(notes), [r"$$\lambda=2\pi$$"])

    def test_displaystyle_is_a_no_op_and_enskip_is_a_space(self):
        notes = tex2ink.notes(r"\begin{equation}S=\displaystyle\sum_i x_i"
                              r"\end{equation}")
        self.assertEqual(texts(notes), [r"$$S=\sum_i x_i$$"])
        notes = tex2ink.notes(r"\begin{equation}A \enskip B\end{equation}")
        self.assertEqual(texts(notes), ["$$A B$$"])

    def test_text_styling_inside_maths_reduces_to_its_argument(self):
        notes = tex2ink.notes(r"Given $\textbf{K}$ and $\textsl{calibrated}$ "
                              r"and $\emph{q}$.")
        self.assertEqual(texts(notes),
                         ["Given $K$ and $calibrated$ and $q$."])

    def test_text_styling_inside_display_maths_reduces_too(self):
        notes = tex2ink.notes(r"\begin{equation}\textbf{f}(\textit{x})"
                              r"\end{equation}")
        self.assertEqual(texts(notes), ["$$f(x)$$"])

    def test_nested_styling_inside_maths_unwraps_all_the_way(self):
        notes = tex2ink.notes(r"$\textbf{\textsl{v}}$ is a vector.")
        self.assertEqual(texts(notes), ["$v$ is a vector."])

    def test_noise_is_stripped_from_inline_maths_as_well(self):
        notes = tex2ink.notes(r"Let $\arraycolsep=2pt \hat{X}$ be it.")
        self.assertEqual(texts(notes), [r"Let $\hat{X}$ be it."])

    def test_mathematical_text_commands_are_left_for_the_typesetter(self):
        # \text and \mathrm mean "upright, in math"; the typesetter knows
        # them, so they are meaning, not typography.
        notes = tex2ink.notes(r"\begin{equation}\text{if } x>0, "
                              r"\mathrm{d}x\end{equation}")
        self.assertEqual(texts(notes),
                         [r"$$\text{if } x>0, \mathrm{d}x$$"])

    def test_overrightarrow_is_a_real_accent_and_stays(self):
        # A vector arrow is meaning, not typography: inkwell.latex owns it.
        notes = tex2ink.notes(r"the ray $\overrightarrow{C_L p_c}$ is long.")
        self.assertEqual(texts(notes),
                         [r"the ray $\overrightarrow{C_L p_c}$ is long."])


class FiguresTablesBoxes(unittest.TestCase):
    def test_figure_is_a_numbered_caption(self):
        notes = tex2ink.notes(r"""
\begin{figure}
    \centering
    \def\svgwidth{\textwidth}
    \import{./figs/}{winduptoy.pdf_tex}
    \caption{A wind-up toy.}
    \label{fig:toy}
\end{figure}
""", chapter="1")
        self.assertEqual(texts(notes), ["> Figure 1.1: A wind-up toy."])
        self.assertEqual(kinds(notes), [S.QUOTE])

    def test_mdframed_is_a_callout(self):
        notes = tex2ink.notes("\\begin{mdframed}\nThink about it.\n\\end{mdframed}")
        self.assertEqual(texts(notes), ["!Think about it."])
        self.assertEqual(kinds(notes), [S.CALLOUT])

    def test_tabular_rows_become_pipe_rows(self):
        notes = tex2ink.notes(r"""
\begin{table}
\begin{tabular}{lcc}
\hline
 & Wall & Door\\
\hline
Nothing & 70\% & 40\%\\
\hline
\end{tabular}
\caption{Odds.\label{tab:odds}}
\end{table}
""", chapter="4")
        # An empty cell needs a visible stand-in: classify strips leading
        # pipes and spaces, so a bare "| Wall" would lose its first column.
        self.assertEqual(texts(notes), ["— | Wall | Door",
                                        "Nothing | 70% | 40%",
                                        "> Table 4.1: Odds."])
        self.assertEqual(kinds(notes), [S.TABLE, S.TABLE, S.QUOTE])

    def test_a_list_inside_a_table_cell_is_flattened(self):
        notes = tex2ink.notes(r"""
\begin{tabular}{ll}
Standard & Two:
\begin{itemize}
\item around the axle
\item around the contact point
\end{itemize}\\
\end{tabular}
""")
        self.assertEqual(texts(notes),
                         ["Standard | Two: around the axle; around the contact point"])

    def test_verbatim_is_a_run_of_code_lines(self):
        notes = tex2ink.notes("\\begin{verbatim}\nfor i in x:\n    go()\n"
                              "\\end{verbatim}")
        self.assertEqual(texts(notes), ["`for i in x:`", "`    go()`"])
        self.assertEqual(kinds(notes), [S.CODE, S.CODE])

    def test_plain_verbatim_prints_its_dollars_literally(self):
        # \begin{verbatim} really does print "$" -- so this is faithful.
        notes = tex2ink.notes("\\begin{verbatim}\ncost = $5\n\\end{verbatim}")
        self.assertEqual(texts(notes), ["`cost = $5`"])

    def test_verbatim_that_switches_maths_back_on_is_typeset(self):
        # The book's Bayes-filter listing opens with
        #   \begin{Verbatim}[codes={\catcode`$=3 ...}]
        # which restores "$" as the math shift, so the book shows "x in X"
        # set as math, not the dollars.  A code note is never re-typeset by
        # the reader, so the math is reduced to text here.
        notes = tex2ink.notes(
            "\\begin{Verbatim}[commandchars=\\\\\\{\\}, "
            "codes={\\catcode`$=3\\catcode`^=7\\catcode`_=8}]\n"
            "      for all $x \\in X$:\n"
            "\\end{Verbatim}")
        self.assertEqual(texts(notes), ["`      for all x \u2208 X:`"])
        self.assertEqual(kinds(notes), [S.CODE])

    def test_maths_in_a_live_verbatim_leaves_no_tex_behind(self):
        notes = tex2ink.notes(
            "\\begin{Verbatim}[codes={\\catcode`$=3}]\n"
            "        Bel'(x) = $\\sum_{x_{t-1}}P(x|u,x_{t-1})*$Bel$(x_{t-1})$\n"
            "\\end{Verbatim}")
        self.assertEqual(len(notes), 1)
        line = notes[0].text
        self.assertNotIn("$", line)
        self.assertNotIn("\\", line)
        self.assertIn("Bel'(x) =", line)      # the code itself is untouched
        self.assertEqual(S.classify(line).kind, S.CODE)

    def test_unrenderable_environments_leave_a_marker(self):
        notes = tex2ink.notes("\\begin{forest}\n[a [b] [c]]\n\\end{forest}")
        self.assertEqual(texts(notes), ["> [tree diagram omitted]"])


class References(unittest.TestCase):
    TEX = r"""
\chapter{Kinematics}\label{chap:kin}
\section{Forward}\label{sec:fwd}
\begin{figure}\caption{Arm.}\label{fig:arm}\end{figure}
\begin{equation}x=1\label{eq:x}\end{equation}
See \cref{fig:arm}, \cref{sec:fwd}, \cref{eq:x}, \eqref{eq:x},
\cref{chap:kin}, \nameref{sec:fwd} and \ref{fig:arm}.
"""

    def test_references_resolve_to_numbers_in_a_second_pass(self):
        notes = tex2ink.notes(self.TEX, chapter="3")
        self.assertEqual(texts(notes)[-1],
                         "See Figure 3.1, Section 3.1, Equation (3.1), (3.1), "
                         "Chapter 3, Forward and 3.1.")

    def test_labels_from_other_chapters_resolve_across_the_book(self):
        book = tex2ink.Labels()
        tex2ink.notes(self.TEX, chapter="3", labels=book)
        notes = tex2ink.notes(r"Back in \cref{sec:fwd}.", chapter="5", labels=book)
        self.assertEqual(texts(notes), ["Back in Section 3.1."])

    def test_doubled_braces_in_a_label_are_forgiven(self):
        notes = tex2ink.notes(self.TEX + r" Also \cref{{eq:x}}.", chapter="3")
        self.assertTrue(texts(notes)[-1].endswith("Also Equation (3.1)."))

    def test_unknown_reference_is_marked_not_crashed(self):
        notes = tex2ink.notes(r"See \cref{fig:nope}.")
        self.assertEqual(texts(notes), ["See [fig:nope]."])


class Citations(unittest.TestCase):
    BIB = r"""
@article{otte2012,
title = {C-FOREST},
author = {M. Otte and N. Correll},
year = {2013},
}
@article{watson2020autonomous,
  author={Watson, James and Miller, Austin and Correll, Nikolaus},
  year={2020},
}
@book{thrun,
  author={Thrun, Sebastian},
  year={2005},
}
"""

    def test_citations_become_author_year(self):
        bib = tex2ink.Bibliography.parse(self.BIB)
        notes = tex2ink.notes(r"Shown by \cite{otte2012} and "
                              r"\cite{watson2020autonomous,thrun}.", bib=bib)
        self.assertEqual(texts(notes), ["Shown by (Otte and Correll 2013) and "
                                        "(Watson et al. 2020; Thrun 2005)."])

    def test_citeasnoun_is_a_citation_too(self):
        bib = tex2ink.Bibliography.parse(self.BIB)
        notes = tex2ink.notes(r"From \protect\citeasnoun{thrun}.", bib=bib)
        self.assertEqual(texts(notes), ["From (Thrun 2005)."])

    def test_unknown_citation_keeps_its_key(self):
        notes = tex2ink.notes(r"As in \cite{ghost}.")
        self.assertEqual(texts(notes), ["As in [ghost]."])


class WholeBook(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "chapters").mkdir()
        (self.root / "book.tex").write_text(r"""
\begin{document}
\chapter*{Preface}
Hello.
\input{chapters/introduction}
\part{Mechanisms}
\input{chapters/locomotion}
\part{Appendices}
\appendix
\input{chapters/trigonometry}
\end{document}
""")
        (self.root / "chapters/introduction.tex").write_text(
            "\\chapter{Introduction}\nIntro text, see \\cref{sec:wheels}.")
        (self.root / "chapters/locomotion.tex").write_text(
            "\\chapter{Locomotion}\n\\section{Wheels}\\label{sec:wheels}\nRound.")
        (self.root / "chapters/trigonometry.tex").write_text(
            "\\chapter{Trigonometry}\nSine.")
        (self.root / "robotics.bib").write_text("")

    def test_book_becomes_one_notebook_per_chapter_in_reading_order(self):
        out = self.root / "out"
        written = tex2ink.convert(self.root, out, prefix="IAR")
        self.assertEqual([p.name for p in written],
                         ["iar-00-preface.json", "iar-01-introduction.json",
                          "iar-02-locomotion.json", "iar-a-trigonometry.json"])
        intro = store.load(written[1])
        self.assertEqual(texts(intro), ["# 1  Introduction",
                                        "Intro text, see Section 2.1."])
        appendix = store.load(written[3])
        self.assertEqual(texts(appendix)[0], "# A  Trigonometry")
        # The open dialog sorts by mtime: reading order must be newest-first.
        stamps = [p.stat().st_mtime for p in written]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_a_chapter_may_input_its_own_subfiles(self):
        (self.root / "chapters/locomotion.tex").write_text(
            "\\chapter{Locomotion}\n\\input{chapters/wheels}\nAfter.")
        (self.root / "chapters/wheels.tex").write_text(
            "\\section{Wheels}\\label{sec:wheels}\nRound.")
        written = tex2ink.convert(self.root, self.root / "out", prefix="IAR")
        loco = store.load(written[2])
        self.assertEqual(texts(loco), ["# 2  Locomotion", "!Part: Mechanisms",
                                       "## 2.1  Wheels", "Round.", "After."])
        intro = store.load(written[1])
        self.assertEqual(texts(intro)[-1], "Intro text, see Section 2.1.")

    def test_notebooks_are_plain_store_files(self):
        written = tex2ink.convert(self.root, self.root / "out", prefix="IAR")
        raw = json.loads(written[1].read_text())
        self.assertEqual(set(raw[0]), {"text", "created", "fmt", "tag",
                                       "emphasis", "done"})

    def test_part_notes_go_in_the_chapter_that_opens_them(self):
        written = tex2ink.convert(self.root, self.root / "out", prefix="IAR")
        loco = store.load(written[2])
        self.assertEqual(texts(loco)[:2], ["# 2  Locomotion",
                                           "!Part: Mechanisms"])


if __name__ == "__main__":
    unittest.main()
