"""The clipboard.

The system one, so text moves between inkwell and everything else on the
machine; an in-process one as a fallback when there is no `pbcopy` (a Linux
box, a test, a pipe).
"""

from __future__ import annotations

import subprocess
import sys


def commands(platform: str = sys.platform) -> tuple:
    """The (copy, paste) commands a platform ships with."""
    if platform == "darwin":
        return (["pbcopy"], ["pbpaste"])
    if platform == "win32":
        return (["clip"], ["powershell", "-NoProfile", "-Command", "Get-Clipboard"])
    return (["xclip", "-selection", "clipboard"],
            ["xclip", "-selection", "clipboard", "-o"])


COPY, PASTE = commands()

_held = ""          # the fallback clipboard


def copy(text: str) -> bool:
    """Put text on the clipboard. True if the system took it."""
    global _held
    _held = text
    try:
        subprocess.run(COPY, input=text.encode(), timeout=2, check=True)
    except Exception:                       # noqa: BLE001 - fall back quietly
        return False
    return True


def paste() -> str:
    """Whatever is on the clipboard."""
    try:
        done = subprocess.run(PASTE, capture_output=True, timeout=2, check=True)
    except Exception:                       # noqa: BLE001
        return _held
    return done.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
