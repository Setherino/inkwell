"""The notebooks folder, and the open dialog that lists it."""

import tempfile
import time
import unittest
from pathlib import Path

import urwid

from .helpers import lines  # noqa: F401
from inkwell import store
from inkwell.app import Inkwell
from inkwell.widgets import Library


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, name, *texts, age=0):
        path = self.tmp / name
        store.save([store.Note(t) for t in texts], path)
        if age:
            stamp = time.time() - age
            import os
            os.utime(path, (stamp, stamp))
        return path

    def test_it_lists_only_notebooks(self):
        self.write("one.json", "a")
        (self.tmp / "notes.txt").write_text("not a notebook")
        (self.tmp / "sub").mkdir()
        self.assertEqual([p.name for p in store.notebooks(self.tmp)],
                         ["one.json"])

    def test_the_most_recently_written_comes_first(self):
        self.write("old.json", "a", age=10_000)
        self.write("new.json", "b")
        self.assertEqual([p.stem for p in store.notebooks(self.tmp)],
                         ["new", "old"])

    def test_migration_only_touches_the_real_notes_home(self):
        other = self.tmp / "elsewhere"
        store.ensure(other)
        self.assertEqual(store.notebooks(other), [])

    def test_a_missing_folder_is_not_an_error(self):
        self.assertEqual(store.notebooks(self.tmp / "nope"), [])

    def test_names_become_safe_filenames(self):
        self.assertEqual(store.slug("Thermo 3 — Entropy!"), "thermo-3-entropy")
        self.assertEqual(store.slug("../../etc/passwd"), "etcpasswd")
        self.assertEqual(store.slug("   "), "untitled")
        self.assertEqual(store.path_for("HW 0", self.tmp).name, "hw-0.json")

    def test_titles_are_readable_again(self):
        self.assertEqual(store.title_of(self.tmp / "thermo-3.json"), "thermo 3")

    def test_ensure_only_makes_the_folder(self):
        """It must never import a notebook from anywhere else.

        A second copy of a notebook is how you end up editing the wrong one
        and losing work, so there is deliberately no migration.
        """
        landing = self.tmp / "Inkwell"
        elsewhere = self.tmp / "somewhere-else"
        elsewhere.mkdir()
        store.save([store.Note("not mine")], elsewhere / "notes.json")
        store.ensure(landing)
        self.assertTrue(landing.is_dir())
        self.assertEqual(store.notebooks(landing), [])


class SaveTests(unittest.TestCase):
    """Two sessions must not silently overwrite each other."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "HW0.json"
        store.save([store.Note("# HW0"), store.Note("2. the important one")],
                   self.path)
        self.app = Inkwell(self.path, use_llm=False)

    def written(self, path=None):
        return [n.text for n in store.load(path or self.path)]

    def test_ordinary_saving_writes_the_notebook(self):
        self.app.commit("a new thought.")
        self.assertIn("a new thought.", self.written())

    def test_a_file_changed_by_someone_else_is_not_overwritten(self):
        # another session (or an old window) writes the file
        import os
        store.save([store.Note("# HW0"), store.Note("2. the important one"),
                    store.Note("typed in the other window")], self.path)
        os.utime(self.path, (time.time() + 5, time.time() + 5))
        self.app.commit("typed in this window.")
        self.assertIn("typed in the other window", self.written())
        spare = [p for p in self.tmp.iterdir() if "conflict" in p.name]
        self.assertEqual(len(spare), 1, list(self.tmp.iterdir()))
        self.assertIn("typed in this window.", self.written(spare[0]))

    def test_it_says_what_it_did(self):
        import os
        store.save([store.Note("elsewhere")], self.path)
        os.utime(self.path, (time.time() + 5, time.time() + 5))
        self.app.commit("mine.")
        self.assertIn("changed underneath", self.app._said)

    def test_our_own_writes_do_not_look_like_a_conflict(self):
        for text in ("one.", "two.", "three."):
            self.app.commit(text)
        self.assertEqual(list(self.tmp.glob("*conflict*")), [])
        self.assertEqual(len(self.written()), 5)


class DialogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        store.save([store.Note("# Thermo"), store.Note("prose here.")],
                   self.tmp / "thermo-3.json")
        store.save([store.Note("# HW0")], self.tmp / "hw0.json")
        self.dialog = Library(self.tmp, self.tmp / "thermo-3.json")
        self.chosen, self.closed = [], []
        urwid.connect_signal(self.dialog, "chosen",
                             lambda _w, path: self.chosen.append(path))
        urwid.connect_signal(self.dialog, "closed",
                             lambda _w: self.closed.append(True))

    def painted(self):
        return "\n".join(lines(self.dialog.render((54,), True)))

    def test_it_shows_every_notebook_with_its_size_and_time(self):
        page = self.painted()
        self.assertIn("thermo 3", page)
        self.assertIn("hw0", page)
        self.assertIn("2 notes", page)
        self.assertIn("1 note", page)

    def test_the_open_notebook_is_marked(self):
        self.assertIn("▸ thermo 3", self.painted())

    def test_enter_opens_the_highlighted_notebook(self):
        self.dialog.keypress((54,), "enter")
        self.assertEqual(self.chosen, [self.tmp / "thermo-3.json"])

    def test_it_opens_on_the_notebook_you_are_in(self):
        self.assertEqual(self.dialog.selected().name, "thermo-3.json")

    def test_arrows_move_the_highlight(self):
        self.dialog.keypress((54,), "up")
        self.assertEqual(self.dialog.selected().name, "hw0.json")

    def test_a_typed_name_starts_a_new_notebook(self):
        self.dialog.body.focus_position = 2
        self.dialog.naming.set_edit_text("Lecture 4")
        self.dialog.keypress((54,), "enter")
        self.assertEqual(self.chosen, [self.tmp / "lecture-4.json"])

    def test_escape_closes_it(self):
        self.dialog.keypress((54,), "esc")
        self.assertEqual(self.closed, [True])

    def test_clicking_a_notebook_opens_it(self):
        self.dialog.render((54,), True)
        self.dialog.mouse_event((54,), "mouse press", 1, 6, 2, True)
        self.assertTrue(self.chosen)

    def test_an_empty_folder_still_offers_a_way_in(self):
        empty = Library(self.tmp / "nothing-here")
        self.assertIn("no notebooks yet", "\n".join(lines(empty.render((54,), True))))


class SwitchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        store.save([store.Note("# Thermo")], self.tmp / "thermo-3.json")
        store.save([store.Note("# HW0"), store.Note("- due tonight")],
                   self.tmp / "hw0.json")
        self.app = Inkwell(self.tmp / "thermo-3.json", use_llm=False)

    def test_f2_opens_and_closes_the_dialog(self):
        self.app.unhandled("f2")
        self.assertIsNotNone(self.app.library)
        self.app.unhandled("f2")
        self.assertIsNone(self.app.library)

    def test_opening_another_notebook_replaces_the_page(self):
        self.app.load_notebook(self.tmp / "hw0.json")
        self.assertEqual([w.note.text for w in self.app._notes],
                         ["# HW0", "- due tonight"])
        self.assertEqual(len(self.app.walker), 2)

    def test_the_notebook_you_leave_is_saved_first(self):
        self.app.commit("something typed just now.")
        self.app.load_notebook(self.tmp / "hw0.json")
        self.assertIn("something typed just now.",
                      [n.text for n in store.load(self.tmp / "thermo-3.json")])

    def test_the_new_notebook_is_formatted_from_scratch(self):
        self.app.load_notebook(self.tmp / "hw0.json")
        kinds = [b.kind for b in self.app.doc.blocks]
        self.assertEqual(kinds[0], "title")
        self.assertEqual(kinds[1], "item")

    def test_a_notebook_that_does_not_exist_yet_opens_empty(self):
        self.app.load_notebook(self.tmp / "brand-new.json")
        self.assertEqual(self.app._notes, [])
        self.app.commit("first note in it.")
        self.assertTrue((self.tmp / "brand-new.json").exists())

    def test_the_status_line_says_which_notebook_is_open(self):
        self.app.frame.render((92, 20), True)
        self.assertIn("thermo 3", self.app.status.text)
        self.app.load_notebook(self.tmp / "hw0.json")
        self.app.frame.render((92, 20), True)
        self.assertIn("hw0", self.app.status.text)

    def test_f5_swaps_the_theme(self):
        self.assertEqual(self.app.theme, "dark")
        self.app.unhandled("f5")
        self.assertEqual(self.app.theme, "light")
        self.app.frame.render((92, 20), True)
        self.assertIn("f5 dark", self.app.status.text)


if __name__ == "__main__":
    unittest.main()
