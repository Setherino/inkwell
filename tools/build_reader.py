#!/usr/bin/env python3
"""Pack the textbook reader into one portable file.

    python3 tools/build_reader.py                       # dist/IntroRobotics.pyz
    python3 tools/build_reader.py --book ~/projects/Introduction-to-Autonomous-Robots
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

from inkwell import reader  # noqa: E402

# Where the book comes from: the authors' own repository, the only place a
# copy of it should be got from.
BOOK_REPO = ("https://github.com/Introduction-to-Autonomous-Robots"
             "/Introduction-to-Autonomous-Robots.git")

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


def fetch_book(into, url: str = BOOK_REPO, run=subprocess.run) -> Path:
    """Clone the book's LaTeX source into *into*. Shallow: only the text."""
    into = Path(into)
    run(["git", "clone", "--depth", "1", url, str(into)], check=True)
    return into


def plan(book, notebooks, clone: bool) -> str:
    """Where this build gets the book: given notebooks, a clone, or a fetch."""
    if notebooks:
        return "notebooks"
    if clone or not Path(book).is_dir():
        return "clone"
    return "convert"


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


def stage(notebooks: Path, staging: Path, prefix: str = reader.PREFIX) -> None:
    """Lay the archive out in *staging*."""
    shutil.copytree(ROOT / "inkwell", staging / "inkwell", ignore=IGNORE)
    book = staging / "inkwell" / reader.BOOK_FOLDER
    book.mkdir()
    for path in sorted(Path(notebooks).glob(f"{prefix}-*.json")):
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


def build(notebooks, out, name: str = "IntroRobotics", prefix: str = reader.PREFIX,
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
    source.add_argument("--book", type=Path,
                        default=Path.home() / "projects/Introduction-to-Autonomous-Robots",
                        help="LaTeX root to convert fresh (default: the clone in ~/projects)")
    source.add_argument("--notebooks", type=Path,
                        help="pack an existing folder of iar-*.json instead")
    source.add_argument("--clone", action="store_true",
                        help="clone the book's LaTeX source from GitHub and "
                             "convert that (what a fresh checkout does anyway)")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "IntroRobotics.pyz")
    parser.add_argument("--name", default=None, help="archive name (default: from --out)")
    parser.add_argument("--launchers", action="store_true",
                        help="also write .command/.sh/.bat wrappers beside the archive")
    args = parser.parse_args(argv)
    name = args.name or args.out.stem

    how = plan(args.book, args.notebooks, args.clone)
    if how == "notebooks":
        notebooks = args.notebooks
    else:
        source = args.book
        if how == "clone":
            source = Path(tempfile.mkdtemp(prefix="book-src-")) / "book"
            print(f"fetching the book's LaTeX source from {BOOK_REPO}")
            fetch_book(source)
        from tools import tex2ink
        notebooks = Path(tempfile.mkdtemp(prefix="book-"))
        written = tex2ink.convert(source, notebooks, prefix=reader.PREFIX.upper())
        print(f"converted {len(written)} chapters from {source}")
    out = build(notebooks, args.out, name, with_launchers=args.launchers)
    size = out.stat().st_size // 1024
    print(f"{out}  ({size} KB)")
    for path in sorted(out.parent.glob(name + ".*")):
        if path != out:
            print(f"  {path.name}")
    print(f"run:  python3 {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
