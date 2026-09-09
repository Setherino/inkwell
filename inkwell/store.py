"""Notebooks on disk.

One folder of plain JSON files -- ``~/Documents/Inkwell`` by default, so the
notes are somewhere a person would look for them, next to everything else
they write. Each file is a notebook; the app can switch between them.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_DIR = Path(os.environ.get("INKWELL_DIR",
                                  Path.home() / "Documents" / "Inkwell"))
DEFAULT_NAME = "notes.json"
SUFFIX = ".json"


def default_path(directory: Path | None = None) -> Path:
    return (directory or DEFAULT_DIR) / DEFAULT_NAME


@dataclass
class Note:
    text: str
    created: float = field(default_factory=time.time)
    # How the model says to format this line ({} = format it from its own
    # markup). See muse.py for the fields.
    fmt: dict = field(default_factory=dict)
    tag: str = ""
    emphasis: str = ""
    done: bool = False

    def stamp(self) -> str:
        return time.strftime("%H:%M", time.localtime(self.created))


def load(path) -> list:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    notes = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            notes.append(Note(item))
        elif isinstance(item, dict) and item.get("text"):
            fields = {k: v for k, v in item.items() if k in Note.__annotations__}
            notes.append(Note(**fields))
    return notes


def stamp_of(path) -> float:
    """When the file was last written, or 0 if it is not there."""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return 0.0


def save(notes, path) -> float:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(n) for n in notes], indent=1))
    tmp.replace(path)
    return stamp_of(path)


def beside(path, why: str = "conflict") -> Path:
    """A free name next to *path*, for when writing over it would lose work."""
    path = Path(path)
    stamp = time.strftime("%H%M%S")
    candidate = path.with_name(f"{path.stem}-{why}-{stamp}{path.suffix}")
    count = 2
    while candidate.exists():
        candidate = path.with_name(
            f"{path.stem}-{why}-{stamp}-{count}{path.suffix}")
        count += 1
    return candidate


# --- the folder -------------------------------------------------------------
def notebooks(directory: Path | None = None) -> list:
    """Every notebook in the folder, most recently written first."""
    directory = Path(directory or DEFAULT_DIR)
    try:
        found = [p for p in directory.iterdir()
                 if p.is_file() and p.suffix == SUFFIX]
    except OSError:
        return []
    return sorted(found, key=lambda p: (-p.stat().st_mtime, p.name.lower()))


def title_of(path) -> str:
    """A notebook's name, as shown in the open dialog."""
    return Path(path).stem.replace("-", " ").replace("_", " ")


def slug(name: str) -> str:
    """A filename someone typed, made safe."""
    cleaned = re.sub(r"[^\w\s-]", "", name).strip().lower()
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return cleaned or "untitled"


def path_for(name: str, directory: Path | None = None) -> Path:
    return Path(directory or DEFAULT_DIR) / (slug(name) + SUFFIX)


def ensure(directory: Path | None = None) -> Path:
    """Make the notes folder if it is not there yet.

    There is deliberately no import from anywhere else: a second copy of a
    notebook is how you end up editing the wrong one, so this never brings
    a file in from another directory.
    """
    directory = Path(directory or DEFAULT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
