import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urwid

urwid.set_encoding("utf8")


def lines(canvas):
    return [row.decode("utf-8", "replace") for row in canvas.text]


def render_flow(widget, cols, focus=False):
    return lines(widget.render((cols,), focus))


def retype(widget, text):
    """Replace an open edit box's text, cursor at the end, as a person would."""
    widget._edit.set_edit_text(text)
    widget._edit.edit_pos = len(text)
    return widget
