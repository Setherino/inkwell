# Changelog

Notable changes, newest first. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semver](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`tools/tex2hw.py`: one LaTeX document → one notebook.** A homework
  sheet is the shape `tex2ink.py` does not do — its own preamble, its own
  `\newcommand` macros, a `\maketitle` title block — so this reads the
  whole document, hands the body to tex2ink's converter, and writes a
  single notebook. The blank space a question leaves you to write in
  becomes `TODO solution`; the title block becomes the notebook's front
  matter. `\[...\]` is lifted out before the block scanner runs, so a
  display wrapped round `\begin{array}` stays one equation instead of
  coming apart around its own `\begin`.
- **The escape principle.** The interface is a tree, so it is written down as
  one (`SHELF`/`ROOT`/`COMPOSER`/`PAGE`/`EDITING` in `app.py`), and `esc` is
  one step up it from wherever you are:
  `[open box] → [page] → [box at the bottom] → [folder]`. `Inkwell.ascend`
  is the whole ladder in one place; no widget interprets `esc` any more.
  A modal now remembers the level it covered, so `esc` never lands you
  deeper than you left.
- **A shelf of books.** A book is a naming convention — two or more
  notebooks sharing a `<prefix>-<slot>-<title>.json` name — so a folder
  holds as many as you convert into it and they appear on a shelf with a
  filter. The shelf is the level above a book's contents, and `esc` walks
  back out through both. `f3` goes straight to it.
- `<prefix>.book.json` manifests: `tools/tex2ink.py` writes one from the
  source's own `\title{}`, so the shelf shows a book's real name.
- `tools/tex2ink.py` derives a prefix from a book's title
  (`prefix_for`) and takes `--title`.
- `tools/build_reader.py` packs any book, or a whole shelf: `--clone` takes
  a git URL, `--prefix` picks one book out of the folder, and `--out`/`--name`
  default from what is being packed.
- Reader CLI is shelf-aware: `inkwell-reader [book] [chapter]`, `--list` for
  the shelf or one book's contents, `--find` across every book.
- Packaging: `pyproject.toml` with `inkwell` and `inkwell-reader` entry
  points, and GitHub Actions running the suite on 3.9/3.13 × Linux/macOS
  plus the pty scenarios.
- `tools/drive.py --escape` and `--shelf`: real-pty walks of the escape
  ladder and of a two-book shelf.
- Docs: `LICENSE` (MIT), `CONTRIBUTING.md`, `docs/architecture.md`.

### Changed

- **The copy editor has no default endpoint.** It is off unless both
  `INKWELL_LLM_URL` and a key are set (`INKWELL_LLM_KEY`, or
  `~/.config/inkwell/key`). A notes app should not send anything anywhere
  until its owner has said where.
- `reasoning_effort` is opt-in (`INKWELL_LLM_EFFORT`) rather than always
  sent — only reasoning models know the field, and the rest reject it.
- `esc` in the page now reaches the box at the bottom, and clears a picked
  run on the way. Previously it did nothing there.
- `reader.contents()` takes an explicit prefix; there is no default book.
- The folder dialog and the contents menu keep `f2` as their own toggle but
  hand `esc` up to the app.

### Fixed

- Closing the folder dialog put the cursor in the *page* — deeper than the
  level it was opened from.
- `esc` in the page and in the box at the bottom were both no-ops, and the
  `esc` branch in `Inkwell._command` was unreachable, so a picked run of
  notes could not be cleared with the keyboard at all.
