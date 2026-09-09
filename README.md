# inkwell

A terminal notebook that formats itself. You type into the box at the
bottom; when a thought ends it drops into the page above and is laid out as
part of a document — nested lists, aligned columns, definitions, tables,
side-by-side panes, typeset maths. Resize the window and the whole page
re-lays: nothing about a note's appearance is stored.

    inkwell                     # opens the newest notebook in ~/Documents/Inkwell
    inkwell HW0                 # ...or a notebook by name (exact names keep their case)
    inkwell --theme light       # light | dark | auto (the default: ask the terminal)
    inkwell hw0 --export hw0.pdf --width 92     # print it and stop
    inkwell --no-save           # scratch session
    inkwell --no-llm            # markup only, no network
    inkwell --ascii             # no unicode letterforms

`bin/inkwell` runs from the checkout and follows symlinks, so it works from
anywhere on `$PATH`:

    ln -s "$PWD/bin/inkwell" ~/.local/bin/inkwell

## Notebooks

Notes live in **`~/Documents/Inkwell`** — one JSON file per notebook,
somewhere you would actually look for them. `f2` opens the folder:

    ┌────────────── ~/Documents/Inkwell ───────────────┐
    │   notes                       9 notes    21:24   │
    │   hw0                         3 notes    21:24   │
    │ ▸ thermo 3                    3 notes    21:24   │
    │ ──────────────────────────────────────────────── │
    │   new: lecture 4                                 │
    └──────────────────────────────────────────────────┘

Arrows and Enter to open one (or click it); type a name in **new:** to start
one. The dialog opens on the notebook you are in, `▸` marks it, and whatever
you had open is saved before the swap.

Nothing is ever imported from another folder, and a notebook is never
written over blind: if the file changed on disk since this session read it
— an old window left open somewhere — the save goes to
`<notebook>-conflict-HHMMSS.json` beside it and the status line says so.
Two copies of the same notes is how you end up editing the wrong one.

## Light and dark

Two palettes, chosen at startup from `$INKWELL_THEME`, then `$COLORFGBG`,
then an OSC 11 query asking the terminal what colour it is — and `f5` flips
between them live. They are built to measured contrast rather than by eye:
`inkwell/theme.py` carries the WCAG maths, and the tests assert that body
text clears 7:1 against its background in both themes and that even the
quiet things (rules, timestamps, dot leaders) clear 3:1.

## How it decides you're done

- a sentence terminator followed by a space files the sentence
- Enter files whatever is in the box (splitting it into sentences)
- three seconds of quiet files it too

Abbreviations (`e.g.`, `Dr.`), initials (`Seth J.`), trailing `...`,
decimals (`0.4mm`), versions (`v1.2`) and list numbers (`3. `) are not
sentence endings, so you can type through them.

## The kinds of box

Every note is an editable text box; what *kind* of box it is comes from its
own first characters (and two leading spaces per level nests it).

| what you type | what you get |
| --- | --- |
| `# Thermo 3` | the document title, set large |
| `## The second law` | a section: small caps and a rule across the page |
| `### details` or `Open questions:` | a heading |
| plain prose | a paragraph, wrapped in a 78-column measure |
| `is entropy extensive?` | an open question, kept in a `?` gutter |
| `- item` / `* item` / `1. item` / `(a) item` | list items; runs pack tight and count on from the number you typed, past their own sub-items |
| `TODO x` / `- [ ] x` / `- [x] x` | a checkbox; space toggles it |
| `fin pitch: 0.4mm` | a pair — key column, dot leaders, value column |
| `entropy :: what it means` | a definition: bold term, em dash, hanging indent |
| `engine \| T_h \| efficiency` | a table row; the run shares its columns |
| `> borrowed words` | a quotation |
| `` `some/path.py` `` | verbatim — spacing kept, never re-wrapped; a run of lines is one block |
| `!on the midterm` | a callout |
| `$$S = k_B \ln \Omega$$` | display maths, typeset and centred |
| `$\Delta S \geq 0$` inline | typeset inside the sentence |
| `left \|\| right` | **panes**: boxes side by side |
| `{2} wide \|\| narrow` | panes with weights |
| `---` | a divider |

Inline `**bold**`, `_italic_` and `` `code` `` work anywhere.

## Maths

`inkwell/latex.py` is a small LaTeX typesetter built on a box model — every
fragment is some lines plus a baseline, glued together with baselines
aligned — so it can stack:

    $$\Delta S = \int_{T_1}^{T_2} \frac{C_p}{T} dT$$

                        T₂  Cₚ
                 ΔS = ∫  ──── dT
                        T₁  T

Fractions stack over a rule, `\sum`/`\int` carry their limits above and
below, `\sqrt` gets a radical rule, `\begin{bmatrix}` comes out square and
bracketed however tall its cells are. Inside a matrix a fraction stays on
its own line at full size (`2/3`) rather than stacking — a three-row cell
would drag the grid apart — and the precomposed glyphs (`⅔`) are kept for
inline prose, where they read well and a display-size letter is not sitting
next to them. Inline maths is forced onto one line instead (unicode
super/subscripts, `½`, `ⁿ⁄₂`, `[a b; c d]`), because prose has to keep
flowing. Greek, ~120 symbols, `\mathbb`/`\mathcal`, accents (`\vec{F}` →
`F⃗`), `\text{}` and the usual functions are supported; anything it cannot
read is passed through exactly as typed rather than mangled.

## Formatting across notes

The formatter looks at the notes *together*, which is what makes the page a
document rather than a list of styled strings: nesting with depth-matched
markers, tight runs, renumbered lists, shared key and value columns with dot
leaders, table columns shared across a run, pane dividers aligned into a
grid, hanging indents, and one spacing model (a blank line between blocks,
two above a section, none inside a run — gaps can never stack up).

All of it is recomputed per width. Nesting costs 2 columns wide, 1 below 50,
0 below 30. A pair table keeps its size until squeezed, then shortens its
leaders, and stacks only when two columns genuinely will not fit — as a whole
run, so a table never goes ragged. Panes stack vertically rather than squeeze
below 14 columns each. Prose stops widening at 78 columns and then centres.
Timestamps appear in a right gutter past 74 columns, once per minute.

Type size is a single accent: the title gets a block font when there is room
(preferring one line in a smaller font over two in a bigger one), and inline
markup borrows unicode letterforms. `f7` turns the title font off, `f9` the
letterforms.

## Editing

Click a note to open it. It becomes a real `urwid.Edit` with a cursor where
you clicked, wrapped in a character of blue on every side — deep blue on a
dark terminal, light blue on a light one. The halo says which box is open,
and it is part of the target: clicking it puts the cursor at the nearest
point in the text rather than doing nothing.

Along the bottom of the halo sit three buttons, five columns each:

| | |
| --- | --- |
| **⏎** (or Enter, or `f1`) | a line break, right where the cursor is |
| **✓** (or Esc, or `f12`) | done — keep it and close |
| **✕** | throw this edit away and put the note back as it was |

**Enter is a line break**, not a way out: one `⏎` is a new line inside the
block, two — a blank line — is where the note becomes two notes when you
finish it. Starting a new block inside a list keeps you in the list, so
Enter twice in `- perforated alu` gives you a second bullet.

**Arrows move about.** Inside an open note they move the cursor; walk off
the top or bottom line and the note closes and you step to the note above or
below. In the page they move from note to note, and Enter (or just typing)
opens the one you are on.

**The box at the bottom is only ever reached by clicking it.** Finishing a
note leaves you in the page, among the notes, rather than jumping the cursor
back down to the composer.

| | |
| --- | --- |
| Backspace at the start | join with the note above (its marker is dropped) |
| Delete at the end | pull the next note up into this one |
| `f6` | join the focused note upwards without opening it |
| `f4` | **split across**: turn the box into side-by-side panes |
| `f3` | fold the panes back into one box |
| click a pane | edit that pane in place, its neighbours still on screen |
| Tab / Shift-Tab | walk the panes |
| `f8` | delete the focused note |

## The optional copy editor

If a Kubi gateway key is around (`~/.config/lectern/notes-key`, or
`$INKWELL_LLM_KEY` / `$LITELLM_API_KEY`), every new note is *also* sent to
gpt-oss-20b in a background thread with the few notes above it for context.
It answers with formatting only — which kind of box, how deep, whether it
continues the note above, whether a run-on should be split into separate
items, which two halves make a pair, which phrase carries the weight. Never
type sizes, never a title, never overruling markup you typed. When the
answer lands the note re-formats in place:

    remember to email the vendor about stock    ->  ☐ email the vendor about stock
    lead time is about three weeks              ->  lead time ···· about three weeks
    cut the plate then bend it then clinch it   ->  • cut the plate
                                                   • bend it
                                                   • clinch it

Failures are silent and harmless — the page always renders from the markup
first. `--no-llm` turns it off.

## Layout

    inkwell/shaping.py      text -> notes, and each note's own markup (pure)
    inkwell/document.py     the formatter: notes -> a laid-out document (pure)
    inkwell/latex.py        LaTeX -> terminal maths, on a box model (pure)
    inkwell/typography.py   wrapping, inline letterforms, the title font
    inkwell/widgets.py      the note box: display, edit, panes, split/join
    inkwell/app.py          frame, focus, idle timer, palette, gestures
    inkwell/muse.py         the optional copy editor
    inkwell/clip.py         the system clipboard, with a fallback
    inkwell/history.py      undo, with interned snapshots
    inkwell/pdf.py          the PDF exporter
    inkwell/sfnt.py         just enough TrueType to embed a font
    inkwell/store.py        the notebooks folder and its JSON files
    inkwell/theme.py        the two palettes, contrast maths, terminal sniffing
    tools/lecture.py        types a whole lecture and prints the page
    tools/drive.py          runs the app in a real pty and prints the screen

## A textbook in inkwell

### Build the reader (start here)

*Introduction to Autonomous Robots* as a reader you can search and annotate,
built on your own machine in one command:

    python3 -m pip install --user urwid      # once; brings wcwidth + typing_extensions
    python3 tools/build_reader.py            # ~8 s: fetches the book, writes the archive
    python3 dist/IntroRobotics.pyz           # read it

The build clones the book's own LaTeX source from
[the authors' repository](https://github.com/Introduction-to-Autonomous-Robots/Introduction-to-Autonomous-Robots),
converts all 24 chapters and packs them with the reader and a vendored urwid
into one `dist/IntroRobotics.pyz`. That file needs nothing but Python 3.9+ —
copy it to any machine and run it. `--launchers` adds double-click wrappers.

**The book is not in this repository, and no built archive belongs in it
either.** *Introduction to Autonomous Robots* is CC BY-NC-ND 4.0; the print
edition is © MIT Press, and its authors ask that compiled copies of the book
stay offline. Everything here is the reader — the code — so each person
builds their own copy from the source the authors publish. `.gitignore`
keeps `iar-*.json` and `*.pyz` out.

On first run the chapters are copied into `~/Documents/Inkwell` (or
`$INKWELL_DIR`) and never over a copy already there, so margin notes survive
a rebuild.

### The reader

`tools/tex2ink.py` turns a LaTeX book into one notebook per chapter, and
`inkwell/reader.py` reads them with a table of contents:

    python3 tools/tex2ink.py ~/projects/Introduction-to-Autonomous-Robots
    python3 -m inkwell.reader              # contents menu, then read
    python3 -m inkwell.reader 3            # straight into chapter 3
    python3 -m inkwell.reader --list       # print every chapter and section
    python3 -m inkwell.reader --find kalman   # every passage that says it

In the menu: arrows move, Enter unfolds a chapter and opens a section, `esc`
closes it. Typing searches the whole book as you go -- the sections whose
titles match, then the passages that say the word, each shown in the sentence
it sits in under the chapter and section it belongs to, and Enter on a passage
opens the notebook at that note. One or two letters only filter the contents;
from three on, the prose is searched too. Inside a chapter `f2` brings the
contents back, `ctrl f` opens it ready to search, and `f10` quits; everything
else is inkwell, so the book takes margin notes.

`tools/build_reader.py` packs the reader, the notebooks and a vendored urwid
into one `dist/IntroRobotics.pyz` that runs wherever Python 3.9+ is
installed (`python3 IntroRobotics.pyz`); `--launchers` adds `.command`, `.sh`
and `.bat` double-click wrappers for those who want them. On first run the notebooks are copied into the notes
folder, never over a copy already there. `tools/smoke_reader.py` drives the
archive in a real pty as the end-to-end check; it has been run on macOS and
in a `python:3.9-slim` Linux container. Windows has not been tried: urwid
carries its own Win32 console backend and the Mac-only pieces (clipboard,
PDF font, terminal colour query) have fallbacks, but that is reasoning, not
evidence.

## Tests

    python3 -m unittest discover -s tests -t .    # 651 tests, stdlib only

`tests/test_lecture.py` is the end-to-end one: a student's 58 jotted notes
from a thermodynamics lecture (fragments, run-ons, LaTeX, a table, a
comparison, todos), then assertions that the result is a page worth reading
back — nothing overflows at any width, no LaTeX leaks, lists stay tight,
sections get air, the table and pane dividers line up, the page is >55%
content, never three blank lines together, and every note is still editable.
`tools/lecture.py [widths...]` prints that same page to look at, and
`--llm` runs it through the copy editor.

    python3 tools/lecture.py 92 56       # the lecture, two widths
    python3 tools/drive.py               # a document, re-laid at 4 widths
    python3 tools/drive.py --clicks      # click in, click off, deselect
    python3 tools/drive.py --library     # the open dialog and the theme toggle
    python3 tools/drive.py --llm         # the copy editor, live
