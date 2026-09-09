"""Turn a stream of typed characters into notes, and read each note's markup.

Everything here is pure text -> data: when a sentence is finished, and what
kind of *block* a line is (paragraph, list item, key/value, section...).
How a block is laid out is document.py's job; how it is drawn is
typography.py's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Block kinds -- a document's vocabulary, not a font list.
TITLE = "title"        # the document's name
SECTION = "section"    # a named division, drawn with a rule
HEAD = "head"          # a heading inside a section
PARA = "para"          # prose
ASK = "ask"            # an open question, marked so it can be found later
ITEM = "item"          # list item (possibly numbered, possibly nested)
CHECK = "check"        # checklist item
KV = "kv"              # "key: value", aligned into a column with its run
QUOTE = "quote"        # someone else's words
CODE = "code"          # verbatim
CALLOUT = "callout"    # something shouted
MATH = "math"          # display maths, written as LaTeX
TERM = "term"          # a definition: "term :: what it means"
TABLE = "table"        # one row of a table, written with pipes
RULE = "rule"          # a divider
PANES = "panes"        # several boxes side by side, split with "||"

KINDS = (TITLE, SECTION, HEAD, PARA, ASK, ITEM, CHECK, KV, QUOTE, CODE,
         CALLOUT, MATH, TERM, TABLE, RULE, PANES)
# What the model is allowed to choose (structure only -- never TITLE, and
# never MATH or TABLE, which need markup the writer has to supply).
FORMATTABLE = (SECTION, HEAD, PARA, ASK, ITEM, CHECK, KV, QUOTE, CODE,
               CALLOUT, TERM)
# Kinds that stack into a run and are drawn tightly against each other.
LIST_KINDS = (ITEM, CHECK, KV, TABLE, TERM, PANES, CODE)

TERMINATORS = ".!?…"
_CLOSERS = "\"')]}”’"

ABBREVIATIONS = {
    "e.g.", "i.e.", "etc.", "vs.", "cf.", "al.", "approx.", "fig.", "no.",
    "mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "jr.", "sr.", "inc.",
    "ca.", "resp.", "ea.", "dept.", "est.", "min.", "max.", "sec.",
}

_TASK_RE = re.compile(r"^(todo|to-do|task)\b[:\-\s]*", re.I)
_CHECKBOX_RE = re.compile(r"^[-*]?\s*\[([ xX]?)\]\s*")
_BULLET_RE = re.compile(r"^[-*•]\s+")
_NUMBER_RE = re.compile(r"^(\d{1,3})[.)]\s+")
# "(a)" or "a)" -- lettered lists. The bare "a." form is left alone: it is
# far more often the end of a sentence.
_LETTER_RE = re.compile(r"^\(?([a-z])\)\s+")
_KV_RE = re.compile(r"^([^:\n]{1,28}?):\s+(\S.*)$")
_TERM_RE = re.compile(r"^(.{1,40}?)\s*::\s*(\S.*)$")
_RULE_RE = re.compile(r"^([-*_=])\1{2,}$")
_MATH_RE = re.compile(r"^\$\$(.+?)\$\$$|^\$([^$]+)\$$", re.S)

PANE_SEP = "||"
# A maths span. Bars inside one are an absolute value or a norm, never a
# column separator, so structure tests look at the line with maths blanked.
MATHS_SPAN = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)


def without_maths(text: str) -> str:
    """The line with every ``$...$`` span blanked, same length."""
    return MATHS_SPAN.sub(lambda m: " " * len(m.group(0)), text)


_WEIGHT_RE = re.compile(r"^\{(\d{1,2})\}\s*")
_HAS_LETTER = re.compile(r"[A-Za-z]")

# A heading is short AND terse AND capitalised -- a jotted fragment like
# "prof started 5 min late again" is prose, not a heading.
HEAD_MAX = 24
HEAD_WORDS = 3
# A pair is "label: short value", not any sentence with a colon in it.
VALUE_WORDS = 4
VALUE_MAX = 40
MAX_LEVEL = 3


def should_commit(buffer: str) -> bool:
    """True when the composer buffer looks like a finished thought."""
    if not buffer or not buffer[-1].isspace():
        return False
    body = buffer.strip()
    if len(body) < 2:
        return False
    if body.endswith("..."):
        return False
    core = body.rstrip(_CLOSERS)
    if not core or core[-1] not in TERMINATORS:
        return False
    # "3. " on its own is a list marker, not the end of a sentence -- but
    # "the answer is 3. " is. Requiring a letter tells them apart.
    if not _HAS_LETTER.search(core):
        return False
    token = core.split()[-1].lower()
    if token in ABBREVIATIONS:
        return False
    if len(token) == 2 and token[0].isalpha() and token[1] == ".":
        return False
    return True


def is_idle_commit(buffer: str) -> bool:
    """True when a pause should file the buffer even without punctuation."""
    return len(buffer.strip()) >= 3


@dataclass(frozen=True)
class Shape:
    kind: str
    text: str                # display text, markup stripped
    level: int = 0           # nesting, from leading whitespace
    key: str = ""            # KV only
    value: str = ""          # KV only
    done: bool = False       # CHECK only
    numbered: bool = False   # ITEM only
    start: int = 0           # ITEM only: the number the writer actually typed
    lettered: bool = False   # ITEM only: (a), (b), (c)...
    explicit: bool = False   # the user typed a marker, so hands off


def _is_pair(key: str, value: str) -> bool:
    """Is "key: value" a fact worth aligning, or just a sentence?"""
    if len(key.split()) > 4 or key[-1] in TERMINATORS:
        return False
    if value.startswith("$") and value.endswith("$"):
        return True                      # "efficiency: $\eta = ...$"
    return (len(value) <= VALUE_MAX and len(value.split()) <= VALUE_WORDS
            and value[-1] not in TERMINATORS)


# Kinds whose markup is about a single line; a note broken over several
# lines falls back to prose rather than pretending to be a table row.
_ONE_LINERS = (KV, TERM, TABLE, MATH, RULE, PANES)


def classify(raw: str) -> Shape:
    """Read one note's own markup. Structure only -- no styling decisions."""
    if "\n" in raw.rstrip():
        head, rest = raw.rstrip().split("\n", 1)
        shape = classify(head)
        kind = PARA if shape.kind in _ONE_LINERS else shape.kind
        return Shape(kind, (shape.text + "\n" + rest).rstrip(), shape.level,
                     done=shape.done, numbered=shape.numbered,
                     lettered=shape.lettered, start=shape.start,
                     explicit=shape.explicit)
    body = raw.rstrip()
    lead = len(body) - len(body.lstrip(" \t"))
    level = min(MAX_LEVEL, lead // 2)
    text = body.strip()
    if not text:
        return Shape(PARA, "", level)

    outside = without_maths(text)
    if PANE_SEP in outside:
        return Shape(PANES, text, level, explicit=True)

    math = _MATH_RE.match(text)
    if math:
        return Shape(MATH, (math.group(1) or math.group(2)).strip(), level,
                     explicit=True)
    if _RULE_RE.match(text):
        return Shape(RULE, "", level, explicit=True)
    if outside.count("|") >= 2 and not text.startswith("|-"):
        return Shape(TABLE, text.strip("| "), level, explicit=True)

    term = _TERM_RE.match(text)
    if term:
        return Shape(TERM, text, level, key=term.group(1).strip(),
                     value=term.group(2).strip(), explicit=True)

    if text.startswith("###"):
        return Shape(HEAD, text.lstrip("#").strip(), level, explicit=True)
    if text.startswith("##"):
        return Shape(SECTION, text.lstrip("#").strip(), level, explicit=True)
    if text.startswith("#"):
        return Shape(TITLE, text.lstrip("#").strip(), 0, explicit=True)
    if text.startswith(">"):
        return Shape(QUOTE, text.lstrip("> ").strip(), level, explicit=True)
    if len(text) > 2 and text.startswith("`") and text.endswith("`"):
        # Verbatim: whatever is between the backticks, spaces and all.
        return Shape(CODE, text[1:-1], level, explicit=True)
    if text.startswith("!"):
        return Shape(CALLOUT, text.lstrip("! ").strip(), level, explicit=True)

    check = _CHECKBOX_RE.match(text)
    if check:
        return Shape(CHECK, _CHECKBOX_RE.sub("", text).strip(), level,
                     done=check.group(1).lower() == "x", explicit=True)
    if _TASK_RE.match(text):
        return Shape(CHECK, _TASK_RE.sub("", text).strip(), level, explicit=True)

    number = _NUMBER_RE.match(text)
    if number:
        return Shape(ITEM, _NUMBER_RE.sub("", text).strip(), level,
                     numbered=True, start=int(number.group(1)), explicit=True)
    letter = _LETTER_RE.match(text)
    if letter:
        return Shape(ITEM, _LETTER_RE.sub("", text).strip(), level,
                     numbered=True, lettered=True,
                     start=ord(letter.group(1)) - ord("a") + 1, explicit=True)
    if _BULLET_RE.match(text):
        return Shape(ITEM, _BULLET_RE.sub("", text).strip(), level, explicit=True)

    # A pair is a short fact worth aligning ("fin pitch: 0.4mm"), not any
    # sentence that happens to contain a colon.
    pair = _KV_RE.match(text)
    if pair and _is_pair(pair.group(1), pair.group(2)):
        return Shape(KV, text, level, key=pair.group(1).strip(),
                     value=pair.group(2).strip(), explicit=True)
    if text.endswith(":") and len(text) <= HEAD_MAX * 2:
        return Shape(HEAD, text[:-1].strip(), level, explicit=True)

    if text.isupper() and _HAS_LETTER.search(text) and len(text) <= 60:
        return Shape(CALLOUT, text, level)
    if (len(text) <= HEAD_MAX and len(text.split()) <= HEAD_WORDS
            and text[-1] not in TERMINATORS and text[0].isupper()):
        return Shape(HEAD, text, level)
    if text.rstrip(_CLOSERS).endswith("?"):
        return Shape(ASK, text, level)
    return Shape(PARA, text, level)


_MARKER_RE = re.compile(r"^(\s*(?:[-*•]\s+|\d{1,3}[.)]\s+|\[[ xX]?\]\s*"
                        r"|[-*]\s*\[[ xX]?\]\s*|>\s*|#{1,3}\s+|!\s*))")


_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def blocks_in(text: str) -> list:
    """Split a note where the writer left a blank line.

    One ⏎ is a line inside this block; two is the start of the next one --
    the same rule as everywhere else that has paragraphs.
    """
    out = []
    for piece in _BLANK_LINE.split(text):
        piece = piece.strip("\n").rstrip()
        # Indentation comes in pairs and means nesting; a single leading
        # space is the leftover from breaking in the middle of a sentence.
        if piece.startswith(" ") and not piece.startswith("  "):
            piece = piece[1:]
        if piece.strip():
            out.append(piece)
    return out


_LIST_MARKER = re.compile(r"^\s*(?:[-*•]\s+|\d{1,3}[.)]\s+|\(?[a-z]\)\s+"
                          r"|\[[ xX]?\]\s*|[-*]\s*\[[ xX]?\]\s*)")


def list_marker_of(raw: str) -> str:
    """The marker of a list item, if that is what this line is.

    Headings and quotations are deliberately not included: carrying those
    onto the next block would make a second heading, which nobody means.
    """
    match = _LIST_MARKER.match(raw)
    return match.group(0) if match else ""


def marker_of(raw: str) -> str:
    """The markup prefix a line carries, so a split tail can keep it."""
    match = _MARKER_RE.match(raw)
    return match.group(1) if match else ""


def join(first: str, second: str) -> str:
    """Glue two notes back together, dropping the second one's marker."""
    head = first.rstrip()
    tail = second.strip()
    if marker_of(tail):
        tail = tail[len(marker_of(tail)):].strip()
    if not head:
        return tail
    if not tail:
        return head
    glue = "" if head.endswith(("-", "(", "[", "“")) else " "
    return head + glue + tail


def panes(text: str) -> list:
    """Parse "a || {2} b" into [(weight, text), ...]. Equal unless told."""
    out = []
    for piece in text.split(PANE_SEP):
        weight = 1.0
        match = _WEIGHT_RE.match(piece.strip())
        body = piece.strip()
        if match:
            weight = max(1, min(9, int(match.group(1))))
            body = _WEIGHT_RE.sub("", body)
        out.append((float(weight), body))
    return out


def unpane(text: str) -> str:
    """Fold panes back into one line."""
    return " ".join(body for _weight, body in panes(text) if body).strip()


def repane(parts: list) -> str:
    """Build a panes line from (weight, text) pairs."""
    pieces = []
    for weight, body in parts:
        prefix = "" if float(weight) == 1.0 else "{%d} " % int(weight)
        pieces.append(prefix + body.strip())
    return (" %s " % PANE_SEP).join(pieces)


def split_sentences(text: str) -> list[str]:
    """Split pasted / multi-sentence text into note-sized pieces."""
    out: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        lead = line[:len(line) - len(line.lstrip(" \t"))]
        stripped = line.strip()
        if stripped[0] in "#>-*[`!" or _TASK_RE.match(stripped) or _NUMBER_RE.match(stripped):
            out.append(line.rstrip())
            continue
        buf = ""
        for i, ch in enumerate(stripped):
            buf += ch
            # Only break where a space (or the end) actually follows, so
            # decimals like 0.4mm and versions like v1.2 stay whole.
            following = stripped[i + 1:i + 2]
            if (not following or following.isspace()) and should_commit(buf + " "):
                out.append(lead + buf.strip())
                buf = ""
        if buf.strip():
            out.append(lead + buf.strip())
    return out
