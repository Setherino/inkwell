"""Colours, for whichever terminal you happen to be in.

Two palettes -- one for a dark background, one for a light one -- built to
measured contrast rather than by eye: body text clears 7:1 against its
background, and the deliberately quiet things (rules, timestamps, leaders)
still clear 3:1, so nothing on the page is a grey smudge.

The background is detected at startup: ``$INKWELL_THEME`` wins, then
``$COLORFGBG`` (which many terminals set), then an OSC 11 query asking the
terminal what colour it actually is. If none of that answers, dark.
"""

from __future__ import annotations

import os
import re
import select
import sys

# Attributes the document and widgets can ask for. Both palettes must
# define every one of them; tests check that.
NAMES = (
    "body", "title", "section", "head", "marker", "check", "check_done",
    "kv_key", "kv_value", "leader", "quote", "code", "callout", "callout_bar",
    "math", "ask", "ask_mark", "term", "term_body", "table_head", "rule",
    "meta", "tag", "cursorbar", "picked", "selected", "editing", "halo", "halo_button",
    "prompt", "status", "status_said", "ghost",
    "dialog", "dialog_title", "dialog_item", "dialog_focus",
)

# name: (16-colour fg, 16-colour bg, mono, 256-colour fg, 256-colour bg)
DARK = {
    "body":        ("white",         "",          "",          "#eee", ""),
    "title":       ("light cyan",    "",          "bold",      "#7df", ""),
    "section":     ("light magenta", "",          "bold",      "#e9f", ""),
    "head":        ("white",         "",          "bold",      "#fff", ""),
    "marker":      ("light cyan",    "",          "",          "#7cf", ""),
    "check":       ("light green",   "",          "",          "#9f9", ""),
    "check_done":  ("dark gray",     "",          "",          "#999", ""),
    "kv_key":      ("light gray",    "",          "",          "#cdf", ""),
    "kv_value":    ("white",         "",          "bold",      "#fff", ""),
    "leader":      ("dark gray",     "",          "",          "#889", ""),
    "quote":       ("light cyan",    "",          "italics",   "#adc", ""),
    "code":        ("yellow",        "",          "",          "#fd9", ""),
    "callout":     ("light red",     "",          "bold",      "#fbb", ""),
    "callout_bar": ("light red",     "",          "",          "#f66", ""),
    "math":        ("light cyan",    "",          "",          "#adf", ""),
    "ask":         ("yellow",        "",          "",          "#fe9", ""),
    "ask_mark":    ("brown",         "",          "bold",      "#fc6", ""),
    "term":        ("white",         "",          "bold",      "#fff", ""),
    "term_body":   ("white",         "",          "",          "#eee", ""),
    "table_head":  ("white",         "",          "bold",      "#fff", ""),
    "rule":        ("dark gray",     "",          "",          "#889", ""),
    "meta":        ("dark gray",     "",          "",          "#99a", ""),
    "tag":         ("light blue",    "",          "",          "#aab", ""),
    "cursorbar":   ("light cyan",    "",          "",          "#0df", ""),
    "picked":      ("light cyan",    "",          "bold",      "#0df", ""),
    "selected":    ("black",         "light cyan", "standout", "#012", "#7df"),
    "editing":     ("white",         "dark blue", "standout",  "#fff", "#036"),
    "halo":        ("light blue",    "dark blue", "standout",  "#7df", "#024"),
    "halo_button": ("white",         "dark blue", "standout",  "#cef", "#047"),
    "prompt":      ("light cyan",    "",          "bold",      "#0df", ""),
    "status":      ("light gray",    "",          "",          "#aab", ""),
    "status_said": ("light green",   "",          "bold",      "#9f9", ""),
    "ghost":       ("dark gray",     "",          "",          "#99a", ""),
    "dialog":      ("white",         "black",     "",          "#eee", "#112"),
    "dialog_title": ("light cyan",   "black",     "bold",      "#7df", "#112"),
    "dialog_item": ("white",         "black",     "",          "#eee", "#112"),
    "dialog_focus": ("black",        "light cyan", "standout", "#012", "#7df"),
}

LIGHT = {
    "body":        ("black",         "",          "",          "#222", ""),
    "title":       ("dark blue",     "",          "bold",      "#036", ""),
    "section":     ("dark magenta",  "",          "bold",      "#717", ""),
    "head":        ("black",         "",          "bold",      "#000", ""),
    "marker":      ("dark blue",     "",          "",          "#048", ""),
    "check":       ("dark green",    "",          "",          "#060", ""),
    "check_done":  ("dark gray",     "",          "",          "#777", ""),
    "kv_key":      ("dark blue",     "",          "",          "#345", ""),
    "kv_value":    ("black",         "",          "bold",      "#000", ""),
    "leader":      ("dark gray",     "",          "",          "#778", ""),
    "quote":       ("dark cyan",     "",          "italics",   "#046", ""),
    "code":        ("brown",         "",          "",          "#730", ""),
    "callout":     ("dark red",      "",          "bold",      "#900", ""),
    "callout_bar": ("dark red",      "",          "",          "#c00", ""),
    "math":        ("dark blue",     "",          "",          "#026", ""),
    "ask":         ("brown",         "",          "",          "#640", ""),
    "ask_mark":    ("brown",         "",          "bold",      "#930", ""),
    "term":        ("black",         "",          "bold",      "#000", ""),
    "term_body":   ("black",         "",          "",          "#222", ""),
    "table_head":  ("black",         "",          "bold",      "#000", ""),
    "rule":        ("dark gray",     "",          "",          "#778", ""),
    "meta":        ("dark gray",     "",          "",          "#667", ""),
    "tag":         ("dark blue",     "",          "",          "#558", ""),
    "cursorbar":   ("dark blue",     "",          "",          "#05a", ""),
    "picked":      ("dark blue",     "",          "bold",      "#05a", ""),
    "selected":    ("white",         "dark blue", "standout",  "#fff", "#036"),
    "editing":     ("black",         "light cyan", "standout", "#000", "#cef"),
    "halo":        ("dark blue",     "light cyan", "standout", "#05a", "#adf"),
    "halo_button": ("black",         "light blue", "standout", "#013", "#8cf"),
    "prompt":      ("dark blue",     "",          "bold",      "#05a", ""),
    "status":      ("dark gray",     "",          "",          "#556", ""),
    "status_said": ("dark green",    "",          "bold",      "#060", ""),
    "ghost":       ("dark gray",     "",          "",          "#667", ""),
    "dialog":      ("black",         "white",     "",          "#222", "#eef"),
    "dialog_title": ("dark blue",    "white",     "bold",      "#036", "#eef"),
    "dialog_item": ("black",         "white",     "",          "#222", "#eef"),
    "dialog_focus": ("white",        "dark blue", "standout",  "#fff", "#036"),
}

PALETTES = {"dark": DARK, "light": LIGHT}
BACKGROUND = {"dark": "#000", "light": "#fff"}


def palette(name: str) -> list:
    """urwid's palette form: (name, fg, bg, mono, fg256, bg256)."""
    table = PALETTES.get(name, DARK)
    return [(key, *table[key]) for key in NAMES]


# --- contrast ---------------------------------------------------------------
def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Relative luminance of a "#rgb" or "#rrggbb" colour (WCAG)."""
    text = colour.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    r, g, b = (int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return (0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b))


def contrast(one: str, other: str) -> float:
    """WCAG contrast ratio between two colours, 1.0 (none) to 21.0 (max)."""
    first, second = sorted((luminance(one), luminance(other)), reverse=True)
    return (first + 0.05) / (second + 0.05)


# --- which terminal are we in -----------------------------------------------
_OSC11 = re.compile(rb"rgba?:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)")


def from_environment(env=None) -> str | None:
    env = os.environ if env is None else env
    named = (env.get("INKWELL_THEME") or "").strip().lower()
    if named in PALETTES:
        return named
    pair = env.get("COLORFGBG", "")
    # "15;0" -> light text on a dark background; "0;15" -> the other way.
    if ";" in pair:
        background = pair.split(";")[-1].strip()
        if background.isdigit():
            return "light" if int(background) in (7, 15) else "dark"
    return None


def ask_the_terminal(timeout: float = 0.15) -> str | None:
    """OSC 11: "what colour are you?". Silent if the terminal will not say."""
    try:
        import termios
        import tty
        with open("/dev/tty", "r+b", buffering=0) as tty_file:
            if not os.isatty(tty_file.fileno()):
                return None
            saved = termios.tcgetattr(tty_file)
            try:
                tty.setraw(tty_file.fileno())
                tty_file.write(b"\033]11;?\033\\")
                reply = b""
                while select.select([tty_file], [], [], timeout)[0]:
                    chunk = tty_file.read(32)
                    if not chunk:
                        break
                    reply += chunk
                    if b"\033\\" in reply or b"\a" in reply:
                        break
            finally:
                termios.tcsetattr(tty_file, termios.TCSADRAIN, saved)
    except Exception:                       # noqa: BLE001 - never block startup
        return None
    found = _OSC11.search(reply)
    if not found:
        return None
    parts = []
    for group in found.groups():
        scale = 16 ** len(group) - 1
        parts.append(int(group, 16) / scale)
    red, green, blue = parts
    bright = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "light" if bright > 0.5 else "dark"


def detect(env=None, ask=True) -> str:
    """Best guess at the terminal's background, defaulting to dark."""
    return (from_environment(env)
            or (ask_the_terminal() if ask else None)
            or "dark")


def other(name: str) -> str:
    return "light" if name == "dark" else "dark"
