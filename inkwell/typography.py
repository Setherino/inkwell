"""Drawing primitives: wrapping, inline markup, and the one big font.

This module used to pick fonts for everything; it doesn't any more. Type
size is an accent -- the document's *title* may be set large when there is
room for it, and inline markup borrows unicode letterforms. Everything
else is layout, which lives in document.py.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

import urwid
from urwid import font as uf

# Only three of urwid's fonts carry a full alphabet; the caps-only one is
# the smallest rung, so the title can shrink twice before giving up.
_FONTS = {
    "xl": (uf.HalfBlock7x7Font(), lambda t: t),
    "l": (uf.HalfBlock5x4Font(), lambda t: t),
    "m": (uf.Sextant3x3Font(), lambda t: t.upper()),
}
TITLE_LADDER = ("xl", "l", "m")

MEASURE = 78           # prose stops widening here, however wide the terminal
CENTRE_AT = 92         # ...and centres itself past here


def font(size: str) -> uf.Font:
    return _FONTS[size][0]


def prepare(size: str, text: str) -> str:
    """Coerce text into what this font can actually draw."""
    fnt, pre = _FONTS[size]
    text = pre(text)
    return "".join(c if fnt.char_width(c) else (" " if c.isspace() else "") for c in text)


def measure(size: str, text: str) -> int:
    fnt = _FONTS[size][0]
    return sum(fnt.char_width(c) for c in text)


def height(size: str) -> int:
    return _FONTS[size][0].height


# --- unicode letterforms, used for inline markup only -----------------------
def _offset_map(a_upper: int, a_lower: int, zero: Optional[int] = None):
    table = {}
    for i in range(26):
        table[ord("A") + i] = a_upper + i
        table[ord("a") + i] = a_lower + i
    if zero is not None:
        for i in range(10):
            table[ord("0") + i] = zero + i
    return table


BOLD = _offset_map(0x1D5D4, 0x1D5EE, 0x1D7EC)
ITALIC = _offset_map(0x1D608, 0x1D622)
MONO = _offset_map(0x1D670, 0x1D68A, 0x1D7F6)
SMALLCAPS = {ord(k): ord(v) for k, v in
             zip("abcdefghijklmnopqrstuvwxyz",
                 "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡXʏᴢ")}
SMALLCAPS.update({ord(c): ord(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})

TRANSFORMS = {"plain": {}, "bold": BOLD, "italic": ITALIC, "mono": MONO,
              "smallcaps": SMALLCAPS}

UNICODE_OK = True      # flipped by the f9 toggle via widgets.VIEW


def transform(name: str, text: str, *, unicode_ok: bool = True) -> str:
    if not unicode_ok:
        return text.upper() if name == "smallcaps" else text
    if name == "plain":
        return text
    return text.translate(TRANSFORMS[name])


_INLINE = re.compile(r"\*\*(?P<b>[^*]+)\*\*|(?<![\w`])_(?P<i>[^_]+)_(?![\w`])"
                     r"|`(?P<c>[^`]+)`")


def inline(text: str, *, unicode_ok: bool = True) -> str:
    """Apply inline markup: ``**bold**``, ``_italic_``, ``` `code` ```."""
    def swap(match):
        for name, key in (("bold", "b"), ("italic", "i"), ("mono", "c")):
            if match.group(key):
                return transform(name, match.group(key), unicode_ok=unicode_ok)
        return match.group(0)
    return _INLINE.sub(swap, text)


def emphasise(text: str, phrase: str, *, unicode_ok: bool = True) -> str:
    """Bold one phrase in place (used for the model's suggestion)."""
    if not phrase or not unicode_ok:
        return text
    needle = phrase.strip().lower()
    at = text.lower().find(needle)
    if not needle or len(needle) > 40 or at < 0:
        return text
    return (text[:at] + transform("bold", text[at:at + len(needle)])
            + text[at + len(needle):])


# --- wrapping ---------------------------------------------------------------
def cols(text: str) -> int:
    """Screen columns a string occupies."""
    return urwid.calc_width(text, 0, len(text)) if text else 0


def wrap(text: str, maxcol: int, width_of: Callable[[str], int] = cols,
         hard: bool = True) -> list[str]:
    """Greedy word wrap against an arbitrary width function.

    ``hard=False`` leaves an over-wide word on its own over-long line rather
    than chopping it, so a caller can decide to step down a size instead.
    """
    if maxcol <= 0:
        return [text]
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}" if line else word
        if width_of(candidate) <= maxcol or not line:
            if width_of(candidate) > maxcol and not line:
                if not hard:
                    lines.append(word)
                    continue
                chunk = ""
                for ch in word:
                    if width_of(chunk + ch) > maxcol and chunk:
                        lines.append(chunk)
                        chunk = ch
                    else:
                        chunk += ch
                line = chunk
                continue
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def title_font(text: str, maxcol: int, maxrow: int) -> Optional[tuple[str, list[str]]]:
    """The biggest font the title fits in, or None -- set it as a line instead.

    One line in a smaller font beats two lines in a bigger one, so the
    ladder is walked in preference order: a big font on one line, then a big
    font on two, and only then a smaller one.
    """
    budget = max(1, int(maxrow * 0.45))
    # Preference order: big on one line, then big on two, before small.
    for size, limit in (("xl", 1), ("l", 1), ("l", 2), ("m", 1), ("m", 2)):
        if True:
            if height(size) > budget:
                continue
            if size == "xl" and maxrow < 18:
                continue
            if size == "l" and maxrow < 12:
                continue
            drawable = prepare(size, text)
            lines = wrap(drawable, maxcol, lambda s, k=size: measure(k, s),
                         hard=False)
            if len(lines) > limit or len(lines) * height(size) > budget:
                continue
            if any(measure(size, line) > maxcol for line in lines):
                continue
            return size, lines
    return None


def column(maxcol: int) -> tuple[int, int]:
    """(text measure, left offset) for the page at this width."""
    room = min(maxcol, MEASURE)
    return room, (maxcol - room) // 2 if maxcol >= CENTRE_AT else 0
