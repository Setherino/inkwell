# Contributing

Thanks for looking. This is a small, opinionated program; the notes below are
mostly about the opinions, so a change does not have to be guessed at twice.

## Getting set up

```
git clone https://github.com/Setherino/inkwell
cd inkwell
python3 -m pip install --user urwid          # the only dependency
python3 -m unittest discover -s tests -t .   # should be all green
python3 bin/inkwell --no-save --no-llm       # try it
```

`bin/inkwell` runs from the checkout and follows symlinks, so
`ln -s "$PWD/bin/inkwell" ~/.local/bin/inkwell` works.

Python 3.9 is the floor, because a packed reader has to run on a machine
nobody has prepared. CI checks 3.9 and 3.13, on Linux and macOS.

## Tests first, and evidence for claims

Please write the test before the fix, and please don't say something works
without having watched it work.

- **Unit tests** are stdlib `unittest`. No pytest, no plugins.
- **`tools/drive.py`** drives the app in a real pty and prints the screen. If
  a change affects what is *drawn* — layout, focus, a key — a unit test
  cannot see it and a `drive.py` scenario can. Add one, or extend one.
- **`tests/test_lecture.py`** asserts page quality on a real lecture's notes.
  If your change makes pages uglier, this is what will say so.

A PR that says "tested manually" is fine if you paste what you saw. A PR that
says "should work" is the thing to avoid.

## House style

The code reads like prose on purpose; matching it matters more than any
linter would.

- **Comments say *why*, never *what*.** If a line needs explaining, it is
  usually the design that needs explaining. Several comments in here exist
  only to stop the next person re-introducing a bug — those are the good ones.
- **Docstrings are for the reader of the code**, and often carry the
  decision: see `Inkwell.ascend` or `document.py`'s spacing model.
- Names are words, not abbreviations. `holding_the_view`, `at_the_end`,
  `_close_boxes`.
- No new dependencies, please. The PDF writer, the TrueType parser, the LaTeX
  typesetter and the clipboard are all stdlib deliberately — that is what
  makes a one-file reader possible. urwid is the only import, and the only
  one there will be.

## Things that are load bearing

Read [docs/architecture.md](docs/architecture.md) before a structural change.
The short version of what not to undo:

1. **Nothing about appearance is stored.** Derive it at render time.
2. **`esc` is one step up the tree, and `Inkwell.ascend` is the only thing
   that decides what "up" means.** Widgets hand `esc` back.
3. **The view must not move.** Wrap document changes in
   `holding_the_view()`.
4. **Every gap lives in `gap_before`.** One spacing model; gaps cannot stack.
5. **The copy editor is optional and off by default.** Nothing may block the
   typing path on the network, and there is deliberately no default endpoint.

## Books

A book is a naming convention, not a format — see the README. If you are
adding to the reader, the test to keep passing is that it works for *any*
book, not the one it was written for.

**Please do not commit book content.** A book's own licence governs its text,
and many do not permit redistributing a converted copy. `.gitignore` keeps
converted chapters and built `.pyz` archives out; if you add a fixture, make
it a few lines you wrote yourself (see `make_book` in `tests/test_reader.py`).

## Reporting a bug

What the terminal is, how wide, what you typed, and what you expected instead.
A screenshot of the terminal is worth a lot here, because most of the bugs
worth reporting are about what ended up on screen.

If it is a formatting bug, the notebook JSON (or just the offending note's
text) is the fastest possible repro.

## Licence

MIT, and contributions come in under the same. You keep the copyright to what
you write.
