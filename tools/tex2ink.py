#!/usr/bin/env python3
"""Turn a LaTeX textbook into inkwell notebooks, one per chapter.

    python3 tools/tex2ink.py ~/some-latex-book
    python3 tools/tex2ink.py BOOK_DIR --out ~/Documents/Inkwell
    python3 tools/tex2ink.py BOOK_DIR --prefix IAR --title "Some Book"

The book's ``book.tex`` names the reading order (``\\input{chapters/...}``,
``\\part``, ``\\appendix``); each chapter becomes ``<prefix>-<nn>-<title>.json``
in the notes folder, written so the open dialog lists them in reading order.

Everything emitted is *markup a person could have typed*: ``## 1.2  Title``
for a section, ``- item`` for a bullet, one ``$$...$$`` line per equation,
``> Figure 1.3: caption`` where a figure was (the drawings themselves are
PDFs and cannot be shown in a terminal), ``a | b | c`` for a table row.
Prose is pinned to ``fmt={"block": "para"}`` so the composer's heuristics
(a short capitalised line is a heading, a line ending in ":" too) stay out
of a book. References (``\\cref``) resolve to "Figure 1.3" / "Section 2.1"
across the whole book; citations resolve to (Author Year) from the .bib.

Honest gaps: figures are captions only; ``forest``/``tikz`` diagrams leave a
marker; LaTeX commands this script does not know are passed through
verbatim rather than silently dropped, so they can be found.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inkwell import latex                  # noqa: E402
from inkwell import reader                 # noqa: E402
from inkwell import shaping as S           # noqa: E402
from inkwell import store                  # noqa: E402

PARA_FMT = {"block": S.PARA}
EMPTY_CELL = "—"


# --- small TeX scanners -----------------------------------------------------
def _group(text: str, pos: int) -> tuple[str, int]:
    """The balanced ``{...}`` at *pos* -> (inner, index after the ``}``)."""
    if pos >= len(text) or text[pos] != "{":
        return "", pos
    depth = 0
    i = pos
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[pos + 1:i], i + 1
        i += 1
    return text[pos + 1:], len(text)


def _ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \t\n":
        pos += 1
    return pos


def _opt(text: str, pos: int) -> int:
    """Skip an optional ``[...]`` argument if one sits at *pos*."""
    if pos < len(text) and text[pos] == "[":
        depth = 0
        for i in range(pos, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    return i + 1
    return pos


def _arg(text: str, pos: int) -> tuple[str, int]:
    """One mandatory argument: a group, or the single token that follows."""
    pos = _ws(text, pos)
    if pos < len(text) and text[pos] == "{":
        return _group(text, pos)
    if pos < len(text) and text[pos] == "\\":
        m = re.match(r"\\[A-Za-z]+|\\.", text[pos:])
        return m.group(0), pos + len(m.group(0))
    return text[pos:pos + 1], min(pos + 1, len(text))


_COMMENT = re.compile(r"(?<!\\)%[^\n]*")


def strip_comments(tex: str) -> str:
    return _COMMENT.sub("", tex)


_ENV_EDGE = re.compile(r"\\(begin|end)\{([A-Za-z*]+)\}")


def _env_body(tex: str, name: str, start: int) -> tuple[str, int]:
    """Text inside ``\\begin{name}``...``\\end{name}`` and the index after."""
    depth = 1
    for m in _ENV_EDGE.finditer(tex, start):
        if m.group(2) != name:
            continue
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return tex[start:m.start()], m.end()
    return tex[start:], len(tex)


def _split_depth0(tex: str, sep_re: str) -> list[str]:
    """Split on *sep_re* only outside nested environments and braces."""
    out, depth, brace, last = [], 0, 0, 0
    token = re.compile(sep_re + r"|\\begin\{[A-Za-z*]+\}|\\end\{[A-Za-z*]+\}"
                       r"|\\\\|\\.|[{}]")
    for m in token.finditer(tex):
        t = m.group(0)
        if t.startswith("\\begin"):
            depth += 1
        elif t.startswith("\\end"):
            depth -= 1
        elif t == "{":
            brace += 1
        elif t == "}":
            brace -= 1
        elif depth == 0 and brace == 0 and re.fullmatch(sep_re, t):
            out.append(tex[last:m.start()])
            last = m.end()
    out.append(tex[last:])
    return out


# --- the .bib ---------------------------------------------------------------
class Bibliography(dict):
    """key -> (authors, year), enough for an (Author Year) citation."""

    @classmethod
    def parse(cls, text: str) -> "Bibliography":
        bib = cls()
        for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
            body, _end = _group(text, text.index("{", m.start()))
            fields = {}
            pos = 0
            while True:
                fm = re.compile(r"(\w+)\s*=\s*").search(body, pos)
                if not fm:
                    break
                name = fm.group(1).lower()
                pos = fm.end()
                if pos < len(body) and body[pos] == "{":
                    value, pos = _group(body, pos)
                elif pos < len(body) and body[pos] == '"':
                    end = body.find('"', pos + 1)
                    value, pos = body[pos + 1:end], end + 1
                else:
                    vm = re.compile(r"[^,\n]*").match(body, pos)
                    value, pos = vm.group(0), vm.end()
                fields[name] = value.strip()
            if "author" in fields or "year" in fields:
                bib[m.group(2)] = (fields.get("author", ""), fields.get("year", ""))
        return bib

    def cite(self, key: str) -> str | None:
        if key not in self:
            return None
        authors, year = self[key]
        names = []
        for author in re.split(r"\s+and\s+", authors):
            author = re.sub(r"[{}]", "", author).strip()
            if not author:
                continue
            if "," in author:
                names.append(author.split(",")[0].strip())
            else:
                names.append(author.split()[-1])
        if not names:
            who = key
        elif len(names) == 1:
            who = names[0]
        elif len(names) == 2:
            who = f"{names[0]} and {names[1]}"
        else:
            who = f"{names[0]} et al."
        return f"{who} {year}".strip()


# --- labels -----------------------------------------------------------------
class Labels(dict):
    """label -> (kind, number, name); shared across a book's chapters."""


_WORD = {"fig": "Figure", "tab": "Table", "eq": "Equation", "sec": "Section",
         "chap": "Chapter"}


def _resolve(labels: Labels, how: str, label: str) -> str:
    label = label.strip("{} ")
    entry = labels.get(label)
    if not entry:
        return f"[{label}]"
    kind, number, name = entry
    if how == "nameref":
        return name or number
    if how == "eqref":
        return f"({number})"
    if how in ("ref", "pageref"):
        return number
    if kind == "eq":
        return f"Equation ({number})"
    return f"{_WORD.get(kind, kind.capitalize())} {number}"


# --- the converter ----------------------------------------------------------
CODE = "\x00C\x00"
STYLE = {"textsl": "_", "emph": "_", "textit": "_", "textbf": "**", "texttt": CODE}
PLAIN = {"textsc", "textrm", "text", "mbox", "textnormal", "textsf", "textup",
         "textmd", "hjb", "td", "ar", "nc", "bh", "added", "fbox", "underline",
         "uppercase", "MakeUppercase", "MakeLowercase", "lowercase", "textsuperscript",
         "textsubscript", "replaced", "nameref_", "section_"}
DROP_ARGS = {"index": 1, "vspace": 1, "hspace": 1, "import": 2, "includegraphics": 1,
             "marginnote": 1, "todo": 1, "deleted": 1, "pagestyle": 1,
             "thispagestyle": 1, "setlength": 2, "rule": 2, "hypersetup": 1,
             "bibliographystyle": 1, "bibliography": 1, "phantom": 1,
             "addcontentsline": 3, "markboth": 2, "markright": 1, "cline": 1,
             "multicolumn": 3, "parbox": 2, "hyphenation": 1, "svgwidth": 0,
             "pdfbookmark": 2}
SYMBOLS = {"ldots": "…", "dots": "…", "textendash": "–", "textemdash": "—",
           "LaTeX": "LaTeX", "LaTeXe": "LaTeX2e", "TeX": "TeX", "degree": "°", "textdegree": "°",
           "copyright": "©", "textregistered": "®", "texttrademark": "™",
           "textbackslash": "\\", "textbar": "|", "textless": "<",
           "textgreater": ">", "textasciitilde": "~", "textquotedblleft": "“",
           "textquotedblright": "”", "textquoteleft": "‘", "textquoteright": "’",
           "S": "§", "P": "¶", "pounds": "£", "euro": "€", "today": ""}
LAYOUT = {"noindent", "centering", "small", "normalsize", "scriptsize",
          "footnotesize", "tiny", "large", "Large", "LARGE", "huge", "Huge",
          "bf", "it", "em", "sf", "tt", "rm", "sc", "bfseries", "itshape",
          "newpage", "clearpage", "cleardoublepage", "vfill", "hfill", "par",
          "indent", "raggedright", "raggedleft", "allowdisplaybreaks", "makeindex",
          "maketitle", "tableofcontents", "printindex", "frontmatter",
          "mainmatter", "backmatter", "smallskip", "medskip", "bigskip",
          "protect", "relax", "nonumber", "notag", "linewidth", "textwidth",
          "columnwidth", "textheight", "parindent", "baselineskip", "hline",
          "toprule", "midrule", "bottomrule", "newline_", "strut", "null",
          "selectfont", "normalfont", "unskip", "ignorespaces", "flushleft",
          "flushright", "linebreak_", "hspace_", "displaystyle", "nobreak",
          "leavevmode", "hbox", "sloppy", "fussy", "onecolumn", "twocolumn",
          "appendix", "hyphenpenalty", "exhyphenpenalty", "columnbreak",
          "pagebreak", "nopagebreak", "samepage", "enlargethispage"}
REFS = {"cref", "Cref", "ref", "eqref", "nameref", "autoref", "pageref", "vref"}
CITES = {"cite", "citep", "citet", "citeauthor", "citeyear", "citealp", "citealt",
         "citeasnoun", "possessivecite", "citeyearpar"}
BR = "\x00BR\x00"

_CMD = re.compile(r"\\([A-Za-z]+\*?|[^A-Za-z\s]|\s)")
_HEADING = re.compile(r"\\(chapter|section|subsection|subsubsection|paragraph)"
                      r"(\*?)\s*(?=\{)")
_DISPLAY = re.compile(r"(?<!\\)\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
_INLINE_MATH = re.compile(r"(?<!\\)\$[^$\n]+?\$")
_LABEL = re.compile(r"\\label\{([^}]*)\}")
_BLANK = re.compile(r"\n[ \t]*\n")
_BEGIN = re.compile(r"\\begin\{([A-Za-z*]+)\}")
_REF_MARK = re.compile(r"\x00R(\w+):([^\x00]*)\x00")
_MATH_CATCODE = re.compile(r"\\catcode\s*`?\\?\$\s*=\s*3")

LIST_ENVS = {"itemize", "enumerate", "description"}
MATH_ENVS = {"equation", "equation*", "displaymath", "eqnarray", "eqnarray*",
             "align", "align*", "gather", "gather*", "multline", "multline*",
             "flalign", "flalign*", "alignat", "alignat*"}
ALIGNED = {"eqnarray", "eqnarray*", "align", "align*", "flalign", "flalign*",
           "alignat", "alignat*"}
DIAGRAMS = {"forest": "tree diagram", "tikzpicture": "diagram",
            "tikzcd": "diagram", "pgfpicture": "diagram"}
TRANSPARENT = {"center", "flushleft", "flushright", "scriptsize", "small",
               "footnotesize", "normalsize", "large", "singlespace", "sloppypar",
               "samepage", "raggedright", "document"}


class _Converter:
    def __init__(self, chapter: str, labels: Labels | None, bib: Bibliography | None,
                 part: str | None = None, root: Path | None = None):
        self.chapter = chapter
        self.root = root
        self.labels = labels if labels is not None else Labels()
        self.bib = bib or Bibliography()
        self.part = part
        self.sec = self.sub = self.fig = self.tab = self.eq = 0
        self.current = ("chap", chapter, "")
        self.lead: str | None = None
        self.notes: list[store.Note] = []

    # -- numbering ----------------------------------------------------------
    def _num(self, *parts) -> str:
        head = [self.chapter] if self.chapter else []
        return ".".join(head + [str(p) for p in parts])

    # -- output -------------------------------------------------------------
    def _emit(self, text: str, fmt: dict | None = None) -> None:
        if text.strip():
            self.notes.append(store.Note(text, fmt=dict(fmt) if fmt else {}))

    # -- top level ----------------------------------------------------------
    def run(self, tex: str) -> None:
        self._blocks(_expand_inputs(strip_comments(tex), self.root), "", None, "")

    def finish(self) -> list:
        for note in self.notes:
            note.text = _REF_MARK.sub(
                lambda m: ", ".join(_resolve(self.labels, m.group(1), lab.strip())
                                    for lab in m.group(2).split(",")),
                note.text)
        return self.notes

    # -- blocks -------------------------------------------------------------
    def _blocks(self, tex: str, indent: str, marker: str | None, prefix: str) -> str | None:
        """Walk *tex*, emitting notes. Returns the marker if nothing took it."""
        pos = 0
        while True:
            m = _BEGIN.search(tex, pos)
            if not m:
                return self._prose(tex[pos:], indent, marker, prefix)
            marker = self._prose(tex[pos:m.start()], indent, marker, prefix)
            name = m.group(1)
            inner, pos = _env_body(tex, name, m.end())
            marker = self._env(name, inner, indent, marker, prefix)

    def _env(self, name, inner, indent, marker, prefix):
        if name in LIST_ENVS:
            self._list(name, inner, indent)
        elif name in MATH_ENVS:
            self._equation(name, inner, indent)
        elif name in ("figure", "figure*", "wrapfigure", "SCfigure"):
            self._figure(inner, indent)
        elif name in ("table", "table*"):
            self._table(inner, indent)
        elif name in ("tabular", "tabular*", "tabularx", "longtable"):
            self._tabular(inner, indent)
        elif name in ("verbatim", "Verbatim", "lstlisting", "minted", "alltt"):
            self._verbatim(inner, indent)
        elif name == "mdframed":
            return self._blocks(_strip_opt(inner), indent, marker, "!")
        elif name in ("quote", "quotation", "verse"):
            return self._blocks(inner, indent, marker, "> ")
        elif name in DIAGRAMS:
            self._emit(f"{indent}> [{DIAGRAMS[name]} omitted]")
        elif name == "minipage":
            _spec, at = _group(inner, _opt(inner, 0))
            return self._blocks(inner[at:], indent, marker, prefix)
        elif name in ("comment",):
            pass
        else:                               # unknown or purely visual: keep the words
            return self._blocks(_strip_opt(inner), indent, marker, prefix)
        return marker

    # -- prose --------------------------------------------------------------
    def _prose(self, tex, indent, marker, prefix):
        pos = 0
        while True:
            m = _HEADING.search(tex, pos)
            if not m:
                return self._paragraphs(tex[pos:], indent, marker, prefix)
            marker = self._paragraphs(tex[pos:m.start()], indent, marker, prefix)
            title, pos = _group(tex, m.end())
            self._heading(m.group(1), bool(m.group(2)), title)

    def _heading(self, level: str, starred: bool, title: str) -> None:
        title = self._inline(title)
        if level == "paragraph":
            self.lead = title.rstrip(".")
            return
        if level == "chapter":
            number = "" if starred else self.chapter
            self.current = ("chap", number, title)
            self._emit(f"# {number}  {title}" if number else f"# {title}")
            if self.part:
                self._emit(f"!Part: {self.part}")
                self.part = None
            return
        if level == "section":
            if starred:
                self._emit(f"## {title}")
                self.current = ("sec", "", title)
                return
            self.sec += 1
            self.sub = 0
            number = self._num(self.sec)
            self.current = ("sec", number, title)
            self._emit(f"## {number}  {title}")
            return
        if level == "subsection" and not starred:
            self.sub += 1
            number = self._num(self.sec, self.sub)
            self.current = ("sec", number, title)
            self._emit(f"### {number}  {title}")
            return
        self.current = ("sec", self.current[1], title)
        self._emit(f"### {title}")

    def _paragraphs(self, tex, indent, marker, prefix):
        tex = re.sub(r"\\screencast\s*\{([^}]*)\}\s*\{[^}]*\}",
                     lambda m: f"\n\n- Video: {m.group(1)}\n\n", tex)
        pos = 0
        for m in _DISPLAY.finditer(tex):
            marker = self._text(tex[pos:m.start()], indent, marker, prefix)
            self._equation("displaymath", m.group(1) or m.group(2), indent)
            pos = m.end()
        return self._text(tex[pos:], indent, marker, prefix)

    def _text(self, tex, indent, marker, prefix):
        for piece in _BLANK.split(tex):
            text = self._inline(piece)
            if not text:
                continue
            if self.lead and not text.startswith("- Video:"):
                text = f"**{self.lead}.** {text}"
                self.lead = None
            text = _no_heading_colon(_no_pipes(text))
            if text.startswith("- Video:"):
                self._emit(indent + text)
            elif marker is not None:
                self._emit(marker + text)
                marker = None
            else:
                self._emit(indent + prefix + text, None if prefix else PARA_FMT)
        return marker

    # -- lists --------------------------------------------------------------
    def _list(self, name, inner, indent):
        inner = _strip_opt(inner)
        chunks = _split_depth0(inner, r"\\item\b(?:\[[^\]]*\])?")
        # chunks[0] is whatever sat before the first \item (usually nothing)
        self._blocks(chunks[0], indent, None, "")
        for i, chunk in enumerate(chunks[1:], 1):
            if name != "enumerate":
                bullet = "- "
            elif indent:
                bullet = f"({chr(ord('a') + (i - 1) % 26)}) "
            else:
                bullet = f"{i}. "
            marker = indent + bullet
            first = len(self.notes)
            left = self._blocks(chunk, indent + "  ", marker, "")
            if left is not None and len(self.notes) > first:
                # "\item" followed straight by a sub-list: LaTeX prints
                # "1. (a) ...", so the number rides on the first child.
                child = self.notes[first]
                child.text = left + child.text.lstrip()

    # -- math --------------------------------------------------------------
    def _equation(self, env, body, indent):
        if env in ALIGNED:
            rows = _split_depth0(body, r"\\\\")
            pending: list[str] = []
            for row in rows:
                labels = _LABEL.findall(row)
                numbered = "\\nonumber" not in row and "\\notag" not in row \
                    and not env.endswith("*")
                row = " ".join(_split_depth0(row, r"&"))
                text = _math_clean(row)
                if not text:
                    pending += labels
                    continue
                pending += labels
                if numbered:
                    self.eq += 1
                    number = self._num(self.eq)
                    if pending:
                        for lab in pending:
                            self.labels[lab] = ("eq", number, "")
                        text += f" \\qquad ({number})"
                        pending = []
                self._emit(f"{indent}$${text}$$")
            return
        labels = _LABEL.findall(body)
        text = _math_clean(body)
        if not text:
            return
        if env == "equation":
            self.eq += 1
            number = self._num(self.eq)
            for lab in labels:
                self.labels[lab] = ("eq", number, "")
            if labels:
                text += f" \\qquad ({number})"
        self._emit(f"{indent}$${text}$$")

    # -- floats -------------------------------------------------------------
    def _figure(self, inner, indent):
        self.fig += 1
        number = self._num(self.fig)
        saved = self.current
        self.current = ("fig", number, "")
        caption = self._caption(inner)
        self.current = ("fig", number, caption)
        for lab in _LABEL.findall(inner):
            self.labels[lab] = self.current
        self._emit(f"{indent}> Figure {number}" + (f": {caption}" if caption else ""))
        self.current = saved

    def _table(self, inner, indent):
        self.tab += 1
        number = self._num(self.tab)
        saved = self.current
        self.current = ("tab", number, "")
        caption = self._caption(inner)
        self.current = ("tab", number, caption)
        for lab in _LABEL.findall(inner):
            self.labels[lab] = self.current
        body = re.sub(r"\\caption\s*(\[[^\]]*\])?\s*", "\x00CAP", inner)
        if "\x00CAP" in body:
            at = body.index("\x00CAP")
            _cap, end = _group(body, at + len("\x00CAP"))
            body = body[:at] + body[end:]
        self._blocks(body, indent, None, "")
        self._emit(f"{indent}> Table {number}" + (f": {caption}" if caption else ""))
        self.current = saved

    def _caption(self, inner: str) -> str:
        m = re.search(r"\\caption\s*", inner)
        if not m:
            return ""
        at = _opt(inner, m.end())
        text, _end = _group(inner, _ws(inner, at))
        return _no_pipes(self._inline(text))

    def _tabular(self, inner, indent):
        inner = _strip_opt(inner)
        _spec, at = _group(inner, _ws(inner, 0))
        inner = inner[at:]
        inner = re.sub(r"\\(hline|toprule|midrule|bottomrule)\b", "", inner)
        inner = re.sub(r"\\cline\{[^}]*\}", "", inner)
        for row in _split_depth0(inner, r"\\\\"):
            if not row.strip():
                continue
            cells = []
            for cell in _split_depth0(row, r"&"):
                cell = re.sub(r"\\(begin|end)\{(itemize|enumerate)\}(\[[^\]]*\])?", "", cell)
                cell = re.sub(r"\\item\b", "; ", cell)
                text = self._inline(cell).lstrip("; ").strip()
                text = re.sub(r"\s*;\s*", "; ", text)
                text = re.sub(r":\s*;\s*", ": ", text)
                # A bar anywhere in a cell would split the row, so unlike
                # prose it goes even inside math -- but to a drawable one.
                text = text.replace("|", BAR)
                cells.append(text or EMPTY_CELL)
            if any(c != EMPTY_CELL for c in cells):
                self._emit(indent + " | ".join(cells))

    def _verbatim(self, inner, indent):
        # A plain \begin{verbatim} prints "$" as a dollar sign, so pseudocode
        # in one is already faithful and is left exactly as the book sets it.
        # This book's Bayes-filter listing instead opens with
        #     \begin{Verbatim}[codes={\catcode`$=3\catcode`^=7\catcode`_=8}]
        # which switches the math shift back ON inside the block: the book
        # *typesets* "x \in X" there, it does not print the dollars.  A code
        # note is never re-typeset by the reader (document.py lays S.CODE out
        # verbatim, with no latex.substitute), so the math has to be reduced
        # to text here -- otherwise the page shows "$x \in X$" where the book
        # shows "x in X", which is the book's meaning dropped, not kept.
        live_math = bool(_MATH_CATCODE.search(inner[:_opt(inner, _ws(inner, 0))]))
        inner = _strip_opt(inner)
        for line in inner.strip("\n").split("\n"):
            if live_math:
                line = _INLINE_MATH.sub(
                    lambda m: latex.inline(_math_noise(m.group(0)[1:-1])), line)
            if line.strip():
                self._emit(f"{indent}`{line.rstrip()}`")

    # -- inline -------------------------------------------------------------
    def _inline(self, text: str) -> str:
        math: list[str] = []

        def stash(m):
            math.append(_scrub_math(m.group(0)))
            return f"\x00M{len(math) - 1}\x00"

        text = _INLINE_MATH.sub(stash, text)
        text = self._commands(text)
        text = (text.replace("``", "“").replace("''", "”")
                .replace("`", "‘").replace("'", "’")
                .replace("---", "—").replace("--", "–").replace("~", " "))
        text = re.sub(r"\s*\n\s*", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        text = re.sub(r" ?\x00BR\x00 ?", "\n", text).strip()
        text = text.replace(CODE, "`")
        text = re.sub(r"\x00M(\d+)\x00", lambda m: math[int(m.group(1))], text)
        return text

    def _commands(self, text: str) -> str:
        out: list[str] = []
        i = 0
        while True:
            m = _CMD.search(text, i)
            if not m:
                out.append(text[i:])
                break
            out.append(text[i:m.start()])
            name = m.group(1)
            pos = m.end()
            base = name.rstrip("*")
            if name == "\\":
                out.append(BR)
            elif name.isspace():
                out.append(" ")
            elif name in "%&$_#{}":
                out.append(name)
            elif name in ",;: ":
                out.append(" ")
            elif name in "-/!@":
                pass
            elif base in STYLE:
                inner, pos = _arg(text, pos)
                out.append(STYLE[base] + self._commands(inner) + STYLE[base])
            elif base in PLAIN:
                pos = _opt(text, _ws(text, pos))
                inner, pos = _arg(text, pos)
                out.append(self._commands(inner))
            elif base == "footnote":
                pos = _opt(text, _ws(text, pos))
                inner, pos = _arg(text, pos)
                out.append(f" ({self._commands(inner).strip()})")
            elif base == "url":
                inner, pos = _arg(text, pos)
                out.append(inner)
            elif base == "href":
                link, pos = _arg(text, pos)
                shown, pos = _arg(text, pos)
                out.append(f"{self._commands(shown)} ({link})")
            elif base == "label":
                inner, pos = _arg(text, pos)
                self.labels[inner.strip("{} ")] = self.current
            elif base in REFS:
                pos = _opt(text, _ws(text, pos))
                inner, pos = _arg(text, pos)
                out.append(f"\x00R{base}:{inner}\x00")
            elif base in CITES:
                pos = _opt(text, _ws(text, pos))
                pos = _opt(text, _ws(text, pos))
                inner, pos = _arg(text, pos)
                out.append(self._cite(inner))
            elif base == "def":
                pos = _ws(text, pos)
                mm = re.compile(r"\\[A-Za-z]+").match(text, pos)
                pos = mm.end() if mm else pos
                _drop, pos = _arg(text, pos)
            elif base in DROP_ARGS:
                pos = _opt(text, _ws(text, pos))
                for _ in range(DROP_ARGS[base]):
                    _drop, pos = _arg(text, pos)
            elif base in SYMBOLS:
                out.append(SYMBOLS[base])
            elif base in LAYOUT:
                pos = _opt(text, pos)
                pos = _ws(text, pos) if base in ("newpage", "clearpage") else pos
            elif base in ("newline", "linebreak"):
                out.append(BR)
            else:
                out.append("\\" + name)     # unknown: keep it where it can be seen
            i = pos
        return "".join(out)

    def _cite(self, keys: str) -> str:
        parts = []
        unknown = 0
        for key in keys.split(","):
            key = key.strip()
            if not key:
                continue
            found = self.bib.cite(key)
            if found is None:
                unknown += 1
                parts.append(f"[{key}]")
            else:
                parts.append(found)
        if len(parts) == 1 and unknown:
            return parts[0]
        return "(" + "; ".join(parts) + ")"


_INPUT = re.compile(r"\\(?:input|include)\{([^}]*)\}")


def _expand_inputs(tex: str, root: Path | None, depth: int = 0) -> str:
    """Splice ``\\input{file}`` in place (the kinematics chapter is four files)."""
    if root is None or depth > 8:
        return tex

    def splice(m):
        path = root / m.group(1).strip()
        if not path.suffix:
            path = path.with_suffix(".tex")
        if not path.exists():
            return m.group(0)
        # Blank lines around the splice: a file's last paragraph must not
        # run into the sentence after the \\input.
        return "\n\n" + _expand_inputs(strip_comments(_read(path)), root, depth + 1) + "\n\n"

    return _INPUT.sub(splice, tex)


def _strip_opt(inner: str) -> str:
    """Drop the ``[options]`` an environment may open with."""
    at = _opt(inner, _ws(inner, 0))
    return inner[at:]


def _no_heading_colon(text: str) -> str:
    """"The position is given by:" is prose in a book, not a heading.

    classify() makes any line of <= 48 chars ending in ":" an explicit
    heading, and fmt cannot override an explicit shape, so the colon is
    swapped for U+A789 MODIFIER LETTER COLON, which draws the same way and
    which Menlo (the PDF export face) actually has -- U+2236 RATIO it lacks.
    """
    if text.endswith(":") and len(text) <= S.HEAD_MAX * 2:
        return text[:-1] + "\ua789"
    return text


BAR = "│"       # the one vertical bar Menlo, Consolas and DejaVu all have


def _no_pipes(text: str) -> str:
    """Keep prose from reading as panes (``||``) or a table row (two ``|``).

    Bars inside ``$...$`` are math -- an absolute value or a norm -- and
    ``shaping.classify`` ignores those, so they are left for the typesetter.
    Only a bare pipe in prose is swapped, and for one the PDF faces can
    actually draw: U+2223 DIVIDES and U+2016 DOUBLE VERTICAL LINE are both
    missing from Menlo, so the reader used to get an empty box.
    """
    spans: list = []

    def stash(m):
        spans.append(m.group(0))
        return "\x00B%d\x00" % (len(spans) - 1)

    kept = S.MATHS_SPAN.sub(stash, text)
    if kept.count("|") >= 2:
        kept = kept.replace("|", BAR)
    return re.sub(r"\x00B(\d+)\x00", lambda m: spans[int(m.group(1))], kept)


# --- typography that means nothing once math is set in a terminal ---------
_UNIT = r"(?:pt|pc|bp|em|ex|cm|mm|in|dd|cc|sp|mu)"
_LENGTH = r"[-+]?(?:\d+\.?\d*|\.\d+)\s*" + _UNIT + r"\b"
# "\arraycolsep=2pt", "\abovedisplayskip = 10pt plus 2pt minus 3pt": a TeX
# dimension assignment.  It sets column spacing / leading / indentation in
# print; a terminal has none of those, and the requirement that it be a
# *number with a TeX unit* keeps a real equation ("\lambda=2\pi") out.
_DIMEN = re.compile(r"\\[A-Za-z]+\s*=\s*" + _LENGTH
                    + r"(?:\s*(?:plus|minus)\s*" + _LENGTH + r")*\s*")
# \displaystyle inside a display is a no-op; \textstyle and friends only
# pick a size, and every size is the same size in a terminal.
_MATH_SIZE = re.compile(r"\\(?:displaystyle|textstyle|scriptstyle|"
                        r"scriptscriptstyle|limits|nolimits)\b\s*")
# Fixed-width spaces: the width is print-only, but the gap is real.
_MATH_SPACE = re.compile(r"\s*\\(?:enskip|enspace|thinspace|negthinspace|"
                         r"medspace|thickspace)\b\s*")
# \textbf{K} inside math asks for bold; math in a terminal has no bold,
# so what is left of it is its argument.  (\text and \mathrm are NOT here:
# "upright, in math" is meaning, and inkwell.latex already sets them.)
_MATH_STYLE = re.compile(r"\\(?:textbf|textit|textsl|textsc|textmd|textup|"
                         r"emph)\s*(?=\{)")


def _math_noise(src: str) -> str:
    """Strip print-only commands from the inside of one piece of math.

    Only typography goes: anything that still means something (an accent,
    a symbol, \\text, an array) is left for inkwell.latex to typeset.
    """
    src = _DIMEN.sub("", src)
    src = _MATH_SIZE.sub("", src)
    src = _MATH_SPACE.sub(" ", src)
    while True:
        m = _MATH_STYLE.search(src)
        if not m:
            break
        inner, end = _group(src, m.end())
        src = src[:m.start()] + inner + src[end:]
    return src


def _scrub_math(dollared: str) -> str:
    """``$...$`` with the print-only commands taken out of the middle."""
    inner = _math_noise(dollared[1:-1])
    return f"${inner}$" if inner.strip() else dollared


def _math_clean(body: str) -> str:
    body = _math_noise(body)
    body = _LABEL.sub("", body)
    body = re.sub(r"\\(nonumber|notag)\b", "", body)
    body = re.sub(r"\\begin\{array\}\s*\{[^{}]*\}", r"\\begin{matrix}", body)
    body = body.replace("\\end{array}", "\\end{matrix}")
    body = re.sub(r"\\(begin|end)\{split\}", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"(\\\\\s*)+$", "", body).strip()
    return body


# --- public API -------------------------------------------------------------
def notes(tex: str, chapter: str = "", labels: Labels | None = None,
          bib: Bibliography | None = None, part: str | None = None,
          root: Path | None = None) -> list:
    """One chapter's LaTeX -> inkwell notes (store.Note), refs resolved."""
    conv = _Converter(chapter, labels, bib, part, root)
    conv.run(tex)
    return conv.finish()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _chapters(root: Path) -> list[dict]:
    """Reading order from book.tex: [{tex, number, part, title}, ...]."""
    book = strip_comments(_read(root / "book.tex"))
    start = book.find("\\begin{document}")
    end = book.find("\\end{document}")
    body = book[start + len("\\begin{document}"):end if end > 0 else None]
    edge = re.compile(r"\\(part|appendix|input|include|chapter)(\*?)\b")
    out: list[dict] = []
    pending_part = None
    appendix = False
    numbered = 0
    unnumbered = 0
    letters = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    pos = 0
    inline: dict | None = None
    marks = list(edge.finditer(body))
    for k, m in enumerate(marks):
        nxt = marks[k + 1].start() if k + 1 < len(marks) else len(body)
        kind, starred = m.group(1), bool(m.group(2))
        if kind == "part":
            title, _ = _group(body, _ws(body, m.end()))
            pending_part = re.sub(r"\\[A-Za-z]+\{?|[{}]", "", title).strip()
            inline = None
            continue
        if kind == "appendix":
            appendix = True
            inline = None
            continue
        if kind in ("input", "include"):
            name, _ = _group(body, _ws(body, m.end()))
            path = root / name.strip()
            if not path.suffix:
                path = path.with_suffix(".tex")
            tex = _read(path)
            inline = None
        else:                                       # \chapter written in book.tex
            tex = body[m.start():nxt]
            inline = {"tex": tex}
        title_m = re.search(r"\\chapter(\*?)\s*\{", tex)
        title = ""
        chapter_starred = False
        if title_m:
            title, _ = _group(tex, title_m.end() - 1)
            title = re.sub(r"\\[A-Za-z]+\{?|[{}]", "", title).strip()
            chapter_starred = bool(title_m.group(1))
        if chapter_starred:
            unnumbered += 1
            number = ""
            slot = "00" if unnumbered == 1 else f"00-{unnumbered}"
        elif appendix:
            number = next(letters)
            slot = number
        else:
            numbered += 1
            number = str(numbered)
            slot = f"{numbered:02d}"
        out.append({"tex": tex, "number": number, "slot": slot,
                    "part": pending_part, "title": title})
        pending_part = None
        pos = nxt
    return out


def book_title(root) -> str:
    r"""What the book calls itself: ``\title{...}`` from its own source."""
    root = Path(root)
    for name in ("book.tex", "main.tex", "index.tex"):
        path = root / name
        if not path.exists():
            continue
        m = re.search(r"\\title\s*\{", _read(path))
        if m:
            title, _ = _group(_read(path), m.end() - 1)
            title = re.sub(r"\\[A-Za-z]+\{?|[{}]|\\\\", " ", title)
            title = " ".join(title.split())
            if title:
                return title
    return root.resolve().name.replace("-", " ").replace("_", " ").strip()


def prefix_for(root) -> str:
    """A short prefix for a book with no name given: its initials.

    "Introduction to Autonomous Robots" -> "IAR". Short titles keep their
    first word instead, so a two-word book does not become two letters.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", book_title(root)) if w]
    big = [w for w in words if w[0].isupper()]
    if len(big) >= 3:
        return "".join(w[0] for w in big[:5]).upper()
    return (words[0][:8].upper() if words else "BOOK")


def convert(root, out_dir, prefix: str = "", title: str = "") -> list[Path]:
    """Every chapter of the book at *root* -> notebooks in *out_dir*.

    Also writes ``<prefix>.book.json`` so the reader's shelf can show the
    book's real name rather than guessing it from the file names.
    """
    root, out_dir = Path(root), Path(out_dir)
    prefix = prefix or prefix_for(root)
    title = title or book_title(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    bib_path = root / "robotics.bib"
    bib = Bibliography.parse(_read(bib_path)) if bib_path.exists() else Bibliography()
    chapters = _chapters(root)
    labels = Labels()
    for ch in chapters:                          # pass 1: learn every label
        notes(ch["tex"], chapter=ch["number"], labels=labels, bib=bib, root=root)
    written: list[Path] = []
    now = time.time()
    for i, ch in enumerate(chapters):            # pass 2: resolve them
        made = notes(ch["tex"], chapter=ch["number"], labels=labels, bib=bib,
                     part=ch["part"], root=root)
        path = store.path_for(f"{prefix} {ch['slot']} {ch['title']}", out_dir)
        store.save(made, path)
        stamp = now - i * 60
        os.utime(path, (stamp, stamp))
        written.append(path)
    reader.write_manifest(out_dir, prefix.lower(), title, str(root))
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("book", type=Path, help="folder holding book.tex")
    parser.add_argument("--out", type=Path, default=store.DEFAULT_DIR,
                        help=f"notes folder (default: {store.DEFAULT_DIR})")
    parser.add_argument("--title", default="",
                        help="what to call the book (default: its own "
                             "\\title{})")
    parser.add_argument("--prefix", default="",
                        help="notebook name prefix (default: the book's "
                             "initials)")
    args = parser.parse_args(argv)
    for path in convert(args.book, args.out, args.prefix, args.title):
        count = len(store.load(path))
        print(f"{count:5d} notes  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
