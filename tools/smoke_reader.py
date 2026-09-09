"""Drive the built reader archive in a real pty: menu, open a section, back, quit.

    python3 tools/smoke_reader.py dist/IntroRobotics.pyz /tmp/some-empty-folder
"""
import os, sys, re
sys.path.insert(0, os.getcwd())
from tools.drive import Driver
pyz, home = sys.argv[1], sys.argv[2]
sys.path.insert(0, pyz)                  # the archive carries inkwell and urwid
from inkwell.pdf import LOOKALIKE        # noqa: E402

def plain(text):
    """Headings are drawn in bold look-alike glyphs; read them back as ASCII."""
    return "".join(LOOKALIKE.get(c, (c,))[0] for c in text)
d = Driver([sys.executable, pyz], cols=100, rows=30, env={"INKWELL_DIR": home, "PYTHONPATH": ""})
d.pump(2.5)
screen = "\n".join(d.screen.text())
ok = True
def check(label, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + label); ok &= bool(cond)
check("contents menu shows the book title", "Introduction to Autonomous Robots" in screen)
check("chapters listed", "1  Introduction" in screen and "Kinematics" in screen)
for _ in range(3): d.key(b"\x1b[B", wait=0.15)         # down x3 -> 3 Kinematics
d.key(b"\r", wait=0.4)                                  # expand
screen = "\n".join(d.screen.text())
check("chapter unfolds into sections", "3.1  Forward Kinematics" in screen)
d.key(b"\x1b[B", wait=0.15); d.key(b"\x1b[B", wait=0.15)   # onto 3.1 (after 3, Part callout?) 
d.key(b"\r", wait=1.0); d.pump(2.5)                    # open (254 notes to lay out)
screen = plain("\n".join(d.screen.text()))
check("menu closed, chapter open at the section", "type to search the book" not in screen and "3.1.1 Forward Kinematics" in screen)
check("status line names the chapter", re.search(r"iar 03 kinematics.*notes", screen) is not None)
d.key(b"\x1bOQ", wait=0.6)                              # F2 -> contents again
screen = "\n".join(d.screen.text())
check("f2 brings the contents back", "type to search the book" in screen)
d.send("kalman", pause=0.03); d.pump(0.5)
screen = "\n".join(d.screen.text())
check("typing searches the whole book", "Kalman Filter" in screen and "passages" in screen)
check("passages are shown in context", "Extended Kalman Filter" in screen and "…" in screen)
d.key(b"\x1b", wait=0.5)                                # esc closes the menu
d.key(b"\x06", wait=0.6)                                # ctrl f -> contents, to search
screen = "\n".join(d.screen.text())
check("ctrl f opens the search", "type to search the book" in screen)
d.key(b"\x1b", wait=0.5)
code = d.close()
check("f10 exits cleanly (code 0)", code == 0)
check("no traceback anywhere", not d.crashed())
if d.crashed(): print(d.crashed())
print("--- last screen before quit ---"); print("\n".join(d.screen.text()[:12]))
sys.exit(0 if ok else 1)
