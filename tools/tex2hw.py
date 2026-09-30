#!/usr/bin/env python3
r"""Turn one standalone LaTeX document -- a homework sheet, a handout -- into
one inkwell notebook.

    python3 tools/tex2hw.py ~/Downloads/HW2/HW2.tex
    python3 tools/tex2hw.py HW2.tex --notebook HW2 --student "A. Student"

``tex2ink.py`` converts a *book*: many chapter files, each one already
inside ``\begin{document}``, none of them carrying a preamble.  A homework
sheet is the other shape -- a single file with its own preamble, its own
``\newcommand`` macros, a ``\maketitle`` title block, and ``\[...\]``
wrapped round arrays and matrices.  This handles that shape and then hands
the body to tex2ink's converter, so a homework page and a textbook page
come out looking like the same document.

What it does that tex2ink alone does not:

* the preamble is *read*, not emitted -- ``\newcommand`` definitions are
  expanded into the body, everything else above ``\begin{document}`` goes
* a no-argument macro whose name says "solution" is the blank space a
  question leaves you to write in, so it becomes ``TODO solution``: a
  checkbox to tick as you work, which is what the space is *for*
* ``\title`` / ``\author`` / ``\date`` become the notebook's front matter
  -- a title, a ``due:`` pair, the file it came from -- instead of prose
* ``\(...\)`` is inline math, the same as ``$...$``
* ``\[...\]`` and ``$$...$$`` are lifted out before the block scanner runs.
  tex2ink looks for ``\begin`` first, so a display wrapped round
  ``\begin{array}`` or ``\begin{bmatrix}`` otherwise comes apart around its
  own ``\begin`` and leaves the ``\[`` and ``\]`` behind as prose
* ``\\[1em]`` ends a paragraph -- a handout separates its opening lines
  that way rather than with blank ones -- and ``~`` is a space

Honest gaps: macros are expanded textually (``#1``..``#9``, no optional
arguments, no ``\def``), and ``~`` becomes a space inside ``verbatim`` too.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inkwell import store                  # noqa: E402
from tools import tex2ink                  # noqa: E402

DOCUMENT = re.compile(r"\\begin\{document\}(.*)\\end\{document\}", re.S)
DEFINE = re.compile(r"\\(?:new|renew|provide)command\*?\s*"
                    r"(?:\{\s*\\([A-Za-z]+)\s*\}|\\([A-Za-z]+))\s*"
                    r"(?:\[(\d+)\])?\s*(?:\[[^\]]*\])?\s*(?=\{)")
DISPLAY = re.compile(r"\\\[(.+?)\\\]|(?<!\\)\$\$(.+?)\$\$", re.S)
LINEBREAK = re.compile(r"\\\\\s*\[[^\]]*\]")
NBSP = re.compile(r"(?<!\\)~")
# A question that prints blank space for you to write in names the macro
# after what goes there.  "\solutionspace", "\answerbox", "\yoursolution".
PLACEHOLDER = re.compile(r"solution|answer", re.I)
SENTINEL = "\u0000D%d\u0000"
_SENTINEL_RE = re.compile(r"^\x00D(\d+)\x00$")


# --- reading the source -----------------------------------------------------
def _pull(tex: str, name: str) -> tuple[str, str]:
    r"""Take ``\name{...}`` out of *tex* -> (its argument, what is left)."""
    m = re.search(r"\\" + name + r"\s*(?=\{)", tex)
    if not m:
        return "", tex
    inner, end = tex2ink._group(tex, m.end())
    return inner.strip(), tex[:m.start()] + tex[end:]


def macros(tex: str) -> dict:
    r"""Every ``\newcommand`` in *tex* -> {name: (argument count, body)}."""
    found = {}
    for m in DEFINE.finditer(tex):
        body, _ = tex2ink._group(tex, m.end())
        found[m.group(1) or m.group(2)] = (int(m.group(3) or 0), body)
    return found


def drop_definitions(tex: str) -> str:
    """The same text with its ``\\newcommand`` lines gone."""
    while True:
        m = DEFINE.search(tex)
        if not m:
            return tex
        _body, end = tex2ink._group(tex, m.end())
        tex = tex[:m.start()] + tex[end:]


def expand(tex: str, defined: dict, rounds: int = 8) -> str:
    """Replace each defined macro with what it stands for.

    A no-argument macro named for a solution is not expanded to the space
    it prints; it becomes the checkbox that space is asking you to fill.
    """
    if not defined:
        return tex
    pattern = re.compile(r"\\(" + "|".join(sorted(map(re.escape, defined),
                                                  key=len, reverse=True))
                         + r")(?![A-Za-z])")
    for _ in range(rounds):
        m = pattern.search(tex)
        if not m:
            break
        while m:
            count, body = defined[m.group(1)]
            end = m.end()
            if count == 0 and PLACEHOLDER.search(m.group(1)):
                body = "\n\nTODO solution\n\n"
            else:
                args = []
                for _i in range(count):
                    at = tex2ink._ws(tex, end)
                    arg, end = tex2ink._group(tex, at)
                    args.append(arg)
                for i, arg in enumerate(args, 1):
                    body = body.replace(f"#{i}", arg)
            tex = tex[:m.start()] + body + tex[end:]
            m = pattern.search(tex, m.start() + len(body))
    return tex


# --- math the block scanner must not see -----------------------------------
def protect(tex: str) -> tuple[str, list]:
    r"""Lift every display out of *tex*, leaving a paragraph of its own.

    tex2ink walks ``\begin`` before it walks math, so a display built out
    of ``\begin{array}`` has to be gone before it looks.
    """
    held: list[str] = []

    def take(m):
        body = tex2ink._math_clean(m.group(1) or m.group(2))
        held.append(f"$${body}$$" if body else "")
        return f"\n\n{SENTINEL % (len(held) - 1)}\n\n"

    return DISPLAY.sub(take, tex), held


def restore(notes: list, held: list) -> list:
    """Put each display back into the note standing in for it."""
    kept = []
    for note in notes:
        m = _SENTINEL_RE.match(note.text.strip())
        if not m:
            kept.append(note)
            continue
        display = held[int(m.group(1))]
        if not display:
            continue
        indent = note.text[:len(note.text) - len(note.text.lstrip())]
        note.text, note.fmt = indent + display, {}
        kept.append(note)
    return kept


# --- the whole thing --------------------------------------------------------
def front_matter(name: str, title: str, author: str, date: str,
                 source: Path) -> list:
    """The head of the notebook: what this is, when it is due, where from."""
    inline = tex2ink._Converter("", None, None)._inline
    out = [store.Note(f"# {name}")]
    for line in [ln.strip() for ln in re.split(r"\\\\", title) if ln.strip()]:
        out.append(store.Note(inline(line), fmt=tex2ink.PARA_FMT))
    if author:
        out.append(store.Note(f"name: {author}"))
    try:
        shown = "~/" + str(source.resolve().relative_to(Path.home()))
    except ValueError:
        shown = str(source.resolve())
    out.append(store.Note(f"source: {shown}"))
    # A date is the one fact on a homework sheet with a deadline attached,
    # and it is usually too long to align as a pair -- so it is a callout,
    # which is what a callout is for.
    if date:
        out.append(store.Note("!due: " + re.sub(r"^due:?\s*", "", date,
                                                flags=re.I)))
    return out


def convert(path, name: str = "", student: str = "") -> list:
    """One LaTeX file -> the notes of one notebook."""
    path = Path(path)
    src = tex2ink.strip_comments(path.read_text(encoding="utf-8",
                                                errors="replace"))
    found = DOCUMENT.search(src)
    body = found.group(1) if found else src
    defined = macros(src)
    body = expand(drop_definitions(body), defined)

    title, body = _pull(body, "title")
    author, body = _pull(body, "author")
    date, body = _pull(body, "date")
    if not found or not title:
        title = title or _pull(src, "title")[0]
        author = author or _pull(src, "author")[0]
        date = date or _pull(src, "date")[0]

    body = body.replace(r"\(", "$").replace(r"\)", "$")
    body = LINEBREAK.sub("\n\n", body)
    body = NBSP.sub(" ", body)
    body, held = protect(body)

    made = restore(tex2ink.notes(body, root=path.parent), held)
    head = front_matter(name or path.stem, title, student, date, path)
    return head + made + [store.Note("---"),
                          store.Note("TODO export to PDF and submit")]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("file", type=Path, help="the .tex to convert")
    parser.add_argument("--out", type=Path, default=store.DEFAULT_DIR,
                        help=f"notes folder (default: {store.DEFAULT_DIR})")
    parser.add_argument("--notebook", default="",
                        help="what to call it (default: the file's own name)")
    parser.add_argument("--student", default="",
                        help="a name to put in the front matter")
    parser.add_argument("--force", action="store_true",
                        help="write over a notebook that is already there")
    args = parser.parse_args(argv)

    name = args.notebook or args.file.stem
    made = convert(args.file, name, args.student)
    folder = store.ensure(args.out)
    path = folder / (name + store.SUFFIX)
    if path.exists() and not args.force:
        print(f"{path} is already there -- --force writes over it",
              file=sys.stderr)
        return 1
    store.save(made, path)
    print(f"{len(made):5d} notes  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
