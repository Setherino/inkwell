# Architecture

A map of the code, for someone about to change it. The README describes what
inkwell *does*; this is how it is put together and which decisions are load
bearing.

## The one idea

**Nothing about a note's appearance is stored.** A note is text, a timestamp,
and at most a few formatting hints. Every time the screen is drawn,
`document.py` lays the whole page out again at the current terminal width.

That is why a resize is a re-*format* rather than a re-flow: the page is not
adjusted, it is decided again from scratch. It is also why there is no
"styled document" model to keep in sync with anything, and why a notebook is
a readable JSON file you could edit in any editor.

If you are adding a feature, the question to ask is: *can this be derived at
render time?* If yes, derive it. Persisting appearance is how this codebase
would rot.

## Layers

Nothing below points upwards. `app.py` may import `document.py`; never the
other way round.

```
             store.py        notebooks on disk (JSON), the notes folder
                │
           shaping.py        one line of text -> what kind of box it is
                │
          typography.py      widths, columns, block fonts
           latex.py          $maths$ -> a box model with baselines
                │
          document.py        ALL the notes together -> a laid-out page
                │
           widgets.py        one note as a widget; the composer; dialogs
                │
             app.py          the tree, focus, undo, saving, keys
                │
          reader.py          books: a shelf, a contents, search
```

Off to the side, depending on the core but not depended on:

| | |
| --- | --- |
| `muse.py` | the optional copy editor. A thread and a queue in front of an OpenAI-compatible endpoint. Off unless configured; never on the typing path. |
| `pdf.py`, `sfnt.py` | PDF export. `sfnt.py` parses TrueType and rebuilds a standalone font; `pdf.py` writes Type0/Identity-H. No dependencies. |
| `theme.py` | two palettes, built to measured WCAG contrast, and terminal background detection. |
| `history.py` | undo. Interned frozen note states, so unchanged notes are shared between snapshots. |
| `clip.py` | the system pasteboard, with an in-process fallback. |

## `document.py` owns everything visible

This is the piece to understand before changing anything about layout.

It does not format notes one at a time — it looks at them **together**, which
is where nesting, tight runs of list items, renumbering, shared key/value and
table columns, and pane grids come from. A note cannot know it is the second
item of a list; the document can.

Two rules inside it are easy to break by accident:

- **Every gap lives in `gap_before`.** There is one spacing model and gaps
  cannot stack. If you find yourself adding a blank line somewhere else, you
  are about to create a page with three blank lines in it.
- **`shaping.classify` reads the kind from the first line only.** A
  multi-line note is a paragraph unless its first line says otherwise, and
  one-line kinds (`kv`, `term`, `table`, `math`, `panes`, `rule`) are
  downgraded when broken across lines.

## The tree

The interface is a tree, so it is written down as one, in `app.py`:

```
SHELF     0   which book              (reader only)
ROOT      1   the folder of notebooks (reader: one book's contents)
COMPOSER  2   the box at the bottom
PAGE      3   a note has the cursor bar; arrows scroll
EDITING   4   an open box -- the halo, or one of its panes
```

`Inkwell.depth()` reads which level has the cursor. `Inkwell.ascend()` is
**the whole escape ladder in one method**, and `esc` is one step up it from
wherever you are.

Two things follow that are worth not undoing:

1. **No widget handles `esc`.** `NoteWidget`, `Composer`, `Library` and the
   reader's `Menu` and `Shelf` all `return key`, so it bubbles through urwid
   to `unhandled_input` and reaches `ascend`. A widget cannot know what is
   above it; only the app knows the shape of the tree. (`f2` and `ctrl f`
   *are* widget-owned toggles — a toggle is not a rung.)
2. **Transient decorations are not levels.** A picked run of notes, a
   selection inside a box, a filter typed into the contents — these decorate
   a level rather than being one, and they go when you leave it. Nothing in
   the app takes two presses of `esc` to get out of.

A tree can be taller in one app than another: plain inkwell tops out at
`ROOT`, the reader has the shelf above it. Same ladder either way. If you add
a modal, give it a level, teach `depth()` about it, and let `ascend` do the
rest — and have it remember what it covered (`_came_from` / `_uncover`) so
`esc` never lands the reader somewhere deeper than they left.

## The view must not move

Anything that changes the document records where the reader is looking and
puts it back. `Inkwell.holding_the_view()` captures (listbox position,
offset) and restores it; it wraps reformat, settle, undo, the model's answer
landing, the theme flipping, and resize.

`commit` is the deliberate exception — it scrolls only when `at_the_end()`
says the last note is already on screen. Typing at the foot of the page
follows along; reading further up is left exactly where it was.

A note's blank spacing rows belong to the *page*, not the note
(`NoteWidget.content_rows`), so clicking in a gap deselects rather than
opening the note above it.

## Books are a naming convention

There is no book format and nothing knows which book. Two or more notebooks
sharing a `<prefix>-<slot>-<title>.json` name are read as one book, in that
order; a folder holds as many as you convert into it. An optional
`<prefix>.book.json` names it. `reader.books()` is the whole discovery layer.

This is why the reader generalizes: it was written for one textbook, and
making it plural meant deleting assumptions rather than adding a mechanism.

## Testing

The suite is stdlib `unittest`, no pytest, and runs without a terminal:

```
python3 -m unittest discover -s tests -t .
```

Two kinds of test earn their keep here beyond the unit tests:

- **`tests/test_lecture.py`** asserts *page quality* on a real 58-note
  lecture: nothing overflows at any width, no LaTeX leaks, lists stay tight,
  >55% of rows are content, never three blank lines together, tables and pane
  dividers line up, every note still editable. It is the test that catches
  "technically correct, unreadable".
- **`tools/drive.py`** runs the app in a **real pty** with a just-enough VT
  parser, so a scenario can assert on what is actually on screen. Unit tests
  cannot see a rendering regression; this can.

```
python3 tools/drive.py --escape    # esc climbing the tree, rung by rung
python3 tools/drive.py --shelf     # two books, and esc back out through both
python3 tools/drive.py --clicks    # click in, click off
```

When you fix a bug, the useful question is which of these three would have
caught it, and whether it now does.
