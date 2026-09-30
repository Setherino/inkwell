"""A folder of books, not one book.

A book is a naming convention: two or more notebooks sharing a
``<prefix>-<slot>-<title>.json`` name. Nothing knows which book, so a
folder can hold as many as you convert into it and the shelf finds them.
"""

import json
import tempfile
import unittest
from pathlib import Path

from .helpers import lines  # noqa: F401
from .test_reader import make_book
from inkwell import reader, store
from inkwell.app import COMPOSER, EDITING, PAGE, ROOT, SHELF
from inkwell.widgets import VIEW

SIZE = (70, 20)


def two_books(folder=None):
    """Two books and some loose notebooks, all in one folder."""
    folder = Path(folder or tempfile.mkdtemp())
    make_book(folder, prefix="iar")
    make_book(folder, prefix="thermo")
    store.save([store.Note("# HW0")], folder / "hw0.json")
    store.save([store.Note("# Scratch")], folder / "notes.json")
    return folder


class Discovery(unittest.TestCase):
    def setUp(self):
        self.folder = two_books()

    def test_every_book_in_the_folder_is_found(self):
        self.assertEqual(reader.prefixes(self.folder), ["iar", "thermo"])

    def test_loose_notebooks_are_not_books(self):
        found = "\n".join(b.title for b in reader.books(self.folder))
        self.assertNotIn("HW0", found)
        self.assertNotIn("Scratch", found)

    def test_a_lone_notebook_named_like_a_chapter_is_still_just_a_notebook(self):
        bare = Path(tempfile.mkdtemp())
        store.save([store.Note("# One")], bare / "solo-01-chapter.json")
        self.assertEqual(reader.prefixes(bare), [])

    def test_a_manifest_says_it_is_a_book_however_short(self):
        bare = Path(tempfile.mkdtemp())
        store.save([store.Note("# One")], bare / "solo-01-chapter.json")
        reader.write_manifest(bare, "solo", "A Very Short Book")
        self.assertEqual(reader.prefixes(bare), ["solo"])
        (book,) = reader.books(bare)
        self.assertEqual(book.title, "A Very Short Book")

    def test_a_book_carries_its_chapters_in_reading_order(self):
        book = reader.pick_book(reader.books(self.folder), "iar")
        self.assertEqual([c.slot for c in book.chapters][:3], ["00", "01", "02"])
        self.assertGreater(book.notes, 0)

    def test_an_empty_folder_has_no_shelf(self):
        self.assertEqual(reader.books(Path(tempfile.mkdtemp())), [])
        self.assertEqual(reader.books(Path("/no/such/folder")), [])


class Naming(unittest.TestCase):
    def test_a_short_prefix_is_an_acronym_and_a_long_one_is_words(self):
        self.assertEqual(reader.name_of("iar"), "IAR")
        self.assertEqual(reader.name_of("thermo"), "Thermo")
        self.assertEqual(reader.name_of("fluid-mech"), "Fluid Mech")

    def test_a_manifest_beats_the_guess(self):
        folder = Path(tempfile.mkdtemp())
        make_book(folder, prefix="iar")
        self.assertEqual(reader.books(folder)[0].title, "IAR")
        reader.write_manifest(folder, "iar", "Introduction to Autonomous Robots")
        self.assertEqual(reader.books(folder)[0].title,
                         "Introduction to Autonomous Robots")

    def test_a_manifest_round_trips_and_a_broken_one_is_ignored(self):
        folder = Path(tempfile.mkdtemp())
        reader.write_manifest(folder, "x", "A Title", source="/somewhere")
        said = reader.read_manifest(folder, "x")
        self.assertEqual(said["title"], "A Title")
        self.assertEqual(said["source"], "/somewhere")
        reader.manifest_path(folder, "x").write_text("{not json")
        self.assertEqual(reader.read_manifest(folder, "x"), {})

    def test_a_book_is_picked_by_prefix_or_by_part_of_its_title(self):
        folder = two_books()
        reader.write_manifest(folder, "iar", "Introduction to Autonomous Robots")
        shelf = reader.books(folder)
        self.assertEqual(reader.pick_book(shelf, "iar").prefix, "iar")
        self.assertEqual(reader.pick_book(shelf, "autonomous").prefix, "iar")
        self.assertEqual(reader.pick_book(shelf, "THERMO").prefix, "thermo")
        self.assertIsNone(reader.pick_book(shelf, "nothing like it"))


class ShelfWidget(unittest.TestCase):
    def setUp(self):
        VIEW.cols, VIEW.rows = SIZE
        self.folder = two_books()
        reader.write_manifest(self.folder, "iar", "Autonomous Robots")
        self.books = reader.books(self.folder)
        self.chosen = []
        self.shelf = reader.Shelf(self.books, current="thermo")
        import urwid
        urwid.connect_signal(self.shelf, "chosen",
                             lambda _w, book: self.chosen.append(book.prefix))

    def painted(self):
        return "\n".join(lines(self.shelf.render(SIZE, True)))

    def test_it_lists_every_book_with_how_much_of_it_there_is(self):
        shown = self.painted()
        self.assertIn("Autonomous Robots", shown)
        self.assertIn("Thermo", shown)
        self.assertIn("chapters", shown)

    def test_the_book_you_are_reading_is_marked_and_starts_selected(self):
        self.assertIn("▸ Thermo", self.painted())
        self.assertEqual(self.shelf.current_book().prefix, "thermo")

    def test_enter_opens_the_highlighted_book(self):
        self.shelf.keypress(SIZE, "enter")
        self.assertEqual(self.chosen, ["thermo"])

    def test_typing_filters_the_shelf_and_backspace_puts_it_back(self):
        for character in "auto":
            self.shelf.keypress(SIZE, character)
        self.assertEqual([b.prefix for b in self.shelf.shown()], ["iar"])
        for _ in range(4):
            self.shelf.keypress(SIZE, "backspace")
        self.assertEqual(len(self.shelf.shown()), 2)

    def test_a_filter_matching_nothing_says_so_rather_than_going_blank(self):
        for character in "zzz":
            self.shelf.keypress(SIZE, character)
        self.assertIn("no book matches", self.painted())

    def test_it_hands_esc_back_and_keeps_f2_as_its_toggle(self):
        closed = []
        import urwid
        urwid.connect_signal(self.shelf, "closed", lambda _w: closed.append(True))
        self.assertEqual(self.shelf.keypress(SIZE, "esc"), "esc")
        self.assertEqual(closed, [])
        self.shelf.keypress(SIZE, "f2")
        self.assertEqual(closed, [True])

    def test_it_is_readable_at_a_narrow_width(self):
        rows = lines(self.shelf.render((44, 12), True))
        self.assertTrue(all(len(r) <= 44 for r in rows))
        self.assertTrue(any("Thermo" in r for r in rows))


class TheLadder(unittest.TestCase):
    """The shelf is a rung above the contents, and esc walks out through it."""

    def setUp(self):
        VIEW.cols, VIEW.rows = SIZE
        self.folder = two_books()
        self.app = reader.Reader(self.folder / "iar-01-introduction.json",
                                 theme="dark", folder=self.folder)
        self.app.frame.render(SIZE, True)

    def test_the_prefix_comes_from_the_notebook_that_was_opened(self):
        self.assertEqual(self.app.prefix, "iar")

    def test_esc_climbs_page_composer_contents_shelf(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(1)
        self.app.frame.render(SIZE, True)
        self.app.listbox.focus.start_edit()
        self.assertEqual(self.app.depth(), EDITING)
        for expected in (PAGE, COMPOSER, ROOT, SHELF):
            self.app.unhandled("esc")
            self.assertEqual(self.app.depth(), expected)

    def test_esc_never_takes_you_deeper_anywhere_on_the_way(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(1)
        self.app.frame.render(SIZE, True)
        self.app.listbox.focus.start_edit()
        for _ in range(4):
            before = self.app.depth()
            self.app.unhandled("esc")
            self.assertLess(self.app.depth(), before,
                            f"esc did not ascend from level {before}")

    def test_the_shelf_steps_aside_back_to_what_it_covered(self):
        self.app.unhandled("esc")           # composer -> contents
        self.app.unhandled("esc")           # contents -> shelf
        self.assertEqual(self.app.depth(), SHELF)
        self.app.unhandled("esc")
        self.assertIsNone(self.app.shelf)
        self.assertEqual(self.app.depth(), COMPOSER)

    def test_with_only_one_book_there_is_no_shelf_rung(self):
        """Nothing to choose, so the contents is the top."""
        lone = Path(tempfile.mkdtemp())
        make_book(lone, prefix="iar")
        app = reader.Reader(lone / "iar-01-introduction.json", folder=lone)
        app.frame.render(SIZE, True)
        app.unhandled("esc")
        self.assertEqual(app.depth(), ROOT)
        app.unhandled("esc")
        self.assertEqual(app.depth(), COMPOSER, "straight back down, no shelf")

    def test_picking_a_book_off_the_shelf_opens_its_contents(self):
        self.app.open_shelf()
        thermo = reader.pick_book(self.app.books(), "thermo")
        self.app.open_book(thermo)
        self.assertIsNone(self.app.shelf)
        self.assertEqual(self.app.depth(), ROOT)
        self.assertEqual(self.app.prefix, "thermo")
        self.assertIn("Thermo", "\n".join(lines(self.app.menu.render(SIZE, True))))

    def test_f3_goes_straight_to_the_shelf_from_the_contents(self):
        self.app.open_contents()
        self.assertEqual(self.app.depth(), ROOT)
        self.app.unhandled("f3")
        self.assertEqual(self.app.depth(), SHELF)

    def test_the_contents_shows_the_book_you_are_in(self):
        reader.write_manifest(self.folder, "iar", "Autonomous Robots")
        app = reader.Reader(self.folder / "iar-01-introduction.json",
                            folder=self.folder)
        app.frame.render(SIZE, True)
        app.open_contents()
        self.assertIn("Autonomous Robots",
                      "\n".join(lines(app.menu.render(SIZE, True))))


class Cli(unittest.TestCase):
    def setUp(self):
        self.folder = two_books()
        reader.write_manifest(self.folder, "iar", "Autonomous Robots")

    def run_it(self, *argv):
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = reader.main(["--dir", str(self.folder), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_list_with_no_book_named_prints_the_whole_shelf(self):
        code, out, _ = self.run_it("--list")
        self.assertEqual(code, 0)
        self.assertIn("Autonomous Robots", out)
        self.assertIn("Thermo", out)

    def test_list_of_one_book_prints_its_chapters_and_sections(self):
        code, out, _ = self.run_it("iar", "--list")
        self.assertEqual(code, 0)
        self.assertIn("1  Introduction", out)
        self.assertIn("1.1  Intelligence", out)
        self.assertNotIn("Thermo", out)

    def test_find_searches_every_book_on_the_shelf(self):
        code, out, _ = self.run_it("--find", "odometry")
        self.assertEqual(code, 0)
        self.assertIn("odometry", out.lower())

    def test_find_inside_one_book_stays_in_it(self):
        code, out, _ = self.run_it("thermo", "--find", "odometry")
        self.assertIn("odometry", out.lower())

    def test_a_book_that_is_not_there_lists_what_is(self):
        code, _out, err = self.run_it("nosuchbook")
        self.assertEqual(code, 1)
        self.assertIn("iar", err)
        self.assertIn("thermo", err)

    def test_an_empty_folder_explains_what_a_book_is(self):
        self.folder = Path(tempfile.mkdtemp())
        code, _out, err = self.run_it("--list")
        self.assertEqual(code, 1)
        self.assertIn("prefix", err)

    def test_a_bare_chapter_still_works_on_a_one_book_shelf(self):
        """"reader 3" must keep working without naming the book."""
        self.folder = Path(tempfile.mkdtemp())
        make_book(self.folder, prefix="iar")
        code, out, _ = self.run_it("2", "--list")
        self.assertEqual(code, 0)
        self.assertIn("Kinematics", out)


class Fetching(unittest.TestCase):
    """Getting a book must stay one command with nothing to look up."""

    def setUp(self):
        from tools import build_reader
        self.build_reader = build_reader

    def test_a_catalogue_name_resolves_to_a_url(self):
        url = self.build_reader.source_url("iar")
        self.assertTrue(url.startswith("https://"))
        self.assertIn("Introduction-to-Autonomous-Robots", url)

    def test_a_url_is_passed_through_untouched(self):
        """The catalogue is a convenience, not the only way in."""
        self.assertEqual(self.build_reader.source_url("https://example.test/b.git"),
                         "https://example.test/b.git")

    def test_every_catalogued_book_says_where_it_is_and_how_it_is_licensed(self):
        self.assertTrue(self.build_reader.CATALOGUE)
        for name, entry in self.build_reader.CATALOGUE.items():
            url, title, licence = entry
            self.assertTrue(url.startswith("https://"), name)
            self.assertTrue(title.strip(), name)
            self.assertTrue(licence.strip(), f"{name} must state its licence")

    def test_nothing_to_pack_says_how_to_get_a_book(self):
        """The failure a newcomer hits first has to teach the flow."""
        import contextlib
        import io
        err = io.StringIO()
        empty = Path(tempfile.mkdtemp())
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = self.build_reader.main(["--notebooks", str(empty),
                                           "--out", str(empty / "x.pyz")])
        self.assertEqual(code, 1)
        said = err.getvalue()
        self.assertIn("--clone iar", said)
        self.assertIn("--book", said)


class Converting(unittest.TestCase):
    """tex2ink names a book from its own source, and says so on disk."""

    def setUp(self):
        from tools import tex2ink
        self.tex2ink = tex2ink
        self.src = Path(tempfile.mkdtemp())
        (self.src / "book.tex").write_text(
            "\\title{Principles of Fluid Mechanics}\n"
            "\\begin{document}\\input{one}\\end{document}\n")
        (self.src / "one.tex").write_text("\\chapter{Statics}\nPressure.\n")

    def test_a_book_is_named_by_its_own_title(self):
        self.assertEqual(self.tex2ink.book_title(self.src),
                         "Principles of Fluid Mechanics")

    def test_a_prefix_is_made_from_the_titles_initials(self):
        self.assertEqual(self.tex2ink.prefix_for(self.src), "PFM")

    def test_converting_writes_a_manifest_the_shelf_can_read(self):
        out = Path(tempfile.mkdtemp())
        self.tex2ink.convert(self.src, out)
        said = reader.read_manifest(out, "pfm")
        self.assertEqual(said["title"], "Principles of Fluid Mechanics")
        self.assertIn(str(self.src), said["source"])

    def test_a_title_with_no_latex_title_falls_back_to_the_folder(self):
        bare = Path(tempfile.mkdtemp()) / "some-book"
        bare.mkdir()
        self.assertEqual(self.tex2ink.book_title(bare), "some book")


if __name__ == "__main__":
    unittest.main()
