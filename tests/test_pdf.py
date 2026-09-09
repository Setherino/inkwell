"""Exporting the page as a PDF."""

import re
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from . import helpers  # noqa: F401
from inkwell import pdf, store
from inkwell.app import Inkwell
from inkwell.sfnt import Face

MENLO = Path(pdf.FONT)


def out(name="page.pdf"):
    return Path(tempfile.mkdtemp()) / name


def notes(*texts):
    return [store.Note(t) for t in texts]


def streams(raw: bytes) -> str:
    """The drawing instructions, decompressed -- not the embedded fonts."""
    text = ""
    for match in re.finditer(rb"stream\n(.*?)\nendstream", raw, re.S):
        try:
            body = zlib.decompress(match.group(1))
        except zlib.error:
            continue
        if b" Tj" not in body:            # a font file, not a page
            continue
        text += body.decode("latin-1", "replace")
    return text


class FaceTests(unittest.TestCase):
    def setUp(self):
        self.face = Face(MENLO, 0)

    def test_it_reads_the_face_we_asked_for(self):
        self.assertEqual(Face(MENLO, 0).name, "Menlo-Regular")
        self.assertEqual(Face(MENLO, 1).name, "Menlo-Bold")
        self.assertEqual(Face(MENLO, 2).name, "Menlo-Italic")

    def test_it_maps_characters_to_glyphs(self):
        self.assertNotEqual(self.face.glyph("A"), 0)
        self.assertNotEqual(self.face.glyph("∑"), 0)
        self.assertEqual(self.face.glyph(""[0:1] * 1), self.face.glyph(""))

    def test_it_knows_what_it_cannot_draw(self):
        self.assertTrue(self.face.has("─"))
        self.assertFalse(self.face.has("🎉"))

    def test_widths_are_in_pdf_units_and_monospace(self):
        for character in "AWil.":
            self.assertEqual(self.face.width(self.face.glyph(character)), 602)

    def test_a_face_from_a_collection_becomes_its_own_font_file(self):
        solo = self.face.standalone()
        self.assertEqual(solo[:4], b"\x00\x01\x00\x00")
        self.assertGreater(len(solo), 100_000)
        again = Face.__new__(Face)          # parse what we just built
        again.data = solo
        again.index = 0
        again._tables = again._directory()
        again.units = again._units()
        self.assertEqual(again.units, self.face.units)
        self.assertEqual(again._cmap()["A".__hash__() and ord("A")],
                         self.face.glyph("A"))

    def test_block_characters_report_their_real_height(self):
        self.assertAlmostEqual(self.face.outline_height("█"), 1.0195, places=3)
        self.assertAlmostEqual(self.face.outline_height("▀"), 0.5098, places=3)


class FileTests(unittest.TestCase):
    def test_it_writes_a_pdf_a_reader_will_open(self):
        path = out()
        report = pdf.export(notes("# Title", "some prose here."), path)
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF-1.4"))
        self.assertTrue(raw.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/Type /Catalog", raw)
        self.assertIn(b"/Type /Pages", raw)
        self.assertEqual(report["pages"], 1)

    def test_the_cross_reference_table_points_at_the_objects(self):
        path = out()
        pdf.export(notes("a note."), path)
        raw = path.read_bytes()
        start = int(raw[raw.rfind(b"startxref"):].split()[1])
        self.assertEqual(raw[start:start + 4], b"xref")
        offsets = re.findall(rb"^(\d{10}) 00000 n $", raw[start:], re.M)
        self.assertTrue(offsets)
        for index, offset in enumerate(offsets, 1):
            at = int(offset)
            self.assertEqual(raw[at:at + len(str(index)) + 6],
                             f"{index} 0 obj".encode())

    def test_the_font_is_embedded_as_a_real_font_file(self):
        path = out()
        pdf.export(notes("some prose here."), path)
        raw = path.read_bytes()
        self.assertIn(b"/Subtype /Type0", raw)
        self.assertIn(b"/Encoding /Identity-H", raw)
        self.assertIn(b"/CIDToGIDMap /Identity", raw)
        self.assertIn(b"/FontFile2", raw)
        self.assertIn(b"/Length1", raw)

    def test_the_words_are_in_the_file_as_glyphs(self):
        path = out()
        pdf.export(notes("hello there."), path)
        face = Face(MENLO, 0)
        wanted = "".join(f"{face.glyph(c):04X}" for c in "hello")
        self.assertIn(wanted, streams(path.read_bytes()))

    def test_long_notebooks_run_to_several_pages(self):
        path = out()
        report = pdf.export(notes(*[f"note {i} on the page." for i in range(200)]),
                            path)
        self.assertGreater(report["pages"], 2)
        self.assertEqual(path.read_bytes().count(b"/Type /Page "), report["pages"])

    def test_an_empty_notebook_still_makes_a_file(self):
        path = out()
        report = pdf.export([], path)
        self.assertEqual(report["pages"], 1)
        self.assertTrue(path.exists())


class RenderTests(unittest.TestCase):
    def book(self, *texts, cols=92):
        return pdf.Book(notes(*texts), cols=cols)

    def test_look_alike_bold_becomes_the_real_bold_face(self):
        book = self.book("this has **bold** in it, and more words after.")
        faces = {run.style for line in book.sheets[0].lines for run in line.runs}
        self.assertIn("bold", faces)
        drawn = "".join(run.text for line in book.sheets[0].lines
                        for run in line.runs)
        self.assertIn("bold", drawn)           # plain letters, not look-alikes
        self.assertNotIn("𝗯", drawn)

    def test_look_alike_italic_becomes_the_italic_face(self):
        book = self.book("> a quotation of some length here.")
        faces = {run.style for line in book.sheets[0].lines for run in line.runs}
        self.assertIn("italic", faces)

    def test_small_caps_come_back_as_capitals(self):
        # ...on a real section, not the first note, which is the title.
        book = self.book("# The document", "## Thermals",
                         "prose under it, at some length.")
        drawn = "".join(run.text for line in book.sheets[0].lines
                        for run in line.runs)
        self.assertIn("THERMALS", drawn)

    def test_a_block_title_is_drawn_as_the_same_art(self):
        book = self.book("# Inkwell")
        art = [line for line in book.sheets[0].lines
               if line.runs and "█" in line.runs[0].text]
        self.assertTrue(art)
        # the rows stack with no gap, the way a terminal stacks them
        self.assertAlmostEqual(art[0].step, book.art_step, places=4)

    def test_the_art_block_is_centred_as_one_piece(self):
        book = self.book("# Inkwell")
        art = [line.runs[0] for line in book.sheets[0].lines
               if line.runs and "█" in line.runs[0].text]
        self.assertEqual(len({run.column for run in art}), 1)

    def test_a_title_the_face_cannot_draw_is_set_as_type_instead(self):
        # A long title falls to the sextant font on screen; Menlo has no
        # sextants, so the PDF sets it in bold with a rule under it.
        book = self.book("# HW0 - Prerequisites Check-in")
        drawn = "".join(run.text for line in book.sheets[0].lines
                        for run in line.runs)
        self.assertIn("HW0 - Prerequisites Check-in", drawn)
        self.assertIn("━", drawn)
        self.assertNotIn("🬂", drawn)
        self.assertEqual(book.undrawable, set())

    def test_art_the_face_can_draw_is_still_art(self):
        book = self.book("# Inkwell")
        drawn = "".join(run.text for line in book.sheets[0].lines
                        for run in line.runs)
        self.assertIn("█", drawn)
        self.assertNotIn("Inkwell", drawn)

    def test_maths_survives_the_trip(self):
        book = self.book("$$\\frac{n(n+1)}{2}$$")
        drawn = "".join(run.text for line in book.sheets[0].lines
                        for run in line.runs)
        self.assertIn("─", drawn)
        self.assertIn("n(n+1)", drawn)

    def test_colours_come_from_the_light_palette(self):
        book = self.book("!careful", "plain prose here, at some length.")
        colours = {run.colour for line in book.sheets[0].lines
                   for run in line.runs}
        self.assertGreater(len(colours), 1)
        for red, green, blue in colours:            # readable on white paper
            self.assertLess(min(red, green, blue), 0.8)

    def test_glyphs_no_face_can_draw_are_reported_not_left_as_boxes(self):
        path = out()
        report = pdf.export(notes("party time 🎉"), path)
        self.assertIn("🎉", report["undrawable"])
        face = Face(MENLO, 0)
        self.assertNotIn(f"{face.glyph('🎉'):04X}", streams(path.read_bytes()))

    def test_a_note_is_kept_whole_on_one_page_when_it_fits(self):
        long_note = "word " * 300
        book = pdf.Book(notes("filler.", long_note), cols=92)
        pages = [sheet for sheet in book.sheets
                 if any("word" in run.text for line in sheet.lines
                        for run in line.runs)]
        self.assertEqual(len(pages), 1)

    def test_the_page_number_is_on_every_page(self):
        path = out()
        report = pdf.export(notes(*[f"note {i}." for i in range(200)]), path)
        face = Face(MENLO, 0)
        text = streams(path.read_bytes())
        for number in range(1, report["pages"] + 1):
            wanted = "".join(f"{face.glyph(c):04X}" for c in str(number))
            self.assertIn(wanted, text)


class AppTests(unittest.TestCase):
    def test_the_app_exports_next_to_the_notebook(self):
        folder = Path(tempfile.mkdtemp())
        book = folder / "thermo-3.json"
        store.save(notes("# Thermo", "prose here."), book)
        app = Inkwell(book, use_llm=False)
        report = app.export_pdf()
        self.assertEqual(Path(report["path"]), folder / "thermo-3.pdf")
        self.assertTrue((folder / "thermo-3.pdf").exists())

    def test_ctrl_p_says_what_it_did(self):
        folder = Path(tempfile.mkdtemp())
        book = folder / "notes.json"
        store.save(notes("a note."), book)
        app = Inkwell(book, use_llm=False)
        app.frame.render((100, 20), True)
        app.unhandled("ctrl p")
        said = app.status.text
        self.assertIn("1 page", said)
        self.assertIn("notes.pdf", said)

    def test_the_message_clears_when_you_carry_on_typing(self):
        app = Inkwell(None, use_llm=False)
        app._said = "something"
        app.touch()
        self.assertEqual(app._said, "")

    def test_the_command_line_exports_and_stops(self):
        folder = Path(tempfile.mkdtemp())
        book = folder / "notes.json"
        store.save(notes("# Title", "prose."), book)
        result = subprocess.run(
            ["python3", "-m", "inkwell", "--no-llm", "--file", str(book),
             "--export", str(folder / "out.pdf")],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        self.assertIn("out.pdf", result.stdout)
        self.assertTrue((folder / "out.pdf").exists())


if __name__ == "__main__":
    unittest.main()
