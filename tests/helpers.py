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


def a_monospace_face():
    """(path, index) of the face `pdf.export` will actually draw with here.

    The PDF tests inspect glyph ids, so they have to ask the same face the
    exporter picked -- Menlo on a Mac, DejaVu or Liberation on Linux. Reading
    ids out of a hardcoded Menlo was both unportable and, off a Mac, wrong.
    """
    import unittest
    from inkwell import pdf
    try:
        return pdf.fonts()["regular"]
    except pdf.NoFont:
        raise unittest.SkipTest("no monospace TrueType font on this machine")
