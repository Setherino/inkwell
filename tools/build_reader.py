#!/usr/bin/env python3
"""Pack the textbook reader into one portable file.

    python3 tools/build_reader.py                       # dist/IntroRobotics.pyz
    python3 tools/build_reader.py --clone iar        # a book, by name
    python3 tools/build_reader.py --notebooks ~/Documents/Inkwell --out /tmp/x/Reader.pyz

The result is a Python zip application: inkwell, the reader, the book's
notebooks and a vendored copy of urwid (pure Python, with its two small
dependencies) in a single ``.pyz``. It runs anywhere Python 3.9+ is
installed -- ``python3 IntroRobotics.pyz`` -- and that one file is the whole
deliverable. ``--launchers`` also writes ``.command``/``.sh``/``.bat``
double-click wrappers beside it for people who would rather not type. No
Python is bundled; that is the one thing the reader asks of the machine.

``--book`` converts the LaTeX source fresh with tools/tex2ink.py so the
archive never carries anyone's margin notes; ``--notebooks`` packs an
existing folder of ``iar-*.json`` files instead. With neither -- a fresh
clone of this repository, say -- the book's own LaTeX source is fetched
from GitHub first (``--clone`` asks for that outright), so building the
reader is one command on a machine that has never seen the book.

The book itself is not in this repository and never travels in it: it is
CC BY-NC-ND, and its authors ask that compiled copies stay offline. Each
reader is built locally from the source the authors publish.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inkwell import reader, store  # noqa: E402

# Books that are published openly and convert cleanly, so fetching one is a
# single command with nothing to look up. This is a convenience list, not a
# capability: --clone takes any git URL, and the tool has no opinion about
# which book you read. A book's own licence governs its text -- see the
# README -- which is why nothing here is redistributed, only fetched.
CATALOGUE = {
    "iar": ("https://github.com/Introduction-to-Autonomous-Robots"
            "/Introduction-to-Autonomous-Robots.git",
            "Introduction to Autonomous Robots",
            "CC BY-NC-ND 4.0, print edition (c) MIT Press"),
}


def source_url(what: str) -> str:
    """What --clone was given: a catalogue name, or a URL as it stands."""
    known = CATALOGUE.get(str(what).strip().lower())
    return known[0] if known else what

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.so", "*.pyd",
                                "tests", "test_*")

MAIN = """\
import sys
from inkwell.reader import main
sys.exit(main())
"""

COMMAND = """\
#!/bin/sh
# Double-click on macOS (or run from a shell): opens the book in a terminal.
cd "$(dirname "$0")" && exec python3 "{name}.pyz" "$@"
"""

BAT = """\
@echo off
rem Opens the book. Needs Python 3.9+ from python.org (tick "Add to PATH").
where py >nul 2>nul && (py -3 "%~dp0{name}.pyz" %*) || (python "%~dp0{name}.pyz" %*)
if errorlevel 1 pause
"""


def fetch_book(into, url: str, run=subprocess.run) -> Path:
    """Clone a book's LaTeX source into *into*. Shallow: only the text."""
    into = Path(into)
    run(["git", "clone", "--depth", "1", url, str(into)], check=True)
    return into


def plan(book=None, notebooks=None, clone=None) -> str:
    """Where this build gets its books.

    A URL is cloned, a LaTeX root is converted, and with neither the notes
    folder is packed exactly as it stands -- which is the common case once
    a book has been converted into it.
    """
    if clone:
        return "clone"
    if book and Path(book).is_dir():
        return "convert"
    if book:
        raise SystemExit(f"no LaTeX source at {book}")
    return "notebooks"


def _vendor(name: str) -> Path:
    """Where an installed pure-Python dependency lives, package dir or module file."""
    module = __import__(name)
    path = Path(module.__file__)
    return path.parent if path.name == "__init__.py" else path


LAZY_ANCHOR = "    loader = importlib.util.LazyLoader(spec.loader)\n"
LAZY_GUARD = ('    if not hasattr(spec.loader, "exec_module"):\n'
              "        # zipimport grew exec_module in Python 3.10; on 3.9 a .pyz\n"
              "        # cannot use LazyLoader, so this stub imports the real module\n"
              "        # the first time anything is asked of it (inkwell build patch).\n"
              "        stub = __import__('types').ModuleType(spec.name)\n"
              "        def _load(attr, _name=name, _package=package, _stub=stub):\n"
              "            sys.modules.pop(_stub.__name__, None)\n"
              "            real = importlib.import_module(_name, _package)\n"
              "            _stub.__dict__.update(real.__dict__)\n"
              "            return getattr(real, attr)\n"
              "        stub.__getattr__ = _load\n"
              "        sys.modules[spec.name] = stub\n"
              "        return stub\n")


LAZY_FILES = ("__init__.py", "display/__init__.py")   # both define lazy_import


def patch_urwid(urwid_dir: Path) -> None:
    """Let urwid import from a .pyz on Python 3.9."""
    for rel in LAZY_FILES:
        path = urwid_dir / rel
        text = path.read_text()
        if LAZY_GUARD in text:
            continue
        if text.count(LAZY_ANCHOR) != 1:
            raise RuntimeError(f"urwid changed: cannot find lazy_import anchor in {path}")
        path.write_text(text.replace(LAZY_ANCHOR, LAZY_GUARD + LAZY_ANCHOR))


def shelved(notebooks: Path, prefix: str = "") -> list:
    """The files one archive should carry: whole books, and what names them.

    With no prefix every book in the folder travels, so one archive can hold
    a shelf. Loose notebooks are left behind -- they are somebody's notes,
    not a book.
    """
    notebooks = Path(notebooks)
    wanted = [prefix] if prefix else reader.prefixes(notebooks)
    files: list = []
    for each in wanted:
        files += sorted(notebooks.glob(f"{each}-*.json"))
        manifest = reader.manifest_path(notebooks, each)
        if manifest.exists():
            files.append(manifest)
    return files


def stage(notebooks: Path, staging: Path, prefix: str = "") -> None:
    """Lay the archive out in *staging*."""
    shutil.copytree(ROOT / "inkwell", staging / "inkwell", ignore=IGNORE)
    book = staging / "inkwell" / reader.BOOK_FOLDER
    book.mkdir()
    for path in shelved(notebooks, prefix):
        shutil.copy2(path, book / path.name)
    for dep in ("urwid", "wcwidth"):
        shutil.copytree(_vendor(dep), staging / dep, ignore=IGNORE)
    shutil.copy2(_vendor("typing_extensions"), staging / "typing_extensions.py")
    patch_urwid(staging / "urwid")
    (staging / "__main__.py").write_text(MAIN)


def launchers(out: Path, name: str) -> list:
    made = []
    for suffix, text in ((".command", COMMAND), (".sh", COMMAND), (".bat", BAT)):
        path = out.with_name(name + suffix)
        body = text.format(name=name)
        if suffix == ".bat":
            path.write_bytes(body.replace("\n", "\r\n").encode())
        else:
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        made.append(path)
    return made


def build(notebooks, out, name: str = "Reader", prefix: str = "",
          with_launchers: bool = False) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="reader-"))
    try:
        stage(Path(notebooks), staging, prefix)
        zipapp.create_archive(staging, out, interpreter="/usr/bin/env python3",
                              compressed=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if with_launchers:
        launchers(out, name)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--book", type=Path, default=None,
                        help="a LaTeX root to convert fresh")
    source.add_argument("--notebooks", type=Path, default=None,
                        help="pack a folder of already-converted notebooks "
                             "(the default: your notes folder, whole shelf)")
    source.add_argument("--clone", metavar="NAME_OR_URL", default=None,
                        help="fetch a book's LaTeX source and convert it: a "
                             "name from --books, or any git URL")
    parser.add_argument("--books", action="store_true",
                        help="list the books --clone knows by name, and stop")
    parser.add_argument("--prefix", default="",
                        help="pack just one book out of the folder, by prefix "
                             "(default: every book in it)")
    parser.add_argument("--title", default="",
                        help="what to call a freshly converted book")
    parser.add_argument("--out", type=Path, default=None,
                        help="archive path (default: dist/<name>.pyz)")
    parser.add_argument("--name", default=None,
                        help="archive name (default: from --out, or the book)")
    parser.add_argument("--launchers", action="store_true",
                        help="also write .command/.sh/.bat wrappers beside the archive")
    args = parser.parse_args(argv)
    if args.books:
        print("Books --clone knows by name:\n")
        for name, (url, title, licence) in sorted(CATALOGUE.items()):
            print(f"  {name:8s} {title}\n           {url}\n           {licence}\n")
        print("Any git URL works too. Each copy is built locally from the\n"
              "source the publisher offers; no book travels in this repository.")
        return 0

    how = plan(args.book, args.notebooks, args.clone)
    if how == "notebooks":
        notebooks = Path(args.notebooks or store.DEFAULT_DIR)
    else:
        source = args.book
        if how == "clone":
            source = Path(tempfile.mkdtemp(prefix="book-src-")) / "book"
            url = source_url(args.clone)
            print(f"fetching LaTeX source from {url}")
            fetch_book(source, url)
        from tools import tex2ink
        notebooks = Path(tempfile.mkdtemp(prefix="book-"))
        prefix = args.prefix or tex2ink.prefix_for(source)
        written = tex2ink.convert(source, notebooks, prefix=prefix,
                                  title=args.title)
        print(f"converted {len(written)} chapters from {source}")
        args.prefix = prefix.lower()

    shelf = reader.books(notebooks)
    if args.prefix:
        shelf = [b for b in shelf if b.prefix == args.prefix.lower()]
    if not shelf:
        names = ", ".join(sorted(CATALOGUE))
        print(f"no book to pack in {notebooks}.\n\n"
              f"Fetch one that is known to convert cleanly ({names}):\n"
              f"    python3 tools/build_reader.py --clone iar\n\n"
              f"...or point it at a LaTeX tree, or any git URL:\n"
              f"    python3 tools/build_reader.py --book ~/some-latex-book\n"
              f"    python3 tools/build_reader.py --clone https://…/book.git\n\n"
              f"See --books for the list, and --help for the rest.",
              file=sys.stderr)
        return 1
    name = (args.name or (args.out.stem if args.out else None)
            or (store.slug(shelf[0].title) if len(shelf) == 1 else "Shelf"))
    out = args.out or ROOT / "dist" / (name + ".pyz")
    print("packing: " + ", ".join(f"{b.title} ({len(b.chapters)})" for b in shelf))
    out = build(notebooks, out, name, prefix=args.prefix,
                with_launchers=args.launchers)
    size = out.stat().st_size // 1024
    print(f"{out}  ({size} KB)")
    for path in sorted(out.parent.glob(name + ".*")):
        if path != out:
            print(f"  {path.name}")
    print(f"run:  python3 {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
