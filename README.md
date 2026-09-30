# inkwell

[![tests](https://github.com/Setherino/inkwell/actions/workflows/tests.yml/badge.svg)](https://github.com/Setherino/inkwell/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.9%20%E2%80%93%203.13-blue)](https://www.python.org/downloads/)
[![licence](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)

A terminal notebook that formats itself. You type into the box at the
bottom; when a thought ends it drops into the page above and is laid out as
part of a document — nested lists, aligned columns, definitions, tables,
side-by-side panes, typeset maths. Resize the window and the whole page
re-lays: nothing about a note's appearance is stored.

Nothing leaves your machine: notes are JSON files in a folder you can see,
and the one network feature is off until you point it somewhere yourself.

### What that looks like

You jot this, one thought at a time, in whatever order the lecture goes:

    # Thermo 3 - entropy
    ## The second law
    entropy always increases in an isolated system.
    entropy :: a measure of how many microstates match one macrostate
    $$S = k_B \ln \Omega$$
    - reversible: $\Delta S = 0$
    - irreversible: $\Delta S > 0$
      - all real processes are irreversible
    wait is entropy extensive or intensive?
    TODO check the microstate counting example in ch 4

and the page reads back like this — no styling stored, no mode to be in:

                 ▀▀█▀▀█                          ▄▀▀▄
                   █  █▀▀▄ ▄▀▀▄ █▀▀ █▀▄▀▄ ▄▀▀▄     ▄▀   ▄▄▄▄
                   █  █  █ █▀▀  █   █ █ █ █  █   ▄  █
                   ▀  ▀  ▀  ▀▀  ▀   ▀   ▀  ▀▀     ▀▀
                                 █
                      ▄▀▀▄ █▀▀▄ ▀█▀ █▀▀ ▄▀▀▄ █▀▀▄ █  █
                      █▀▀  █  █  █  █   █  █ █  █ ▀▄▄█
                       ▀▀  ▀  ▀   ▀ ▀    ▀▀  █▀▀   ▄▄▀

      Tʜᴇ ꜱᴇᴄᴏɴᴅ ʟᴀᴡ
      ──────────────────────────────────────────────────────────────────

      entropy always increases in an isolated system.

      𝗲𝗻𝘁𝗿𝗼𝗽𝘆 — a measure of how many microstates match one macrostate

                                 S = k  ln Ω
                                      B

      • reversible: ΔS = 0
      • irreversible: ΔS > 0
        ◦ all real processes are irreversible

      ? wait is entropy extensive or intensive?

      ☐ check the microstate counting example in ch 4

Real output, not a mockup — those are the notes above put through the
formatter. It is a trimmed excerpt: `python3 tools/lecture.py 68` runs a
whole lecture's 58 notes and prints the page this opens.

    inkwell                     # opens the newest notebook in ~/Documents/Inkwell
    inkwell HW0                 # ...or a notebook by name (exact names keep their case)
    inkwell --theme light       # light | dark | auto (the default: ask the terminal)
    inkwell hw0 --export hw0.pdf --width 92     # print it and stop
    inkwell --no-save           # scratch session
    inkwell --no-llm            # markup only, no network
    inkwell --ascii             # no unicode letterforms

### Install

One dependency — [urwid](https://urwid.org) — and Python 3.9 or newer.
Everything else is stdlib on purpose: the PDF writer, the TrueType parser,
the LaTeX typesetter and the clipboard.

    python3 -m pip install git+https://github.com/Setherino/inkwell

Or run it straight from a checkout. `bin/inkwell` follows symlinks, so it
works from anywhere on `$PATH`:

    python3 -m pip install --user urwid
    ln -s "$PWD/bin/inkwell" ~/.local/bin/inkwell

macOS and Linux are tested (3.9 and 3.13, in CI). Windows has not been
tried — see *Books* for what that rests on.

| | |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | the code, and which decisions are load bearing |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to work on it |
| [CHANGELOG.md](CHANGELOG.md) | what changed |
| [LICENSE](LICENSE) | MIT |

## Notebooks

Notes live in **`~/Documents/Inkwell`** — one JSON file per notebook,
somewhere you would actually look for them. `$INKWELL_DIR` puts them
somewhere else. `f2` opens the folder:

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

## Esc goes up

The interface is a tree whether anyone writes it down or not, so it is
written down:

    0  the shelf                   which book (the reader only)
    1  the folder of notebooks     f2 — the reader puts a book's contents here
    2  the box at the bottom       where a thought gets typed
    3  the page                    a note has the cursor bar; arrows scroll
    4  an open box                 the halo, or one of its panes

`esc` is **one step up that tree, from wherever you are** — and it is the
same key the whole way, so there is never anything to remember about which
level you are on:

    [open box] ─esc→ [page] ─esc→ [box at the bottom] ─esc→ [folder]

A tree can be taller in one app than another. The reader adds the shelf
above a book's contents, and the same key walks back out through both:

    ... ─esc→ [box at the bottom] ─esc→ [contents] ─esc→ [shelf]

Going up keeps your work: leaving an open box files what it says, exactly
as **✓** does. Throwing an edit away is the **✕** button, deliberately not
a key you can hit by accident.

Two consequences worth stating, because they are decisions rather than
accidents:

- **A picked run of notes, a selection inside a box and a filter typed into
  the contents do not get rungs of their own.** They decorate a level
  rather than being one, so they go when you leave the level they belong to
  — nothing in the app takes two presses of `esc` to get out of. (Backspace
  still clears the contents filter in place, which is what you want while
  you are searching.)
- **The folder remembers what it covered.** `esc` at the top steps it aside
  and puts the cursor back on the level it was hiding, so `esc` `esc` from
  the box at the bottom is a round trip rather than a way of ending up
  somewhere deeper than you started.

No widget decides what "up" means from where it sits — a note cannot know
what is above it. They hand `esc` back, it reaches `Inkwell.ascend`, and
that one method is the whole ladder. `inkwell/app.py` carries the levels as
`ROOT`…`EDITING`; `tests/test_escape.py` asserts the rungs, and that `esc`
strictly ascends from every one of them.

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
| **✓** (or `f12`, or `esc`) | done — keep it and close |
| **✕** | throw this edit away and put the note back as it was |

**Enter is a line break**, not a way out: one `⏎` is a new line inside the
block, two — a blank line — is where the note becomes two notes when you
finish it. Starting a new block inside a list keeps you in the list, so
Enter twice in `- perforated alu` gives you a second bullet.

**Arrows move about.** Inside an open note they move the cursor; walk off
the top or bottom line and the note closes and you step to the note above or
below. In the page they move from note to note, and Enter (or just typing)
opens the one you are on.

**Finishing a note leaves you in the page**, among the notes, rather than
jumping the cursor back down to the composer. Getting back down there is
`esc`'s job, not Enter's — see *Esc goes up* above.

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

**Off unless you point it somewhere.** There is no default endpoint: a
notes app should not send anything anywhere until its owner has said where.
Give it an OpenAI-compatible `/v1` — llama.cpp, vLLM, Ollama, LM Studio, a
hosted API — and every new note is *also* sent to it in a background thread
with the few notes above it for context.

    export INKWELL_LLM_URL=http://localhost:8080/v1
    export INKWELL_LLM_KEY=whatever-your-endpoint-wants   # or ~/.config/inkwell/key
    export INKWELL_LLM_MODEL=your-model-name              # optional
    export INKWELL_LLM_EFFORT=low                         # reasoning models only

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
    inkwell/reader.py       books: the shelf, a contents, search
    tools/lecture.py        types a whole lecture and prints the page
    tools/drive.py          runs the app in a real pty and prints the screen
    tools/tex2hw.py         one LaTeX document -> one notebook
    tools/tex2ink.py        a LaTeX book -> one notebook per chapter
    tools/build_reader.py   packs the reader and a book into one .pyz
    tools/smoke_reader.py   drives a built archive, end to end

## A homework sheet

A problem set arrives as one `.tex` file, and the point of putting it in a
notebook is that the questions and your working end up in the same place:

    python3 tools/tex2hw.py ~/Downloads/HW2/HW2.tex --student "Your Name"
    inkwell HW2

Every question comes across as it was set — the maths typeset, the lists
numbered, the tables square — and the blank space each one leaves you to
write in becomes `☐ solution`, a checkbox to tick as you go. The title
block turns into the notebook's front matter: what the course is, when it
is due, and the path of the file it was built from, so a month later the
notebook can still tell you.

It reads a *whole document* — preamble, `\newcommand` macros, `\maketitle`
— which is the shape `tools/tex2ink.py` below does not do: that one
converts a book, whose chapters are already inside `\begin{document}`.

## Books

### Getting one (start here)

*Introduction to Autonomous Robots* as a reader you can search and annotate,
in one command:

    git clone https://github.com/Setherino/inkwell && cd inkwell
    python3 -m pip install --user urwid
    python3 tools/build_reader.py --clone iar     # ~12 s
    python3 dist/IntroRobotics.pyz                # read it

That fetches the book's own LaTeX source from
[the authors' repository](https://github.com/Introduction-to-Autonomous-Robots/Introduction-to-Autonomous-Robots),
converts all 24 chapters (2,090 notes), and packs them with the reader and a
vendored urwid into one file that needs nothing but Python 3.9+ — copy it to
any machine and run it. `--launchers` adds double-click wrappers. On first
run the chapters are copied into `~/Documents/Inkwell` and never over a copy
already there, so margin notes survive a rebuild.

`--books` lists the books that can be fetched by name. Any other book is the
same command with a URL or a path:

    python3 tools/build_reader.py --clone https://github.com/…/book.git
    python3 tools/build_reader.py --book ~/some-latex-book

### What a book is

A **book is a naming convention, not a special file**: any two or more
notebooks in the notes folder sharing a `<prefix>-<slot>-<title>.json` name
are read as one book, in that order.

    iar-01-introduction.json  iar-02-kinematics.json  ...   ->  one book
    thermo-01-first-law.json  thermo-02-entropy.json  ...   ->  another
    hw0.json                                                ->  just a notebook

Nothing in the code knows which book. So a folder holds as many as you
convert into it, and they turn up on the **shelf** on their own:

    ┌────────────────────────────── Shelf ──────────────────────────────┐
    │   find: 2 books                                                   │
    │ ───────────────────────────────────────────────────────────────── │
    │ ▸ Autonomous Robots                        24 chapters 2090 notes │
    │   Engineering Thermodynamics                8 chapters  412 notes │
    │ ───────────────────────────────────────────────────────────────── │
    │  ↑↓ move · ⏎ open · esc back · f10 quit                           │
    └───────────────────────────────────────────────────────────────────┘

That is the level above a book's own contents, so the reader's tree is two
deep at the top and `esc` walks back out through both (see *Esc goes up*).
With only one book on the shelf the reader never shows it — there would be
nothing to choose.

An optional `<prefix>.book.json` beside the chapters says what the book is
called; `tools/tex2ink.py` writes one from the source's own `\title{}`.
Without a manifest the prefix is used (`iar` → `IAR`).

### Converting a book

`tools/tex2ink.py` turns a LaTeX tree into one notebook per chapter. It
reads `book.tex` for the reading order and emits only markup a person could
have typed, so a converted chapter is an ordinary inkwell page — editable,
re-laid at any width, and yours to write in the margins of.

    python3 tools/tex2ink.py ~/some-latex-book          # prefix + title from the book
    python3 tools/tex2ink.py ~/book --prefix THERMO --title "Engineering Thermodynamics"

### Reading

    python3 -m inkwell.reader                  # the shelf, then read
    python3 -m inkwell.reader iar              # straight into one book
    python3 -m inkwell.reader iar 3            # ...at chapter 3
    python3 -m inkwell.reader --list           # every book, and its chapters
    python3 -m inkwell.reader --find kalman    # search the whole shelf

In a book's contents: arrows move, Enter unfolds a chapter and opens a
section, `f3` goes to the shelf, `esc` steps back out. Typing searches that
whole book as you go — the sections whose titles match, then the passages
that say the word, each shown in the sentence it sits in under the chapter
and section it belongs to, and Enter on a passage opens the notebook at
that note. One or two letters only filter the contents; from three on the
prose is searched too. Inside a chapter `f2` brings the contents back and
`ctrl f` opens it ready to search.

### Packing one up

`tools/build_reader.py` packs the reader, a book (or your whole shelf) and a
vendored urwid into a single `.pyz` that runs wherever Python 3.9+ is
installed — one file, no install:

    python3 tools/build_reader.py                          # your shelf as it stands
    python3 tools/build_reader.py --book ~/some-latex-book # convert, then pack
    python3 tools/build_reader.py --clone https://github.com/…/book.git
    python3 tools/build_reader.py --prefix iar --name IntroRobotics

`--launchers` adds `.command`, `.sh` and `.bat` double-click wrappers. On
first run the notebooks are copied into the notes folder, never over a copy
already there, so margin notes survive a rebuild.

`tools/smoke_reader.py` drives a built archive in a real pty as the
end-to-end check; it has been run on macOS and in a `python:3.9-slim` Linux
container. Windows has not been tried: urwid carries its own Win32 console
backend and the Mac-only pieces (clipboard, PDF font, terminal colour query)
have fallbacks, but that is reasoning, not evidence.

### On other people's books

**No book is in this repository, and no built archive belongs in one
either.** A book's own licence governs its text, and plenty of them —
including *Introduction to Autonomous Robots*, the book this reader was
written for (CC BY-NC-ND 4.0, print edition © MIT Press) — do not permit
redistributing a converted copy. Everything here is the reader; each person
converts their own from the source the publisher offers. `.gitignore` keeps
converted notebooks and `*.pyz` out of git, and `--clone` takes the URL you
give it rather than shipping one.

## Tests

    python3 -m unittest discover -s tests -t .    # 730 tests, stdlib only

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
    python3 tools/drive.py --escape      # esc climbing the tree, rung by rung
    python3 tools/drive.py --shelf       # two books, and esc back out through both
    python3 tools/drive.py --llm         # the copy editor, live
