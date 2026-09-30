# Changelog

Notable changes, newest first. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[semver](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **shift+enter files an open box, and ticks a checkbox in the page.** The
  same gesture for "I am done with this": in an open note it does what the
  `✓` button does, and on a checkbox it toggles it as space already did.
  Enter stays a line break, because a note is prose first and a cell second.
- Shift+enter is not a key a terminal sends by default -- the usual answer
  to it is a bare CR, which is what Enter sends, so nothing can tell the two
  apart. The terminals that *can* say it use `CSI 13;2u` (kitty, WezTerm,
  ghostty, newer iTerm2) or `CSI 27;2;13~` (xterm modifyOtherKeys), and
  urwid 4 decodes neither, so `app.teach_shift_enter` registers both. It has
  to register them on *every* trie it can reach: urwid hands out two
  different module objects for the single `urwid.display.escape` entry in
  `sys.modules`, and the `process_keyqueue` you get by importing it is not
  the one the screen's parser calls. Teaching only the imported one passes a
  unit test and does nothing in a real terminal -- `tools/drive.py
  --shift-enter` is what caught that, by sending the raw bytes down a pty.
- `shift enter` was already named in the editing keymap as an alias for the
  line break. It had never once fired, because nothing decoded it.

### Fixed

- **Arrowing out of a box scrolled the whole page.** Walking off the end of
  an open note steps to the note above or below; `change_focus()` takes the
  row to put that note at and defaults to 0, so the one you landed on was
  pinned to the top of the body and the document slid under you. Stepping
  one note up could move the page five rows. It now lands where the note
  already sits, and only scrolls when the note really is off screen --
  the rule `to_notes` was already following, which `step` never got.

- **An equation broken across two source lines was demoted to prose**, and
  prose sets its math inline -- one line, small -- so every stacked fraction
  in it came out as `r/2`. A math span is delimited, not line-based: LaTeX
  does not care where a newline falls between its `$` signs. A note that is
  nothing but one formula now stays math however the source wrapped it, and
  stacks whenever the page is wide enough. A homework sheet writes exactly
  that shape, which is where this was found.

### Changed

- **A script sits beside its base unless the base takes limits.** Display used
  to park a script it could not shrink -- a capital has no unicode subscript --
  on a row of its own. That reads well alone and badly in company: the row
  above a fraction holds the numerators and the row below holds the
  denominators, so `\frac{r\dot\phi_L}{2}` left a lone `L` over the rule and
  `ẋ_R` dropped its `R` onto the denominators' line. Scripts now attach beside
  the base in display exactly as they do inline, and `\sum`, `\int`, the
  `\lim`-like words and an already-tall base still take their limits over and
  under. A fraction's two halves are also read one level deeper now, the way a
  script's argument already was: the fraction owns the vertical.
- **The one-line fraction is set tiny only when both halves are plain
  digits** (`¹∕₇`, `³∕₁₆`). 0-9 is the one super/subscript range unicode
  draws completely and evenly, so it reads like the precomposed `½` beside
  it; the letter forms are patchy and small enough to misread, which is how
  `\frac{r}{2}` came out `ʳ∕₂` and `\frac{a+b}{2}` came out `ᵃ⁺ᵇ∕₂`. Those
  are now `r/2` and `(a+b)/2`, bracketed on whichever side could be misread.
  The test is explicitly ASCII: `str.isdigit()` is also true of `²` and `٣`,
  and shrinking something already tiny is the bug.

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
