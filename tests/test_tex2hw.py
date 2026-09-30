r"""tools/tex2hw.py turns one standalone LaTeX document into one notebook.

A homework sheet is the shape tex2ink does not do: its own preamble, its
own macros, a \maketitle title block, and \[...\] wrapped round arrays.
The contract is the same one tex2ink has -- every note is markup a person
could have typed -- plus the front matter, which is how you tell a
homework notebook from a chapter of a book.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inkwell import shaping as S           # noqa: E402
from inkwell import store                  # noqa: E402
from tools import tex2hw                   # noqa: E402

SHEET = r"""
\documentclass[11pt]{article}
\usepackage{amsmath}
\newcommand{\solutionspace}{%
  \vspace{0.2em}\noindent\textbf{Solution:}\par
}
\newcommand{\units}[1]{#1~\text{m}}
\begin{document}
\title{CSCI 3302: Robotics\\Homework 2: Odometry}
\date{Due: September 29, 2026, 11:59 PM}
\maketitle
\noindent
Submission: one PDF.\\[0.5em]
Resources: chapter 3.

\section*{Problem 1: Odometry \([34~\text{points}]\)}

The wheel speeds are constant:
\[
\begin{array}{c|cc}
\text{Segment} & \dot{\phi}_L & \dot{\phi}_R \\
\hline
1 & 4.0 & 4.0 \\
\end{array}
\]

\begin{enumerate}
  \item $[8~\text{pts}]$ The axle is \units{0.053}.
  \solutionspace
\end{enumerate}
\end{document}
"""


def convert(tex, **kw):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "HW2.tex"
        path.write_text(tex)
        return tex2hw.convert(path, **kw)


def texts(notes):
    return [n.text for n in notes]


class FrontMatter(unittest.TestCase):
    def setUp(self):
        self.notes = convert(SHEET, name="HW2", student="A. Student")

    def test_the_title_block_becomes_the_head_of_the_notebook(self):
        self.assertEqual(texts(self.notes)[:3],
                         ["# HW2",
                          "CSCI 3302: Robotics",
                          "Homework 2: Odometry"])

    def test_a_due_date_is_a_callout_because_it_has_a_deadline(self):
        due = [t for t in texts(self.notes) if "September" in t]
        self.assertEqual(due, ["!due: September 29, 2026, 11:59 PM"])
        self.assertEqual(S.classify(due[0]).kind, S.CALLOUT)

    def test_the_file_it_came_from_is_recorded(self):
        source = [t for t in texts(self.notes) if t.startswith("source:")]
        self.assertEqual(len(source), 1)
        self.assertTrue(source[0].endswith("HW2.tex"), source[0])

    def test_it_ends_with_the_thing_left_to_do(self):
        self.assertEqual(texts(self.notes)[-2:],
                         ["---", "TODO export to PDF and submit"])


class ThePreamble(unittest.TestCase):
    def test_nothing_above_begin_document_is_emitted(self):
        for text in texts(convert(SHEET)):
            self.assertNotIn(r"\documentclass", text)
            self.assertNotIn(r"\usepackage", text)
            self.assertNotIn(r"\newcommand", text)

    def test_a_macro_with_arguments_is_expanded_where_it_is_used(self):
        item = [t for t in texts(convert(SHEET)) if "axle" in t][0]
        self.assertTrue(item.endswith("The axle is 0.053 m."), item)
        self.assertNotIn(r"\units", item)

    def test_a_solution_placeholder_becomes_a_checkbox_to_tick(self):
        todo = [t for t in texts(convert(SHEET)) if t.strip() == "TODO solution"]
        self.assertEqual(len(todo), 1)
        self.assertEqual(S.classify(todo[0]).kind, S.CHECK)

    def test_a_macro_that_is_not_a_placeholder_keeps_its_own_body(self):
        notes = convert(SHEET.replace("solutionspace", "rubricnote")
                             .replace(r"\textbf{Solution:}", r"\textbf{Marks:}"))
        self.assertIn("**Marks:**", [t.strip() for t in texts(notes)])


class DisplayMaths(unittest.TestCase):
    r"""tex2ink looks for \begin before it looks for math, so a display
    built out of an environment has to be lifted out before it runs."""

    def test_an_array_inside_display_maths_stays_one_equation(self):
        math = [t for t in texts(convert(SHEET)) if t.startswith("$$")]
        self.assertEqual(len(math), 1)
        self.assertIn(r"\begin{matrix}", math[0])
        self.assertEqual(S.classify(math[0]).kind, S.MATH)

    def test_no_note_is_left_holding_a_bare_display_delimiter(self):
        for text in texts(convert(SHEET)):
            self.assertNotIn(r"\[", text)
            self.assertNotIn(r"\]", text)

    def test_round_brackets_are_inline_maths(self):
        head = [t for t in texts(convert(SHEET)) if t.startswith("## ")][0]
        self.assertEqual(head, r"## Problem 1: Odometry $[34 \text{points}]$")


class Prose(unittest.TestCase):
    def test_a_sized_line_break_ends_the_paragraph(self):
        body = texts(convert(SHEET))
        self.assertIn("Submission: one PDF.", body)
        self.assertIn("Resources: chapter 3.", body)

    def test_a_tie_is_a_space_not_a_tilde(self):
        for text in texts(convert(SHEET)):
            self.assertNotIn("~", text)


class Writing(unittest.TestCase):
    def test_it_writes_one_notebook_and_will_not_write_over_one(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "HW2.tex"
            source.write_text(SHEET)
            out = Path(folder) / "notes"
            argv = [str(source), "--out", str(out), "--notebook", "HW2"]
            quiet = io.StringIO()
            with contextlib.redirect_stdout(quiet), \
                    contextlib.redirect_stderr(quiet):
                self.assertEqual(tex2hw.main(argv), 0)
                written = out / "HW2.json"
                self.assertTrue(written.exists())
                self.assertEqual(texts(store.load(written))[0], "# HW2")
                self.assertEqual(tex2hw.main(argv), 1)      # already there
                self.assertEqual(tex2hw.main(argv + ["--force"]), 0)


if __name__ == "__main__":
    unittest.main()
