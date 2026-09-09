#!/usr/bin/env python3
"""Type a whole lecture into inkwell and print the page.

    python3 tools/lecture.py            # 92 columns
    python3 tools/lecture.py 60 120     # any widths you like

This is the eyeball test: a realistic stream of jotted notes, rendered as
the finished page. tests/test_lecture.py asserts on the same stream.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urwid

urwid.set_encoding("utf8")

from inkwell.app import Inkwell                     # noqa: E402
from inkwell.widgets import VIEW                    # noqa: E402
from tests.lecture_notes import STREAM              # noqa: E402


def build(rows=200, llm=False):
    app = Inkwell(None, use_llm=llm)
    VIEW.rows = rows
    for text, how in STREAM:
        if how == "compose":
            for ch in text:
                app.composer.keypress((60,), ch)
            if app.composer.edit_text.strip():
                app.composer.flush()
        else:
            app.commit(text)
    return app


def page(app, cols, rows=None):
    """Every row of the document, not just the visible window."""
    VIEW.cols, VIEW.rows = cols, rows or 200
    out = []
    for widget in app._notes:
        canvas = widget.render((cols,), False)
        out += [line.decode("utf-8").rstrip() for line in canvas.text]
    return out


def wait_for_the_copy_editor(app, seconds=240):
    """Let the model finish, then apply what it said."""
    import time
    start = time.time()
    while app.muse.pending and time.time() - start < seconds:
        time.sleep(1.0)
        app._absorb()
    app._absorb()
    print(f"  copy editor: {app.muse.failures} failures, "
          f"{time.time() - start:.0f}s")


def main(argv):
    llm = "--llm" in argv
    widths = [int(x) for x in argv[1:] if x.isdigit()] or [92]
    app = build(llm=llm)
    if llm:
        wait_for_the_copy_editor(app)
    for cols in widths:
        print(f"\n{'═' * cols}\n{f'  {len(app._notes)} notes at {cols} columns':<{cols}}\n{'═' * cols}")
        for line in page(app, cols):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
