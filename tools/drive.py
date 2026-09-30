#!/usr/bin/env python3
"""Drive inkwell inside a pty and print what the screen actually shows.

There is no terminal in CI (or in an agent's shell), so this is how the app
gets exercised end to end: a real pty, real keystrokes, real SIGWINCH, and a
just-enough VT parser to turn the output back into a grid of characters.

    python3 tools/drive.py            # run the built-in scenarios
"""

from __future__ import annotations

import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSI = re.compile(rb"\x1b\[([0-9;?]*)([A-Za-z])")


class Screen:
    """A character grid that understands the little bit of VT urwid emits."""

    def __init__(self, cols: int, rows: int) -> None:
        self.resize(cols, rows)

    def sgr(self, kind: str, col: int, row: int, wait=0.12) -> None:
        """A mouse event in the SGR form urwid asks terminals for (1006).

        kind is "press", "drag" or "release"; col and row are 0-based.
        """
        code = {"press": 0, "drag": 32, "release": 0}[kind]
        final = "m" if kind == "release" else "M"
        self.key(f"\x1b[<{code};{col + 1};{row + 1}{final}".encode(), wait=wait)

    def drag(self, from_col: int, to_col: int, row: int, steps: int = 4) -> None:
        """Press, sweep across, release -- as a hand would."""
        self.sgr("press", from_col, row)
        for step in range(1, steps + 1):
            at = from_col + round((to_col - from_col) * step / steps)
            self.sgr("drag", at, row)
        self.sgr("release", to_col, row)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.grid = [[" "] * cols for _ in range(rows)]
        self.x = self.y = 0
        self.pending = b""

    def _clear(self, y0, x0, y1, x1):
        for y in range(y0, min(y1 + 1, self.rows)):
            start = x0 if y == y0 else 0
            end = x1 if y == y1 else self.cols - 1
            for x in range(start, min(end + 1, self.cols)):
                self.grid[y][x] = " "

    def feed(self, data: bytes) -> None:
        # A read can land mid-character or mid-escape; hold the tail back.
        data = self.pending + data
        self.pending = b""
        # A chunk can end in the middle of an escape sequence; hold it back
        # rather than printing the tail as text.
        cut = data.rfind(b"\x1b")
        if cut >= 0 and not CSI.match(data, cut) and len(data) - cut < 24:
            self.pending, data = data[cut:], data[:cut]
        for back in range(1, min(4, len(data)) + 1):
            lead = data[-back]
            if lead < 0x80:
                break
            need = 4 if lead >= 0xF0 else 3 if lead >= 0xE0 else 2 if lead >= 0xC0 else 0
            if need and need > back:
                self.pending = data[-back:]
                data = data[:-back]
                break
            if need:
                break
        i = 0
        while i < len(data):
            match = CSI.match(data, i)
            if match:
                self._csi(match.group(1).decode(), match.group(2).decode())
                i = match.end()
                continue
            byte = data[i:i + 1]
            if byte == b"\x1b":                       # other escape: skip 1-2 bytes
                i += 2 if data[i + 1:i + 2] in (b"(", b")", b"#") else 1
                i += 1 if data[i:i + 1] in (b"B", b"0") else 0
                continue
            if byte in (b"\x0e", b"\x0f"):            # charset shifts
                i += 1
                continue
            if byte == b"\r":
                self.x = 0
            elif byte == b"\n":
                self.y = min(self.y + 1, self.rows - 1)
            elif byte == b"\b":
                self.x = max(0, self.x - 1)
            elif byte >= b" ":
                # Decode one utf-8 character.
                length = 1
                first = data[i]
                if first >= 0xF0:
                    length = 4
                elif first >= 0xE0:
                    length = 3
                elif first >= 0xC0:
                    length = 2
                char = data[i:i + length].decode("utf-8", "replace")
                if self.y < self.rows and self.x < self.cols:
                    self.grid[self.y][self.x] = char
                self.x += 1
                i += length
                continue
            i += 1

    def _csi(self, params: str, final: str) -> None:
        nums = [int(p) for p in params.split(";") if p.isdigit()]
        n = nums[0] if nums else 0
        if final in "Hf":
            self.y = min(max((nums[0] if nums else 1) - 1, 0), self.rows - 1)
            self.x = min(max((nums[1] if len(nums) > 1 else 1) - 1, 0), self.cols - 1)
        elif final == "A":
            self.y = max(0, self.y - max(1, n))
        elif final == "B":
            self.y = min(self.rows - 1, self.y + max(1, n))
        elif final == "C":
            self.x = min(self.cols - 1, self.x + max(1, n))
        elif final == "D":
            self.x = max(0, self.x - max(1, n))
        elif final == "J":
            if n == 0:
                self._clear(self.y, self.x, self.rows - 1, self.cols - 1)
            elif n == 1:
                self._clear(0, 0, self.y, self.x)
            else:
                self._clear(0, 0, self.rows - 1, self.cols - 1)
        elif final == "K":
            if n == 0:
                self._clear(self.y, self.x, self.y, self.cols - 1)
            elif n == 1:
                self._clear(self.y, 0, self.y, self.x)
            else:
                self._clear(self.y, 0, self.y, self.cols - 1)

    def text(self) -> list[str]:
        return ["".join(row).rstrip() for row in self.grid]

    def show(self, label: str) -> None:
        bar = "─" * self.cols
        print(f"\n┌─ {label} ({self.cols}×{self.rows}) {bar[len(label) + 6:]}")
        for line in self.text():
            print("│" + line)
        print("└" + bar)


class Driver:
    def __init__(self, args, cols=100, rows=30, env=None) -> None:
        self.cols, self.rows = cols, rows
        self.master, slave = pty.openpty()
        self.set_size(cols, rows)
        environ = dict(os.environ, TERM="xterm-256color", PYTHONUNBUFFERED="1")
        environ.update(env or {})
        self.proc = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave,
                                     cwd=ROOT, env=environ, close_fds=True)
        os.close(slave)
        self.screen = Screen(cols, rows)
        self.raw = bytearray()

    def set_size(self, cols: int, rows: int) -> None:
        fcntl.ioctl(self.master, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0))

    def pump(self, seconds=0.35) -> None:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if not ready:
                continue
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.raw += chunk
            self.screen.feed(chunk)

    def send(self, text: str, pause=0.05) -> None:
        for ch in text:
            os.write(self.master, ch.encode())
            time.sleep(pause)
            self.pump(0.02)

    def key(self, seq: bytes, wait=0.25) -> None:
        os.write(self.master, seq)
        self.pump(wait)

    def click(self, col: int, row: int) -> None:
        """X10 mouse press, which is what urwid asks the terminal for."""
        self.key(bytes([0x1B, ord("["), ord("M"), 32, 33 + col, 33 + row]))
        self.key(bytes([0x1B, ord("["), ord("M"), 35, 33 + col, 33 + row]))

    def sgr(self, kind: str, col: int, row: int, wait=0.12) -> None:
        """A mouse event in the SGR form urwid asks terminals for (1006).

        kind is "press", "drag" or "release"; col and row are 0-based.
        """
        code = {"press": 0, "drag": 32, "release": 0}[kind]
        final = "m" if kind == "release" else "M"
        self.key(f"\x1b[<{code};{col + 1};{row + 1}{final}".encode(), wait=wait)

    def drag(self, from_col: int, to_col: int, row: int, steps: int = 4) -> None:
        """Press, sweep across, release -- as a hand would."""
        self.sgr("press", from_col, row)
        for step in range(1, steps + 1):
            at = from_col + round((to_col - from_col) * step / steps)
            self.sgr("drag", at, row)
        self.sgr("release", to_col, row)

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self.set_size(cols, rows)
        self.screen.resize(cols, rows)
        self.proc.send_signal(signal.SIGWINCH)
        self.pump(0.6)

    def close(self) -> int:
        self.key(b"\x1b[21~", wait=0.4)      # F10
        try:
            return self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return -1

    def crashed(self) -> str:
        text = bytes(self.raw).decode("utf-8", "replace")
        return "Traceback" in text and text[text.find("Traceback"):][:1200] or ""


def llm_scenario():
    """Watch the model's formatting land on notes typed as plain prose."""
    d = Driver([sys.executable, "-m", "inkwell", "--no-save"], cols=92, rows=26)
    d.pump(1.0)
    d.send("Thermals ")
    d.send("the plate stack needs to shed 180 watts without a fan. ")
    d.send("remember to email the vendor about perforated aluminium stock. ")
    d.send("lead time is about three weeks. ")
    d.send("cut the plate then bend the flange then clinch the standoffs. ")
    d.pump(1.0)
    d.screen.show("as typed, formatted from the markup alone")
    d.pump(20.0)
    d.screen.show("after the model formatted it")
    code = d.close()
    print("\nexit code:", code)
    return 1 if (d.crashed() or code != 0) else 0


def click_scenario():
    """Click into a note, then click off it and watch it go back to normal."""
    d = Driver([sys.executable, "-m", "inkwell", "--no-save", "--no-llm"],
               cols=92, rows=22)
    d.pump(1.0)
    d.send("# Inkwell")
    d.key(b"\r")
    d.send("- a bullet item")
    d.key(b"\r")
    d.send("some ordinary prose about the plate stack. ")
    d.pump(0.5)
    d.screen.show("three notes, nothing selected")
    d.click(6, 9)
    d.screen.show("clicked a note (edit box open)")
    d.click(6, 11)
    d.screen.show("clicked another (the first closed)")
    d.click(50, 18)
    d.screen.show("clicked blank page (nothing selected)")
    d.click(20, 11)
    d.pump(0.3)
    d.drag(8, 26, 12)
    d.screen.show("dragged across the text to select it")
    code = d.close()
    boom = d.crashed()
    print("\nexit code:", code)
    if boom:
        print("CRASHED:\n" + boom)
    return 1 if (boom or code != 0) else 0


def library_scenario():
    """Open the notebooks dialog, switch notebook, flip the theme."""
    import tempfile
    sys.path.insert(0, ROOT)
    from inkwell import store
    folder = tempfile.mkdtemp()
    store.save([store.Note("# Thermo 3"), store.Note("entropy always increases."),
                store.Note("- reversible: $\\Delta S = 0$")],
               os.path.join(folder, "thermo-3.json"))
    store.save([store.Note("# HW0"), store.Note("- due tonight at 11:59"),
                store.Note("TODO write my own test cases")],
               os.path.join(folder, "hw0.json"))
    d = Driver([sys.executable, "-m", "inkwell", "--theme", "dark",
                "--file", os.path.join(folder, "thermo-3.json"), "--no-llm"],
               cols=86, rows=22, env={"INKWELL_DIR": folder})
    d.pump(1.2)
    d.screen.show("thermo-3, dark")
    d.key(b"\x1b[12~", wait=0.6)          # f2
    d.screen.show("f2: the notebooks folder")
    d.key(b"\x1b[A", wait=0.3)            # up
    d.key(b"\r", wait=0.8)
    d.screen.show("opened the other notebook")
    d.key(b"\x1b[15~", wait=0.6)          # f5
    d.screen.show("f5: light theme")
    code = d.close()
    boom = d.crashed()
    print("\nexit code:", code)
    if boom:
        print("CRASHED:\n" + boom)
    return 1 if (boom or code != 0) else 0


def escape_scenario():
    """Press esc four times and watch the cursor climb the tree.

        [open box] -esc-> [page] -esc-> [composer] -esc-> [folder]

    Read off the screen rather than from the app: the halo's ✎ and its
    button strip mean an open box, a ▌ in the gutter of a note means the
    page, and the folder dialog announces itself.
    """
    import tempfile
    sys.path.insert(0, ROOT)
    from inkwell import store
    folder = tempfile.mkdtemp()
    store.save([store.Note("# Escape Ladder"),
                store.Note("- first item"),
                store.Note("- second item"),
                store.Note("a plain paragraph to stand on.")],
               os.path.join(folder, "ladder.json"))
    d = Driver([sys.executable, "-m", "inkwell", "--theme", "dark", "--no-llm",
                "--file", os.path.join(folder, "ladder.json")],
               cols=86, rows=20, env={"INKWELL_DIR": folder})
    d.pump(1.2)

    ok = True

    def where() -> str:
        """Which level of the tree the screen is showing."""
        rows = d.screen.text()
        if any("new:" in line for line in rows):
            return "root"
        if any("✎" in line for line in rows):
            return "editing"
        if any(line.startswith("▌") for line in rows[:-2]):
            return "page"
        return "composer"

    def check(label, want):
        nonlocal ok
        got = where()
        print(("PASS " if got == want else f"FAIL (saw {got}) ") + label)
        ok &= got == want

    d.key(b"\x1b[A", wait=0.4)            # up out of the composer, into the page
    check("arrow up out of the composer reaches the page", "page")
    d.key(b"\r", wait=0.4)                # enter opens the note
    check("enter opens the note", "editing")
    d.send(" and typed on the way", pause=0.02)
    d.screen.show("deepest: an open box")

    d.key(b"\x1b", wait=0.5)
    check("esc 1: out of the box, still in the page", "page")
    d.screen.show("esc 1: the page, note half-selected")
    d.key(b"\x1b", wait=0.5)
    check("esc 2: down to the composer", "composer")
    d.screen.show("esc 2: the box at the bottom")
    d.key(b"\x1b", wait=0.6)
    check("esc 3: up to the folder of notebooks", "root")
    d.screen.show("esc 3: the root of the tree")
    d.key(b"\x1b", wait=0.6)
    check("esc 4: the root steps aside, back where it came from", "composer")

    kept = [n.text for n in store.load(os.path.join(folder, "ladder.json"))]
    typed = "a plain paragraph to stand on. and typed on the way"
    print(("PASS " if typed in kept else "FAIL ")
          + "going up kept what was typed on the way")
    ok &= typed in kept

    code = d.close()
    boom = d.crashed()
    print("\nexit code:", code)
    if boom:
        print("CRASHED:\n" + boom)
    return 0 if (ok and not boom and code == 0) else 1


def shelf_scenario():
    """Two books in one folder: pick one, read it, esc back out through both.

        [open box] -esc-> [page] -esc-> [composer] -esc-> [contents] -esc-> [shelf]
    """
    import tempfile
    sys.path.insert(0, ROOT)
    from pathlib import Path
    from inkwell import reader, store
    folder = Path(tempfile.mkdtemp())
    for prefix, title, chapters in (
            ("iar", "Autonomous Robots",
             {"01-introduction": ["# 1  Introduction", "## 1.1  Sensing",
                                  "A robot senses before it acts."],
              "02-kinematics": ["# 2  Kinematics", "## 2.1  Forward",
                                "Odometry drifts as the wheels slip."]}),
            ("thermo", "Engineering Thermodynamics",
             {"01-first-law": ["# 1  The First Law", "## 1.1  Energy",
                               "Energy is conserved in a closed system."],
              "02-entropy": ["# 2  Entropy", "## 2.1  Reversibility",
                             "Entropy always increases."]})):
        for stem, notes in chapters.items():
            store.save([store.Note(t) for t in notes],
                       folder / f"{prefix}-{stem}.json")
        reader.write_manifest(folder, prefix, title)

    d = Driver([sys.executable, "-m", "inkwell.reader", "--theme", "dark"],
               cols=86, rows=20, env={"INKWELL_DIR": str(folder)})
    d.pump(1.6)

    ok = True

    def check(label, cond):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + label)
        ok &= bool(cond)

    screen = "\n".join(d.screen.text())
    check("opens on the shelf when the folder holds two books",
          "Autonomous Robots" in screen and "Engineering Thermodynamics" in screen)
    check("the shelf says how much of each book there is", "chapters" in screen)
    d.screen.show("the shelf: two books, discovered not configured")

    d.send("thermo", pause=0.04)
    screen = "\n".join(d.screen.text())
    check("typing filters the shelf",
          "Engineering Thermodynamics" in screen
          and "Autonomous Robots" not in screen)

    d.key(b"\r", wait=0.8)
    screen = "\n".join(d.screen.text())
    check("enter opens that book's contents",
          "The First Law" in screen and "Entropy" in screen)
    d.screen.show("its contents -- chapters and sections")

    d.key(b"\r", wait=0.4)              # enter on a chapter unfolds it
    screen = "\n".join(d.screen.text())
    check("enter unfolds a chapter into its sections", "1.1  Energy" in screen)
    d.key(b"\x1b[B", wait=0.2)          # down onto that section
    d.key(b"\r", wait=1.0)              # ...and open it
    screen = "\n".join(d.screen.text())
    check("enter on a section opens the chapter there",
          "type to search the book" not in screen)
    d.screen.show("reading a chapter of the book that was picked")

    d.key(b"\x1b[A", wait=0.4)          # up into the page
    d.key(b"\r", wait=0.4)              # open the note
    rows = d.screen.text()
    check("a book takes margin notes", any("✎" in r for r in rows))

    for label, want in (("esc 1: out of the box, into the page", "▌"),
                        ("esc 2: down to the composer", None),
                        ("esc 3: up to the contents", "type to search the book"),
                        ("esc 4: up to the shelf", "Autonomous Robots")):
        d.key(b"\x1b", wait=0.6)
        rows = d.screen.text()
        if want is None:
            check(label, not any("✎" in r for r in rows)
                  and not any(r.startswith("▌") for r in rows[:-2]))
        elif want == "▌":
            check(label, any(r.startswith("▌") for r in rows[:-2]))
        else:
            check(label, want in "\n".join(rows))
    d.screen.show("esc 4: back on the shelf, having climbed five levels")

    code = d.close()
    boom = d.crashed()
    print("\nexit code:", code)
    if boom:
        print("CRASHED:\n" + boom)
    return 0 if (ok and not boom and code == 0) else 1


def scenario():
    """Type a small document and re-lay it at four widths."""
    d = Driver([sys.executable, "-m", "inkwell", "--no-save", "--no-llm"],
               cols=100, rows=34)
    d.pump(1.0)
    for line in ("# Cube Coffee Demo", "## Thermals"):
        d.send(line)
        d.key(b"\r")
    d.send("the plate stack has to shed 180W without a fan. ")
    for line in ("- perforated aluminium, 0.125in", "- 22ga CRS as the fallback",
                 "  - only if the vendor is out of alu", "fin pitch: 0.4mm",
                 "open area: 23%", "vendor lead time: 3 weeks",
                 "TODO email the vendor about stock", "1. cut the plate",
                 "2. bend the flange", "3. clinch the standoffs",
                 "conduction :: heat moving through the plate itself",
                 "$$Q = hA\\Delta T$$", "how thick does the plate need to be?",
                 "Copper || Aluminium", "400 W/mK || 205 W/mK",
                 "> lot size one means the line reconfigures itself",
                 "`partkit/src/clinch.py`", "!do not ship without the gasket"):
        d.send(line)
        d.key(b"\r")
    d.pump(0.8)
    d.screen.show("typed at 100 cols")

    for cols, rows in ((64, 34), (44, 30), (30, 24)):
        d.resize(cols, rows)
        d.screen.show(f"re-laid at {cols}")

    code = d.close()
    boom = d.crashed()
    print("\nexit code:", code)
    if boom:
        print("CRASHED:\n" + boom)
    return 1 if (boom or code != 0) else 0


if __name__ == "__main__":
    if "--llm" in sys.argv:
        sys.exit(llm_scenario())
    if "--library" in sys.argv:
        sys.exit(library_scenario())
    if "--escape" in sys.argv:
        sys.exit(escape_scenario())
    if "--shelf" in sys.argv:
        sys.exit(shelf_scenario())
    sys.exit(click_scenario() if "--clicks" in sys.argv else scenario())
