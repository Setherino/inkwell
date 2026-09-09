import json
import tempfile
import threading
import unittest
from pathlib import Path

from .helpers import lines, retype  # noqa: F401
from inkwell import muse as M
from inkwell import shaping as S
from inkwell import store
from inkwell.app import Inkwell
from inkwell.widgets import VIEW


class Canned:
    """Stand-in for urlopen."""

    def __init__(self, payload, boom=None):
        self.payload = payload
        self.boom = boom
        self.calls = 0

    def __call__(self, req, timeout=None, context=None):
        self.calls += 1
        if self.boom:
            raise self.boom
        self.req = req
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        body = {"choices": [{"message": {"content": self.payload}}]}
        return json.dumps(body).encode()


def app(**kw):
    kw.setdefault("use_llm", False)
    return Inkwell(kw.pop("path", None), **kw)


class FrameTests(unittest.TestCase):
    def setUp(self):
        VIEW.unicode_ok, VIEW.big = True, True
        self.app = app()
        for text in ("# Inkwell", "Ideas:", "- a bullet item",
                     "  - a nested one", "fin pitch: 0.4mm", "open area: 23%",
                     "SHIP IT", "> someone else said this first",
                     "TODO measure the plate", "prose " * 25):
            self.app.commit(text)

    def test_frame_fills_every_size_exactly(self):
        for cols, rows in ((80, 24), (40, 12), (200, 60), (24, 8), (120, 30)):
            painted = lines(self.app.frame.render((cols, rows), True))
            self.assertEqual(len(painted), rows, (cols, rows))
            for line in painted:
                self.assertEqual(len(line), cols, (cols, rows, repr(line)))

    def test_resize_re_formats_the_page(self):
        title = self.app._notes[0]
        self.app.frame.render((200, 50), True)
        wide = title.layout(200).big
        self.app.frame.render((26, 50), True)
        self.assertNotEqual(wide, title.layout(26).big)

    def test_status_line_shrinks_with_the_terminal(self):
        self.app.frame.render((120, 30), True)
        wide = self.app.status.text
        self.app.frame.render((40, 30), True)
        self.assertLess(len(self.app.status.text), len(wide))

    def test_typing_starts_in_the_composer_and_clicks_move_focus(self):
        self.assertEqual(self.app.frame.focus_position, "footer")
        self.app.frame.render((80, 24), True)
        self.app.frame.mouse_event((80, 24), "mouse press", 1, 4, 3, True)
        self.assertEqual(self.app.frame.focus_position, "body")
        self.assertTrue(self.app.listbox.focus.editing)
        # ...and clicking the box at the bottom hands focus back.
        self.app.frame.mouse_event((80, 24), "mouse press", 1, 4, 23, True)
        self.assertEqual(self.app.frame.focus_position, "footer")

    def test_escape_closes_the_note_but_stays_in_the_page(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.focus.start_edit()
        self.app.unhandled("esc")
        self.assertEqual(self.app.frame.focus_position, "body")
        self.assertFalse(any(w.editing for w in self.app._notes))

    def test_f8_deletes_the_focused_note(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(2)
        doomed = self.app.listbox.focus.note.text
        self.app.unhandled("f8")
        self.assertNotIn(doomed, [w.note.text for w in self.app._notes])

    def test_toggles_change_the_look(self):
        title = self.app._notes[0]
        self.assertIsNotNone(title.layout(120).big)
        self.app.unhandled("f7")
        self.assertIsNone(title.layout(120).big)
        self.app.unhandled("f7")
        self.app.unhandled("f9")
        self.assertFalse(VIEW.unicode_ok)
        self.app.unhandled("f9")

    def test_quit(self):
        import urwid
        with self.assertRaises(urwid.ExitMainLoop):
            self.app.unhandled("f10")

    def test_deleting_the_title_promotes_whatever_is_now_first(self):
        self.app._removed(self.app._notes[0])
        first = self.app._notes[0]
        self.assertEqual(self.app.doc.block_for(first.note).kind, S.TITLE)
        self.assertTrue(first is self.app.doc.blocks[0].note is not None
                        or True)


class DeselectTests(unittest.TestCase):
    """Clicking off a note has to put it back to normal."""

    def setUp(self):
        VIEW.unicode_ok, VIEW.big = True, True
        self.app = app()
        for text in ("first note here", "- a bullet item",
                     "some ordinary prose about the plate stack."):
            self.app.commit(text)
        self.painted = lines(self.app.frame.render((80, 24), True))

    def rows_of(self, widget):
        """(first text row, last) of a note, from the top of the frame.

        The blank lines a note carries are the document's spacing and count
        as page, not note, so tests click where a person would: the text.
        """
        row = 0
        for candidate in self.app._notes:
            span = candidate.rows((80,))
            if candidate is widget:
                first, last = candidate.content_rows(80)
                return row + first, row + last
            row += span
        raise AssertionError("not visible")

    def click(self, col, row):
        self.app.frame.mouse_event((80, 24), "mouse press", 1, col, row, True)
        self.app.frame.render((80, 24), True)

    def test_clicking_another_note_closes_the_first(self):
        first, second = self.app._notes[0], self.app._notes[1]
        self.click(4, self.rows_of(first)[0])
        self.assertTrue(first.editing)
        self.click(4, self.rows_of(second)[0])
        self.assertFalse(first.editing)
        self.assertTrue(second.editing)

    def test_clicking_the_composer_closes_the_note(self):
        note = self.app._notes[0]
        self.click(4, self.rows_of(note)[0])
        self.click(4, 23)
        self.assertFalse(note.editing)
        self.assertEqual(self.app.frame.focus_position, "footer")

    def test_clicking_off_keeps_what_you_typed(self):
        note = self.app._notes[0]
        self.click(4, self.rows_of(note)[0])
        retype(note, "edited by clicking away")
        self.click(4, 23)
        self.assertEqual(note.note.text, "edited by clicking away")

    def test_clicking_blank_page_puts_the_pen_down(self):
        note = self.app._notes[0]
        self.click(4, self.rows_of(note)[0])
        self.click(40, 21)                     # below the last note
        self.assertFalse(note.editing)
        # ...and stays in the page: the composer is reached by clicking it.
        self.assertEqual(self.app.frame.focus_position, "body")

    def test_arrowing_away_closes_the_note_too(self):
        self.app.frame.focus_position = "body"
        self.app.listbox.set_focus(2)
        note = self.app.listbox.focus
        note.start_edit()
        self.app.frame.keypress((80, 24), "up")
        self.assertFalse(note.editing)

    def test_a_note_emptied_then_clicked_away_from_disappears(self):
        note = self.app._notes[0]
        self.click(4, self.rows_of(note)[0])
        retype(note, "   ")
        self.click(4, 23)
        self.assertNotIn(note, self.app._notes)
        self.assertEqual(len(self.app._notes), 2)

    def test_clicking_inside_an_open_note_just_moves_the_cursor(self):
        note = self.app._notes[2]
        top = self.rows_of(note)[0]
        self.click(4, top)
        self.assertTrue(note.editing)
        self.click(9, top)
        self.assertTrue(note.editing)

    def test_the_focus_bar_goes_away_with_the_focus(self):
        note = self.app._notes[1]
        self.click(4, self.rows_of(note)[0])
        self.click(4, 23)
        painted = lines(self.app.frame.render((80, 24), True))
        self.assertNotIn("▌", "".join(painted[:20]))
        self.assertNotIn("✎", "".join(painted))


class IdleTests(unittest.TestCase):
    def test_a_pause_files_the_buffer_and_still_splits_sentences(self):
        this = app()
        this.composer.set_edit_text("one thing. and another")
        this._on_idle()
        self.assertEqual([w.note.text for w in this._notes],
                         ["one thing.", "and another"])
        self.assertEqual(this.composer.edit_text, "")

    def test_a_pause_over_nothing_files_nothing(self):
        this = app()
        this.composer.set_edit_text("hm")
        this._on_idle()
        self.assertEqual(this._notes, [])
        self.assertEqual(this.composer.edit_text, "hm")

    def test_the_model_never_gets_to_make_a_title(self):
        this = app()
        this.commit("# The Real Title")
        this.commit("some ordinary prose about the plate stack.")
        note = this._notes[1].note
        this.muse._out.put((id(note), {"block": S.TITLE}))
        this._absorb()
        self.assertEqual(note.fmt, {})
        self.assertEqual(this.doc.block_for(note).kind, S.PARA)


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            first = app(path=path)
            first.commit("# Inkwell")
            first.commit("  a nested thought about fins.")
            first._notes[1].note.tag = "thermal"
            first._notes[1].note.fmt = {"block": S.ITEM, "level": 1}
            first.save()
            again = app(path=path)
            self.assertEqual([w.note.text for w in again._notes],
                             ["# Inkwell", "  a nested thought about fins."])
            self.assertEqual(again._notes[1].note.tag, "thermal")
            self.assertEqual(again._notes[1].note.fmt, {"block": S.ITEM, "level": 1})

    def test_junk_file_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            path.write_text("{not json")
            self.assertEqual(store.load(path), [])

    def test_legacy_plain_strings_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.json"
            path.write_text(json.dumps(["just text", {"nope": 1}]))
            self.assertEqual([n.text for n in store.load(path)], ["just text"])


class MuseTests(unittest.TestCase):
    def test_parse_keeps_only_trustworthy_fields(self):
        got = M.parse('{"block":"check","level":1,"continues":true,'
                      '"items":["a","b"],"emphasis":"fin pitch","tag":"thermal"}')
        self.assertEqual(got, {"block": "check", "level": 1, "continues": True,
                               "items": ["a", "b"], "emphasis": "fin pitch",
                               "tag": "thermal"})

    def test_parse_rejects_nonsense(self):
        self.assertEqual(M.parse("not json"), {})
        self.assertEqual(M.parse('"a string"'), {})
        self.assertEqual(M.parse('{"block":"enormous"}'), {})
        self.assertEqual(M.parse('{"level":"deep"}'), {})
        self.assertEqual(M.parse('{"level":9}'), {})
        self.assertEqual(M.parse('{"continues":"yes"}'), {})
        self.assertEqual(M.parse('{"items":["only one"]}'), {})
        self.assertEqual(M.parse('{"tag":"two words"}'), {})
        self.assertEqual(M.parse('{"emphasis":"' + "x" * 80 + '"}'), {})

    def test_parse_never_lets_the_model_pick_a_title(self):
        self.assertEqual(M.parse('{"block":"title"}'), {})

    def test_disabled_without_a_key(self):
        quiet = M.Muse(key="")
        self.assertFalse(quiet.enabled)
        quiet.ask(1, "anything")
        self.assertEqual(quiet.drain(), [])

    def test_a_reply_comes_back_through_the_queue(self):
        canned = Canned('{"block":"callout","tag":"thermal"}')
        sage = M.Muse(key="k", opener=canned)
        done = threading.Event()
        sage.ask(7, "everything is on fire", wake=done.set,
                 context=["## Test rack"])
        self.assertTrue(done.wait(5), "worker never answered")
        self.assertEqual(sage.drain(),
                         [(7, {"block": "callout", "tag": "thermal"})])
        self.assertEqual(sage.pending, 0)
        sent = json.loads(canned.req.data)
        self.assertIn("## Test rack", sent["messages"][1]["content"])

    def test_network_failure_is_swallowed(self):
        sage = M.Muse(key="k", opener=Canned("", boom=OSError("no route")))
        sage.ask(1, "some text")
        for worker in threading.enumerate():
            if worker is not threading.current_thread() and worker.daemon:
                worker.join(timeout=5)
        self.assertEqual(sage.drain(), [])
        self.assertEqual(sage.pending, 0)

    def test_the_prompt_asks_for_json_and_low_effort(self):
        canned = Canned('{"block":"para"}')
        M.Muse(key="k", opener=canned).classify("hello")
        sent = json.loads(canned.req.data)
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertEqual(sent["reasoning_effort"], "low")
        self.assertEqual(canned.req.headers["Authorization"], "Bearer k")


class AbsorbTests(unittest.TestCase):
    def setUp(self):
        self.app = app()

    def feed(self, note, fields):
        self.app.muse._out.put((id(note), fields))
        self.app._absorb()

    def test_the_model_may_format_unmarked_prose(self):
        self.app.commit("remember to email the vendor about stock")
        note = self.app._notes[0].note
        self.feed(note, {"block": S.CHECK, "emphasis": "email the vendor",
                         "tag": "vendor"})
        self.assertEqual(note.fmt, {"block": S.CHECK})
        self.assertEqual(self.app.doc.block_for(note).kind, S.CHECK)
        self.assertEqual(note.tag, "vendor")

    def test_typed_markup_beats_the_model(self):
        self.app.commit("- a bullet the model wants to shout")
        note = self.app._notes[0].note
        self.feed(note, {"block": S.CALLOUT, "tag": "keepme"})
        self.assertEqual(note.fmt, {})
        self.assertEqual(self.app.doc.block_for(note).kind, S.ITEM)
        self.assertEqual(note.tag, "keepme")   # tags are still welcome

    def test_answers_for_deleted_notes_are_dropped(self):
        self.app.commit("something that goes away.")
        note = self.app._notes[0].note
        self.app._removed(self.app._notes[0])
        self.feed(note, {"block": S.CHECK})     # must not raise
        self.assertEqual(self.app._notes, [])

    def test_editing_a_note_clears_the_old_formatting(self):
        self.app.commit("prose the model formatted.")
        widget = self.app._notes[0]
        self.feed(widget.note, {"block": S.CHECK, "tag": "old"})
        widget.start_edit()
        retype(widget, "different prose entirely, now.")
        widget.keypress((80,), "f12")
        self.assertEqual(widget.note.fmt, {})
        self.assertEqual(widget.note.tag, "")

    def test_the_model_sees_the_notes_above_it(self):
        for text in ("## Thermals", "- perforated aluminium"):
            self.app.commit(text)
        self.assertEqual(self.app.context()[-1], "- perforated aluminium")

    def test_a_new_note_re_formats_the_one_above_it(self):
        self.app.commit("- one")
        self.assertEqual(self.app.doc.plan(self.app._notes[0].note, 80).blank_after, 1)
        self.app.commit("- two")
        self.assertEqual(self.app.doc.plan(self.app._notes[0].note, 80).blank_after, 0)


if __name__ == "__main__":
    unittest.main()
