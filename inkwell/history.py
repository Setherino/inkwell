"""Undo, all the way back.

Every change to the page records a snapshot: a tuple of frozen note states.
Two things make a million of them affordable rather than absurd:

* states are **interned**, so a note that did not change in this edit is the
  same object in every snapshot that contains it -- a snapshot of a 50-note
  page costs a 50-pointer tuple (~450 bytes), not 50 copies of the text
* identical snapshots are never recorded twice

So the cost of a step is what actually changed, and the history holds the
page as it was, not a pile of duplicates.
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import Note

LIMIT = 1_000_000


@dataclass(frozen=True)
class State:
    """One note, frozen hard enough to be shared between snapshots."""

    text: str
    created: float
    fmt: tuple
    tag: str
    emphasis: str
    done: bool


def freeze(note: Note) -> State:
    return State(note.text, note.created,
                 tuple(sorted((k, _hashable(v)) for k, v in note.fmt.items())),
                 note.tag, note.emphasis, note.done)


def _hashable(value):
    if isinstance(value, list):
        return tuple(_hashable(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hashable(v)) for k, v in value.items()))
    return value


def thaw(state: State) -> Note:
    return Note(text=state.text, created=state.created,
                fmt={k: _plain(v) for k, v in state.fmt},
                tag=state.tag, emphasis=state.emphasis, done=state.done)


def _plain(value):
    if isinstance(value, tuple):
        if value and all(isinstance(v, tuple) and len(v) == 2
                         and isinstance(v[0], str) for v in value):
            return {k: _plain(v) for k, v in value}
        return [_plain(v) for v in value]
    return value


class History:
    """Where the page has been, and where it was going before you undid it."""

    def __init__(self, limit: int = LIMIT) -> None:
        self.limit = max(1, limit)
        self._past: list = []
        self._future: list = []
        self._now: tuple | None = None
        self._known: dict = {}          # the interning table

    # --- recording --------------------------------------------------------
    def _snapshot(self, notes) -> tuple:
        out = []
        for note in notes:
            state = freeze(note)
            out.append(self._known.setdefault(state, state))
        return tuple(out)

    def record(self, notes) -> bool:
        """Remember the page as it is now. False if nothing changed."""
        snapshot = self._snapshot(notes)
        if snapshot == self._now:
            return False
        if self._now is not None:
            self._past.append(self._now)
            if len(self._past) > self.limit:
                del self._past[:len(self._past) - self.limit]
        self._now = snapshot
        self._future.clear()
        return True

    def merge_last(self) -> None:
        """Fold the step just recorded into the one before it.

        Some single gestures change the page twice -- splitting a note edits
        one and adds another -- and undo should take back the gesture, not
        half of it.
        """
        if self._past:
            self._past.pop()

    # --- moving through it ------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return bool(self._past)

    @property
    def can_redo(self) -> bool:
        return bool(self._future)

    @property
    def depth(self) -> int:
        return len(self._past)

    def undo(self):
        """The page as it was one step ago, as fresh notes -- or None."""
        if not self._past:
            return None
        self._future.append(self._now)
        self._now = self._past.pop()
        return [thaw(state) for state in self._now]

    def redo(self):
        if not self._future:
            return None
        self._past.append(self._now)
        self._now = self._future.pop()
        return [thaw(state) for state in self._now]
