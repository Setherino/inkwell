"""Undo: the page as it was, all the way back."""

import unittest

from .helpers import retype  # noqa: F401
from inkwell import store
from inkwell.app import Inkwell
from inkwell.history import LIMIT, History, freeze, thaw


def notes(*texts):
    return [store.Note(t) for t in texts]


class SnapshotTests(unittest.TestCase):
    def test_a_note_survives_being_frozen_and_thawed(self):
        note = store.Note("a note", tag="thermal", emphasis="a", done=True,
                          fmt={"block": "check", "items": ["one", "two"]})
        back = thaw(freeze(note))
        for field in ("text", "tag", "emphasis", "done", "fmt", "created"):
            self.assertEqual(getattr(back, field), getattr(note, field), field)

    def test_thawing_gives_you_a_separate_note(self):
        note = store.Note("a note")
        back = thaw(freeze(note))
        back.text = "changed"
        self.assertEqual(note.text, "a note")

    def test_identical_pages_are_not_recorded_twice(self):
        page = notes("one", "two")
        history = History()
        self.assertTrue(history.record(page))
        self.assertFalse(history.record(page))
        self.assertEqual(history.depth, 0)

    def test_unchanged_notes_are_shared_between_steps(self):
        page = notes(*[f"note {i}" for i in range(20)])
        history = History()
        history.record(page)
        for step in range(50):
            page[0].text = f"edited {step}"
            history.record(page)
        # 20 originals + 50 versions of the first note, not 20 x 51 copies.
        self.assertEqual(len(history._known), 20 + 50)
        for snapshot in history._past:
            self.assertIs(snapshot[5], history._past[0][5])

    def test_the_limit_is_a_million(self):
        self.assertEqual(LIMIT, 1_000_000)

    def test_the_oldest_steps_fall_off_the_end(self):
        history = History(limit=3)
        page = notes("x")
        for step in range(10):
            page[0].text = f"step {step}"
            history.record(page)
        self.assertEqual(history.depth, 3)
        for _ in range(3):
            history.undo()
        self.assertFalse(history.can_undo)


class WalkTests(unittest.TestCase):
    def setUp(self):
        self.history = History()
        self.page = notes("one")
        self.history.record(self.page)
        for text in ("two", "three"):
            self.page.append(store.Note(text))
            self.history.record(self.page)

    def test_undo_gives_the_previous_page(self):
        self.assertEqual([n.text for n in self.history.undo()], ["one", "two"])
        self.assertEqual([n.text for n in self.history.undo()], ["one"])

    def test_undo_stops_at_the_beginning(self):
        self.history.undo()
        self.history.undo()
        self.assertIsNone(self.history.undo())

    def test_redo_walks_back_up(self):
        self.history.undo()
        self.history.undo()
        self.assertEqual([n.text for n in self.history.redo()], ["one", "two"])
        self.assertEqual([n.text for n in self.history.redo()],
                         ["one", "two", "three"])

    def test_redo_stops_at_the_present(self):
        self.assertIsNone(self.history.redo())

    def test_a_new_change_after_undoing_forgets_the_redo(self):
        self.history.undo()
        self.page = notes("one", "different")
        self.history.record(self.page)
        self.assertFalse(self.history.can_redo)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.app = Inkwell(None, use_llm=False)
        self.app.frame.render((80, 24), True)
        for text in ("# Notes", "1. first item", "2. second item"):
            self.app.commit(text)

    def texts(self):
        return [w.note.text for w in self.app._notes]

    def focus(self, index):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(index)

    def test_undo_puts_back_a_deleted_note(self):
        self.focus(2)
        self.app.unhandled("f8")
        self.assertEqual(len(self.texts()), 2)
        self.app.unhandled("ctrl z")
        self.assertEqual(self.texts(),
                         ["# Notes", "1. first item", "2. second item"])

    def test_undo_puts_back_an_edit(self):
        widget = self.app._notes[1]
        widget.start_edit()
        retype(widget, "1. something else")
        widget.keypress((80,), "f12")
        self.app.unhandled("ctrl z")
        self.assertEqual(self.texts()[1], "1. first item")

    def test_breaking_a_note_in_two_is_one_step_to_undo(self):
        widget = self.app._notes[2]
        widget.start_edit()
        for key in ("enter", "enter"):
            widget.keypress((80,), key)
        for character in "and a third":
            widget.keypress((80,), character)
        widget.keypress((80,), "f12")
        self.assertEqual(len(self.texts()), 4)
        self.app.unhandled("ctrl z")
        self.assertEqual(len(self.texts()), 3)
        self.assertEqual(self.texts()[2], "2. second item")

    def test_undo_takes_back_a_committed_note(self):
        self.app.commit("one more thought.")
        self.app.unhandled("ctrl z")
        self.assertNotIn("one more thought.", self.texts())

    def test_redo_puts_it_back_again(self):
        self.focus(1)
        self.app.unhandled("f8")
        self.app.unhandled("ctrl z")
        self.app.unhandled("ctrl r")
        self.assertEqual(self.texts(), ["# Notes", "2. second item"])

    def test_undo_walks_all_the_way_to_an_empty_page(self):
        for _ in range(20):
            self.app.unhandled("ctrl z")
        self.assertEqual(self.texts(), [])

    def test_the_page_is_re_formatted_after_undo(self):
        self.focus(1)
        self.app.unhandled("f8")                 # drop "1. first item"
        self.app.unhandled("ctrl z")
        marks = ["".join(t for _a, t in self.app.doc.plan(w.note, 80).rows[0])
                 .strip()[:2] for w in self.app._notes[1:]]
        self.assertEqual(marks, ["1.", "2."])

    def test_undo_is_written_to_disk(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            app = Inkwell(path, use_llm=False)
            app.frame.render((80, 24), True)
            app.commit("first note.")
            app.commit("second note.")
            app.unhandled("ctrl z")
            self.assertEqual([n.text for n in store.load(path)], ["first note."])

    def test_every_notebook_has_its_own_past(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "other.json"
            store.save([store.Note("elsewhere")], other)
            self.app.load_notebook(other)
            self.assertFalse(self.app.history.can_undo)
            self.app.unhandled("ctrl z")
            self.assertEqual(self.texts(), ["elsewhere"])

    def test_the_undo_keys(self):
        for key in ("ctrl z", "ctrl _", "f11"):
            self.app.commit("a note to take back.")
            self.app.unhandled(key)
            self.assertNotIn("a note to take back.", self.texts(), key)


if __name__ == "__main__":
    unittest.main()
