"""inkwell/reader.py: a textbook as a set of notebooks with a contents menu.

The reader is inkwell plus a table of contents: chapters and their sections
in reading order, filtered as you type, Enter opens the notebook scrolled to
that section. tools/build_reader.py packs it, the notebooks and a vendored
urwid into one .pyz that runs on any machine with Python 3.9+.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urwid                                # noqa: E402

urwid.set_encoding("utf8")

from inkwell import clip, pdf, reader, store  # noqa: E402
from inkwell.app import Inkwell            # noqa: E402
from inkwell.widgets import VIEW           # noqa: E402


def make_book(folder: Path, prefix="iar"):
    """Three tiny chapters, written the way tex2ink writes them."""
    chapters = {
        f"{prefix}-00-preface": ["# Preface", "Hello.",
                                 "This book explains odometry from first "
                                 "principles."],
        f"{prefix}-01-introduction": ["# 1  Introduction", "Text.",
                                      "## 1.1  Intelligence", "More.",
                                      "### 1.1.1  Embodiment", "Deep.",
                                      "## Exercises", "1. Think."]
        + [f"Filler paragraph number {n} keeps the page long enough to scroll."
           for n in range(30)],
        f"{prefix}-02-kinematics": ["# 2  Kinematics", "## 2.1  Forward Kinematics",
                                    "$$x = 1$$",
                                    "Odometry drifts as the wheels slip.",
                                    "## 2.2  Inverse Kinematics",
                                    "The arm solves for its joint angles."],
        f"{prefix}-a-trigonometry": ["# A  Trigonometry", "## A.1  Sine", "sin.",
                                     "Padding words before the middle. " * 4
                                     + "A gyroscope sits here. "
                                     + "Padding words after the middle. " * 4],
    }
    folder.mkdir(parents=True, exist_ok=True)
    now = 1_800_000_000
    for i, (name, texts) in enumerate(chapters.items()):
        path = folder / (name + ".json")
        store.save([store.Note(t) for t in texts], path)
        os.utime(path, (now - i, now - i))
    (folder / "HW0.json").write_text(json.dumps([{"text": "# HW0"}]))
    return folder


class Contents(unittest.TestCase):
    def setUp(self):
        self.folder = make_book(Path(tempfile.mkdtemp()))

    def test_chapters_come_in_reading_order_with_their_sections(self):
        chapters = reader.contents(self.folder, "iar")
        self.assertEqual([c.title for c in chapters],
                         ["Preface", "1  Introduction", "2  Kinematics",
                          "A  Trigonometry"])
        intro = chapters[1]
        self.assertEqual([(s.index, s.level, s.title) for s in intro.sections],
                         [(2, 1, "1.1  Intelligence"), (4, 2, "1.1.1  Embodiment"),
                          (6, 1, "Exercises")])
        self.assertEqual(intro.count, 38)

    def test_other_notebooks_in_the_folder_are_not_part_of_the_book(self):
        titles = [c.title for c in reader.contents(self.folder, "iar")]
        self.assertNotIn("HW0", titles)

    def test_rows_show_collapsed_chapters_until_one_is_opened(self):
        chapters = reader.contents(self.folder, "iar")
        rows = reader.rows(chapters, expanded=set(), query="")
        self.assertEqual([r.text for r in rows],
                         ["Preface", "1  Introduction", "2  Kinematics",
                          "A  Trigonometry"])
        rows = reader.rows(chapters, expanded={chapters[1].path}, query="")
        self.assertEqual([r.text for r in rows][1:5],
                         ["1  Introduction", "  1.1  Intelligence",
                          "    1.1.1  Embodiment", "  Exercises"])
        self.assertEqual(rows[2].section.index, 2)

    def test_typing_filters_sections_across_the_whole_book(self):
        chapters = reader.contents(self.folder, "iar")
        rows = reader.rows(chapters, expanded=set(), query="kine")
        self.assertEqual([r.text for r in rows],
                         ["2  Kinematics", "  2.1  Forward Kinematics",
                          "  2.2  Inverse Kinematics"])
        rows = reader.rows(chapters, expanded=set(), query="sine")
        self.assertEqual([(r.chapter.title, r.text) for r in rows],
                         [("A  Trigonometry", "A  Trigonometry"),
                          ("A  Trigonometry", "  A.1  Sine")])
        self.assertEqual(reader.rows(chapters, set(), "zzz"), [])


class Menu(unittest.TestCase):
    def setUp(self):
        self.folder = make_book(Path(tempfile.mkdtemp()))
        self.chapters = reader.contents(self.folder, "iar")
        self.menu = reader.Menu(self.chapters)
        self.got = []
        urwid.connect_signal(self.menu, "chosen",
                             lambda _w, path, index: self.got.append((path, index)))
        urwid.connect_signal(self.menu, "closed", lambda _w: self.got.append("closed"))

    def screen(self):
        canvas = self.menu.render((70, 20), True)
        return [line.decode("utf-8").rstrip() for line in canvas.text]

    def test_enter_on_a_chapter_expands_it_and_again_opens_it(self):
        self.menu.keypress((70, 20), "down")            # onto Introduction
        self.menu.keypress((70, 20), "enter")
        self.assertIn("1.1  Intelligence", "\n".join(self.screen()))
        self.assertEqual(self.got, [])
        self.menu.keypress((70, 20), "enter")
        self.assertEqual(self.got, [(self.chapters[1].path, 0)])

    def test_enter_on_a_section_opens_the_chapter_there(self):
        self.menu.keypress((70, 20), "down")
        self.menu.keypress((70, 20), "right")           # expand
        self.menu.keypress((70, 20), "down")
        self.menu.keypress((70, 20), "down")            # 1.1.1 Embodiment
        self.menu.keypress((70, 20), "enter")
        self.assertEqual(self.got, [(self.chapters[1].path, 4)])

    def test_typing_filters_and_enter_opens_the_first_match(self):
        for ch in "forward":
            self.menu.keypress((70, 20), ch)
        rows = "\n".join(self.screen())
        self.assertIn("2.1  Forward Kinematics", rows)
        self.assertNotIn("1  Introduction", rows)
        self.menu.keypress((70, 20), "enter")
        self.assertEqual(self.got, [(self.chapters[2].path, 1)])

    def test_backspace_clears_the_filter_and_f2_closes_the_menu(self):
        self.menu.keypress((70, 20), "k")
        self.menu.keypress((70, 20), "backspace")
        self.assertIn("Introduction", "\n".join(self.screen()))
        # Esc is a rung of the tree, so the menu hands it up (test_escape.py);
        # f2 is the toggle it keeps for itself.
        self.assertEqual(self.menu.keypress((70, 20), "esc"), "esc")
        self.assertEqual(self.got, [])
        self.menu.keypress((70, 20), "f2")
        self.assertEqual(self.got, ["closed"])

    def test_the_menu_is_readable_at_narrow_widths(self):
        canvas = self.menu.render((44, 12), True)
        rows = [line.decode("utf-8").rstrip() for line in canvas.text]
        self.assertTrue(all(len(r) <= 44 for r in rows))
        self.assertTrue(any("Introduction" in r for r in rows))


class Search(unittest.TestCase):
    """Typing in the contents searches the prose, not only the headings."""

    def setUp(self):
        self.folder = make_book(Path(tempfile.mkdtemp()))
        self.chapters = reader.contents(self.folder, "iar")

    def screen(self, menu, size=(70, 20)):
        canvas = menu.render(size, True)
        return [line.decode("utf-8").rstrip() for line in canvas.text]

    def typed(self, word, size=(70, 20)):
        menu = reader.Menu(self.chapters)
        got = []
        urwid.connect_signal(menu, "chosen",
                             lambda _w, path, index: got.append((path, index)))
        for ch in word:
            menu.keypress(size, ch)
        return menu, got

    # -- finding ---------------------------------------------------------------
    def test_a_word_in_the_prose_is_found_wherever_it_is(self):
        hits = reader.search(self.chapters, "odometry")
        self.assertEqual([(h.chapter.title, h.index,
                           h.section.title if h.section else None) for h in hits],
                         [("Preface", 2, None),
                          ("2  Kinematics", 3, "2.1  Forward Kinematics")])

    def test_case_does_not_matter_but_a_letter_or_two_is_not_a_search(self):
        self.assertEqual(len(reader.search(self.chapters, "ODOMETRY")), 2)
        self.assertEqual(reader.search(self.chapters, "od"), [])

    def test_a_word_only_headings_say_is_not_repeated_as_a_passage(self):
        self.assertEqual(reader.search(self.chapters, "kinematics"), [])

    def test_the_number_of_passages_is_capped(self):
        self.assertEqual(len(reader.search(self.chapters, "the", limit=5)), 5)

    # -- reading a hit ---------------------------------------------------------
    def test_the_snippet_marks_the_word_inside_its_sentence(self):
        hit = reader.search(self.chapters, "odometry")[0]
        parts = reader.snippet(hit)
        self.assertEqual("".join(text for _attr, text in parts),
                         "This book explains odometry from first principles.")
        self.assertEqual([t for attr, t in parts if attr == "match"], ["odometry"])

    def test_a_long_passage_is_trimmed_around_the_match(self):
        hit = reader.search(self.chapters, "gyroscope")[0]
        line = "".join(text for _attr, text in reader.snippet(hit, width=40))
        self.assertIn("gyroscope", line)
        self.assertLessEqual(len(line), 42)         # the width, plus two ellipses
        self.assertTrue(line.startswith("…") and line.endswith("…"), line)

    # -- in the menu -----------------------------------------------------------
    def test_passages_are_listed_under_their_chapter_and_enter_opens_the_note(self):
        menu, got = self.typed("odometry")
        screen = "\n".join(self.screen(menu))
        self.assertIn("Preface", screen)
        self.assertIn("odometry from first principles", screen)
        self.assertIn("2  Kinematics", screen)
        self.assertNotIn("1  Introduction", screen)
        menu.keypress((70, 20), "enter")
        self.assertEqual(got, [(self.chapters[0].path, 2)])

    def test_the_chapter_a_passage_is_in_stays_on_screen_above_it(self):
        menu, _got = self.typed("odometry", size=(70, 8))
        screen = "\n".join(self.screen(menu, (70, 8)))
        self.assertIn("Preface", screen)                # only two rows fit
        self.assertIn("odometry from first principles", screen)
        self.assertNotIn("2  Kinematics", screen)

    def test_a_passage_says_which_section_it_is_in(self):
        menu, _got = self.typed("wheels")
        row = next(r for r in menu._rows if r.hit)
        self.assertIn("2.1", row.text)
        self.assertIn("Odometry drifts", row.text)

    def test_sections_still_come_before_passages_that_mention_them(self):
        menu, got = self.typed("forward")
        self.assertIn("2.1  Forward Kinematics", "\n".join(self.screen(menu)))
        menu.keypress((70, 20), "enter")
        self.assertEqual(got, [(self.chapters[2].path, 1)])

    def test_the_word_itself_is_marked_in_the_line(self):
        menu, _got = self.typed("odometry")
        row = next(r for r in menu._rows if r.hit)
        line = urwid.AttrMap(reader._Line(row), reader.LINE)
        runs = [(attr, text) for chunk in line.render((70,), False).content()
                for attr, _cs, text in chunk]
        self.assertIn(("dialog_title", b"odometry"), runs)
        self.assertTrue(any(attr == "dialog_item" for attr, _t in runs))

    def test_the_finder_says_how_much_it_found(self):
        menu, _got = self.typed("odometry")
        header = next(r for r in self.screen(menu) if "find:" in r)
        self.assertIn("2 passages", header)

    def test_a_search_with_nothing_behind_it_says_so(self):
        menu, _got = self.typed("zzzz")
        self.assertIn("nothing matches", "\n".join(self.screen(menu)))

    # -- from the command line -------------------------------------------------
    def test_find_prints_every_passage_with_its_place(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = reader.main(["--find", "odometry", "--dir", str(self.folder)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("Preface", text)
        self.assertIn("2.1  Forward Kinematics", text)
        self.assertIn("odometry from first principles", text)
        self.assertNotIn("Introduction", text)

    def test_find_that_matches_nothing_is_an_error(self):
        err, out = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = reader.main(["--find", "zzzz", "--dir", str(self.folder)])
        self.assertEqual(code, 1)
        self.assertIn("nothing", err.getvalue())


class Jumping(unittest.TestCase):
    def setUp(self):
        self.folder = make_book(Path(tempfile.mkdtemp()))
        VIEW.cols, VIEW.rows = 80, 24

    def test_jump_to_puts_a_note_in_focus_at_the_top_of_the_page(self):
        app = Inkwell(self.folder / "iar-01-introduction.json", use_llm=False)
        app.jump_to(4)
        self.assertEqual(app.frame.focus_position, "body")
        self.assertEqual(app.walker.focus, 4)
        self.assertEqual(app.listbox.focus.note.text, "### 1.1.1  Embodiment")
        rows = [line.decode("utf-8") for line in app.frame.render((80, 24), True).text]
        first = next(i for i, r in enumerate(rows) if r.strip())
        self.assertLessEqual(first, 2)          # only the heading's own gap above it
        # The heading is drawn in bold look-alike glyphs; read them back.
        plain = "".join(pdf.LOOKALIKE.get(c, (c,))[0] for c in rows[first])
        self.assertIn("1.1.1", plain)

    def test_reader_opens_a_chapter_at_a_section_from_the_menu(self):
        app = reader.Reader(self.folder / "iar-00-preface.json", theme="dark")
        app.open_contents()
        self.assertIsNotNone(app.menu)
        app.menu._emit("chosen", self.folder / "iar-02-kinematics.json", 1)
        self.assertEqual(app.path.name, "iar-02-kinematics.json")
        self.assertEqual(app.walker.focus, 1)
        self.assertIsNone(app.menu)

    def test_f2_in_the_reader_is_the_contents_not_the_folder(self):
        app = reader.Reader(self.folder / "iar-00-preface.json")
        app._command("f2")
        self.assertIsNotNone(app.menu)
        self.assertIsNone(app.library)
        app._command("f2")
        self.assertIsNone(app.menu)

    def test_ctrl_f_opens_the_contents_to_search_from_inside_a_chapter(self):
        app = reader.Reader(self.folder / "iar-00-preface.json")
        app._command("ctrl f")
        self.assertIsNotNone(app.menu)

    def test_the_reader_never_talks_to_a_model(self):
        app = reader.Reader(self.folder / "iar-00-preface.json")
        self.assertFalse(app.muse.enabled)


class FirstRun(unittest.TestCase):
    def test_bundled_notebooks_are_copied_in_but_never_over_yours(self):
        folder = Path(tempfile.mkdtemp())
        mine = folder / "iar-01-introduction.json"
        mine.write_text(json.dumps([{"text": "# my annotated copy"}]))
        bundle = [("iar-00-preface.json", b'[{"text": "# Preface"}]'),
                  ("iar-01-introduction.json", b'[{"text": "# 1  Introduction"}]')]
        added = reader.install(bundle, folder)
        self.assertEqual([p.name for p in added], ["iar-00-preface.json"])
        self.assertEqual(json.loads(mine.read_text())[0]["text"], "# my annotated copy")
        self.assertEqual(reader.install(bundle, folder), [])

    def test_installed_notebooks_list_in_reading_order(self):
        folder = Path(tempfile.mkdtemp())
        bundle = [(f"iar-{n:02d}-x.json", b'[{"text": "# x"}]') for n in range(5)]
        reader.install(bundle, folder)
        listed = [p.name for p in store.notebooks(folder)]
        self.assertEqual(listed, [f"iar-{n:02d}-x.json" for n in range(5)])

    def test_the_repo_checkout_has_nothing_bundled(self):
        # The notebooks are only put inside the package by the build.
        self.assertEqual(reader.bundled(), [])


class Portability(unittest.TestCase):
    def test_clipboard_commands_follow_the_platform(self):
        self.assertEqual(clip.commands("darwin"), (["pbcopy"], ["pbpaste"]))
        copy, paste = clip.commands("win32")
        self.assertEqual(copy, ["clip"])
        self.assertIn("Get-Clipboard", " ".join(paste))
        copy, paste = clip.commands("linux")
        self.assertEqual(copy[0], "xclip")
        self.assertEqual(paste[0], "xclip")

    def test_pdf_font_is_found_per_platform(self):
        have = {"/System/Library/Fonts/Menlo.ttc",
                "C:\\Windows\\Fonts\\consola.ttf", "C:\\Windows\\Fonts\\consolab.ttf",
                "C:\\Windows\\Fonts\\consolai.ttf", "C:\\Windows\\Fonts\\consolaz.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf"}
        exists = have.__contains__
        mac = pdf.fonts("darwin", exists)
        self.assertEqual(mac["regular"], ("/System/Library/Fonts/Menlo.ttc", 0))
        self.assertEqual(mac["bold italic"], ("/System/Library/Fonts/Menlo.ttc", 3))
        win = pdf.fonts("win32", exists)
        self.assertEqual(win["bold"], ("C:\\Windows\\Fonts\\consolab.ttf", 0))
        lin = pdf.fonts("linux", exists)
        self.assertTrue(lin["italic"][0].endswith("DejaVuSansMono-Oblique.ttf"))
        self.assertEqual(set(mac) == set(win) == set(lin),
                         True)

    def test_missing_fonts_are_a_clear_error_not_a_traceback_from_deep_inside(self):
        with self.assertRaises(pdf.NoFont):
            pdf.fonts("linux", lambda _p: False)

    def test_the_main_loop_does_not_need_a_pipe(self):
        # urwid has no MainLoop.watch_pipe on Windows; the wake-up pipe is
        # only for the model lane, so a reader (no model) never asks for one.
        folder = make_book(Path(tempfile.mkdtemp()))
        app = Inkwell(folder / "iar-00-preface.json", use_llm=False)

        class Loop:
            pass
        app._attach_wakeup(Loop())
        self.assertIsNone(app._wake_fd)


class Build(unittest.TestCase):
    """tools/build_reader.py -> one .pyz that runs from a clean process."""

    @classmethod
    def setUpClass(cls):
        global build_reader
        from tools import build_reader
        cls.tmp = Path(tempfile.mkdtemp())
        book = make_book(cls.tmp / "notebooks")
        cls.pyz = build_reader.build(notebooks=book, out=cls.tmp / "Reader.pyz",
                                     name="Reader")

    def test_the_archive_holds_the_app_its_libraries_and_the_book(self):
        names = set(zipfile.ZipFile(self.pyz).namelist())
        for needed in ("__main__.py", "inkwell/app.py", "inkwell/reader.py",
                       "urwid/__init__.py", "wcwidth/__init__.py",
                       "typing_extensions.py",
                       "inkwell/book/iar-01-introduction.json"):
            self.assertIn(needed, names)
        self.assertNotIn("inkwell/book/HW0.json", names)
        self.assertFalse(any(n.startswith("tests/") or n.startswith("tools/")
                             for n in names))
        self.assertFalse(any(n.endswith(".pyc") for n in names))

    def test_vendored_urwid_is_patched_for_the_39_zip_importer(self):
        # urwid's lazy_import needs loader.exec_module, which zipimport only
        # grew in Python 3.10; the build makes it fall back to a plain import.
        archive = zipfile.ZipFile(self.pyz)
        for name in ("urwid/__init__.py", "urwid/display/__init__.py"):
            self.assertIn('hasattr(spec.loader, "exec_module")',
                          archive.read(name).decode(), name)

    def test_the_archive_is_the_only_file_unless_launchers_are_asked_for(self):
        self.assertEqual(sorted(p.name for p in self.tmp.glob("Reader.*")), ["Reader.pyz"])
        build_reader.launchers(self.pyz, "Reader")
        self.assertTrue((self.tmp / "Reader.command").exists())
        self.assertTrue((self.tmp / "Reader.bat").exists())
        self.assertTrue(os.access(self.tmp / "Reader.command", os.X_OK))

    def test_the_archive_runs_in_a_fresh_interpreter_and_installs_the_book(self):
        home = self.tmp / "home"
        env = {**os.environ, "INKWELL_DIR": str(home), "PYTHONPATH": ""}
        done = subprocess.run([sys.executable, str(self.pyz), "--list"],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("1  Introduction", done.stdout)
        self.assertIn("1.1  Intelligence", done.stdout)
        self.assertTrue((home / "iar-02-kinematics.json").exists())
        self.assertFalse((home / "HW0.json").exists())

    def test_any_book_is_cloned_shallow_from_the_url_it_is_given(self):
        """--clone takes a URL: the build is not tied to one book."""
        asked = []
        build_reader.fetch_book(self.tmp / "clone", "https://example.test/b.git",
                                run=lambda cmd, **kw: asked.append((cmd, kw)))
        (cmd, kw), = asked
        self.assertEqual(cmd[:2], ["git", "clone"])
        self.assertIn("--depth", cmd)
        self.assertEqual(cmd[-2], "https://example.test/b.git")
        self.assertEqual(cmd[-1], str(self.tmp / "clone"))
        self.assertTrue(kw.get("check"))

    def test_where_a_build_gets_its_books_from(self):
        """A URL is cloned, a LaTeX root converted, and neither packs the
        notes folder as it stands -- the common case once a book is in it."""
        self.assertEqual(build_reader.plan(clone="https://example.test/b.git"),
                         "clone")
        self.assertEqual(build_reader.plan(book=self.tmp), "convert")
        self.assertEqual(build_reader.plan(notebooks=self.tmp), "notebooks")
        self.assertEqual(build_reader.plan(), "notebooks")
        with self.assertRaises(SystemExit):
            build_reader.plan(book=self.tmp / "nowhere")

    def test_where_says_where_the_notebooks_live(self):
        home = self.tmp / "home2"
        env = {**os.environ, "INKWELL_DIR": str(home), "PYTHONPATH": ""}
        done = subprocess.run([sys.executable, str(self.pyz), "--where"],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.stdout.strip(), str(home))


if __name__ == "__main__":
    unittest.main()
