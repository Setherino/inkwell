"""Lay the notes out as one document.

This is the formatter. It looks at the notes *together* -- which is what
makes it a document rather than a list of styled strings:

* nesting: an indented note, or one the model says continues the last one,
  is set one level in, with a marker that matches its depth
* runs: consecutive list items, checkboxes or key/value pairs are packed
  tightly against each other and numbered as a sequence
* columns: a run of ``key: value`` notes shares one key column, with dot
  leaders out to the values
* hanging indents: wrapped lines align under the text, never under the
  marker
* rhythm: a blank line between blocks, an extra one above a section, none
  inside a run

Widths are decided here too, so the same document re-lays itself at any
terminal size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import latex
from . import shaping as S
from . import typography as T

Row = list  # list[tuple[attr, str]] -- urwid markup for one screen line

MARKERS = ("•", "◦", "‣", "·")
LEADER = "·"

# A tag earns its place by naming something you cannot already read. These
# are the blocks worth labelling: a formula, a table, a grid, a listing.
FIGURES = (S.MATH, S.TABLE, S.CODE, S.PANES)
# ...and these name themselves already.
NEVER_TAGGED = (S.TITLE, S.SECTION, S.HEAD, S.RULE)


def _mentions(text: str, word: str) -> bool:
    """Is the tag already there in the note's own words?"""
    if not word:
        return False
    stem = word.rstrip("s")
    return any(part.strip(".,:;()[[]'\"").lower().rstrip("s") == stem
               for part in text.split())


def _is_number(cell: str) -> bool:
    try:
        float(cell.strip().rstrip("%"))
    except ValueError:
        return False
    return True


def _clip(text: str, width: int) -> list:
    """Break a verbatim line into screen-width pieces, spaces intact."""
    if T.cols(text) <= width:
        return [text]
    return [text[i:i + width] for i in range(0, len(text), width)]


def cells(row: str) -> list:
    """Split a table row on its pipes."""
    return [c.strip() for c in row.strip().strip("|").split("|")]

ATTRS = {
    S.PARA: "body", S.ITEM: "body", S.CHECK: "check", S.KV: "kv_value",
    S.QUOTE: "quote", S.CODE: "code", S.CALLOUT: "callout",
    S.HEAD: "head", S.SECTION: "section", S.TITLE: "title",
    S.MATH: "math", S.TERM: "term_body", S.TABLE: "body", S.RULE: "rule",
    S.ASK: "ask",
}


@dataclass
class Block:
    note: object
    shape: S.Shape
    kind: str
    level: int = 0
    items: list = field(default_factory=list)   # a note formatted as a list
    key: str = ""
    value: str = ""
    number: int = 0
    number_width: int = 1
    lettered: bool = False
    key_width: int = 0
    value_width: int = 0
    columns: list = field(default_factory=list)   # table run: column widths
    numeric_columns: list = field(default_factory=list)
    pane_weights: list = field(default_factory=list)  # panes run: shared widths
    header: bool = False                          # first row of a table run
    numeric: bool = False       # every value in the run starts with a digit
    tag: str = ""
    tight_after: bool = False
    first: bool = False
    last: bool = False
    gap_before: int = 0        # blank lines above this block
    show_stamp: bool = True    # only the first note of each minute is stamped


@dataclass
class Layout:
    rows: list = field(default_factory=list)
    big: Optional[tuple] = None      # (font size, lines) for a large title
    blank_before: int = 0
    blank_after: int = 1
    align: str = "left"
    panes: list = field(default_factory=list)   # [(width, rows)] side by side
    indent: int = 0                             # where the text column starts
    measure: int = 0


MIN_PANE = 14        # narrower than this and panes stack instead


def indent_unit(maxcol: int) -> int:
    """Nesting costs columns, so it gets cheaper as the terminal narrows."""
    return 2 if maxcol >= 50 else 1 if maxcol >= 30 else 0


class Document:
    """The notes, formatted together. Rebuilt whenever a note changes."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self._by_note: dict[int, Block] = {}
        self.rev = 0

    # --- structure --------------------------------------------------------
    def rebuild(self, notes) -> None:
        blocks: list[Block] = []
        for i, note in enumerate(notes):
            shape = S.classify(note.text)
            kind, level = shape.kind, shape.level
            key, value, items = shape.key, shape.value, []
            fmt = getattr(note, "fmt", None) or {}

            if not shape.explicit and fmt:
                # The model formats only what the user left unmarked.
                if fmt.get("block") in S.FORMATTABLE:
                    kind = fmt["block"]
                if fmt.get("level"):
                    level = min(S.MAX_LEVEL, int(fmt["level"]))
                if fmt.get("continues") and blocks:
                    level = max(level, min(S.MAX_LEVEL, blocks[-1].level + 1))
                if kind == S.KV:
                    key = fmt.get("key") or key
                    value = fmt.get("value") or value
                    if not (key and value):
                        pair = S._KV_RE.match(shape.text)
                        key, value = (pair.group(1), pair.group(2)) if pair else ("", "")
                    if not (key and value):
                        kind = S.PARA
                if kind in (S.ITEM, S.CHECK):
                    items = [x for x in (fmt.get("items") or [])
                             if isinstance(x, str) and x.strip()][:12]

            if i == 0 and kind in (S.HEAD, S.SECTION):
                kind = S.TITLE          # the first heading names the document
            if kind == S.TITLE and i:
                kind = S.SECTION        # only one title, at the top

            blocks.append(Block(note=note, shape=shape, kind=kind, level=level,
                                items=items, key=key, value=value,
                                first=i == 0))

        self._number(blocks)
        self._align_keys(blocks)
        self._align_tables(blocks)
        self._align_panes(blocks)
        self._pack(blocks)          # runs first: tags need to know about them
        self._place_tags(blocks)
        self.blocks = blocks
        self._by_note = {id(b.note): b for b in blocks}
        self.rev += 1

    @staticmethod
    def _runs(blocks, kinds):
        """Yield index ranges of consecutive same-kind, same-level blocks."""
        start = 0
        while start < len(blocks):
            block = blocks[start]
            if block.kind not in kinds:
                start += 1
                continue
            end = start + 1
            while (end < len(blocks) and blocks[end].kind == block.kind
                   and blocks[end].level == block.level):
                end += 1
            yield start, end
            start = end

    @staticmethod
    def _number(blocks) -> None:
        """Number each level's items in sequence.

        A numbered list keeps counting past its own sub-items: 1., 2. with
        bullets in between is still 1., 2.
        """
        runs: dict = {}
        for block in blocks:
            if block.kind not in (S.ITEM, S.CHECK):
                if block.kind not in S.LIST_KINDS:
                    runs.clear()          # anything else ends the list
                continue
            for level in [k for k in runs if k > block.level]:
                del runs[level]           # a shallower item closes deeper ones
            if block.kind != S.ITEM:
                continue
            run = runs.setdefault(block.level, [])
            if run and run[0].shape.lettered != block.shape.lettered:
                run = runs[block.level] = []
            run.append(block)
            if not run[0].shape.numbered:
                continue
            # A list that starts at 2 stays starting at 2: the numbers you
            # typed set where the run begins, the run only keeps counting.
            first = run[0].shape.start or 1
            block.number = first + len(run) - 1
            block.lettered = block.shape.lettered or run[0].shape.lettered
            for member in run:
                member.number_width = len(str(first + len(run) - 1))

    def _align_keys(self, blocks) -> None:
        """A run of key/value notes shares one key column and one value column."""
        for start, end in self._runs(blocks, (S.KV,)):
            run = blocks[start:end]
            keys = max(T.cols(b.key) for b in run)
            values = max(T.cols(b.value) for b in run)
            # Numbers line up on their right edge; words on their left.
            numeric = all(b.value[:1].isdigit() for b in run)
            for block in run:
                block.key_width, block.value_width = keys, values
                block.numeric = numeric

    def _align_tables(self, blocks) -> None:
        """A run of pipe-separated notes becomes one table with a header."""
        for start, end in self._runs(blocks, (S.TABLE,)):
            run = blocks[start:end]
            grids = [cells(b.shape.text) for b in run]
            count = max(len(g) for g in grids)
            widths = [max((T.cols(g[c]) for g in grids if c < len(g)), default=0)
                      for c in range(count)]
            # Alignment is a property of the column, not of each cell, or a
            # column of numbers goes ragged the moment one is negative.
            body = grids[1:] if len(run) > 1 else grids
            numeric = [bool(body) and all(_is_number(g[c])
                                          for g in body if c < len(g))
                       for c in range(count)]
            for i, block in enumerate(run):
                block.columns = widths
                block.numeric_columns = numeric
                block.header = i == 0 and len(run) > 1

    def _align_panes(self, blocks) -> None:
        """Stacked pane rows line their dividers up: a run of them is a grid."""
        for start, end in self._runs(blocks, (S.PANES,)):
            run = blocks[start:end]
            counts = {len(S.panes(b.shape.text)) for b in run}
            if len(counts) != 1:
                continue
            columns = counts.pop()
            weights = [max(S.panes(b.shape.text)[c][0] for b in run)
                       for c in range(columns)]
            for i, block in enumerate(run):
                block.pane_weights = weights
                block.header = i == 0 and len(run) > 1

    @staticmethod
    def _place_tags(blocks) -> None:
        """Put each tag on the thing it actually names.

        A line that introduces a figure -- "the matrix below is orthonormal"
        -- is tagged with a word from its own sentence, which tells the
        reader nothing: the label belongs on the matrix. So a tag that
        merely repeats the note's own words moves down onto the figure it
        was pointing at, and is dropped if there is nothing to move it to.
        """
        for block in blocks:
            block.tag = (getattr(block.note, "tag", "") or "").strip()
        for i, block in enumerate(blocks):
            if not block.tag:
                continue
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            redundant = (block.kind in NEVER_TAGGED
                         or _mentions(block.shape.text, block.tag))
            if not redundant:
                continue
            if nxt is not None and nxt.kind in FIGURES and not nxt.tag:
                nxt.tag, block.tag = block.tag, ""
            else:
                block.tag = ""
        # A tag draws its own line, so it cannot sit inside a run -- it would
        # split the block it is labelling. Push it to the end of the run.
        for i, block in enumerate(blocks):
            if not block.tag or not block.tight_after:
                continue
            last = i
            while last + 1 < len(blocks) and blocks[last].tight_after:
                last += 1
            if not blocks[last].tag:
                blocks[last].tag, block.tag = block.tag, ""
            else:
                block.tag = ""

    @staticmethod
    def _pack(blocks) -> None:
        """Decide the blank lines. A list is one tight block, sub-items
        included; a section gets air above it; everything else gets one
        line. All the spacing is owned by *gap_before*, so gaps can never
        stack up into a hole."""
        for block, nxt in zip(blocks, blocks[1:]):
            block.tight_after = (block.kind in S.LIST_KINDS
                                 and nxt.kind == block.kind)
        for i, block in enumerate(blocks):
            block.last = i == len(blocks) - 1
            previous = blocks[i - 1] if i else None
            if previous is None:
                block.gap_before = 0
            elif previous.tight_after:
                block.gap_before = 0
            elif block.kind == S.SECTION:
                block.gap_before = 1 if previous.kind == S.TITLE else 2
            else:
                block.gap_before = 1
            stamp = block.note.stamp()
            block.show_stamp = previous is None or previous.note.stamp() != stamp

    def block_for(self, note) -> Optional[Block]:
        return self._by_note.get(id(note))

    # --- layout -----------------------------------------------------------
    def plan(self, note, maxcol: int, *, maxrow: int = 24, unicode_ok: bool = True,
             big: bool = True, stamps: bool = True) -> Layout:
        block = self.block_for(note)
        if block is None:                      # a note we have not seen yet
            self.rebuild([note])
            block = self.block_for(note)

        maxcol = max(8, maxcol)
        measure, offset = T.column(maxcol)
        unit = indent_unit(maxcol)
        indent = offset + block.level * unit
        avail = max(6, measure - block.level * unit)
        text = self._text(block, unicode_ok)
        kind = block.kind
        out = Layout(blank_before=block.gap_before,
                     blank_after=1 if block.last else 0)

        if kind == S.TITLE:
            return self._title(block, text, out, maxcol, measure, offset,
                               maxrow, unicode_ok, big)
        if kind == S.SECTION:
            body = T.transform("smallcaps", text, unicode_ok=unicode_ok)
            out.rows = self._flow("", None, body, "section", avail, indent)
            out.rows.append([(None, " " * indent), ("rule", "─" * avail)])
            return out
        if kind == S.HEAD:
            body = T.transform("bold", text, unicode_ok=unicode_ok)
            out.rows = self._flow("", None, body, "head", avail, indent)
            return out
        out.indent, out.measure = indent, measure
        if kind == S.PANES:
            self._panes(block, out, avail, indent, unicode_ok)
            self._label(block, out, maxcol, indent + 2)
            return out
        if kind == S.RULE:
            out.rows = [[(None, " " * indent), ("rule", "─" * avail)]]
            return out
        if kind == S.MATH:
            self._math(block, out, measure, offset, unicode_ok)
            self._label(block, out, maxcol, offset, align="center",
                        measure=measure)
            return out
        if kind == S.TABLE:
            out.rows = self._table(block, avail, indent, unicode_ok)
        elif kind == S.TERM:
            out.rows = self._term(block, avail, indent, unit, unicode_ok)
        elif kind == S.KV:
            out.rows = self._kv(block, out, avail, indent, unit, unicode_ok)
        elif kind == S.CHECK:
            attr = "check_done" if (block.shape.done or note.done) else "check"
            mark = "☑ " if (block.shape.done or note.done) else "☐ "
            out.rows = self._list(block, text, mark, "marker", attr, avail, indent)
        elif kind == S.ITEM:
            if block.number and block.lettered:
                mark = f"({chr(ord('a') + block.number - 1)}) "
            elif block.number:
                mark = f"{block.number}.".rjust(block.number_width + 1) + " "
            else:
                mark = MARKERS[min(block.level, 3)] + " "
            out.rows = self._list(block, text, mark, "marker", "body", avail, indent)
        elif kind == S.ASK:
            out.rows = self._flow("? ", "ask_mark", text, "ask", avail, indent)
        elif kind == S.QUOTE:
            body = T.transform("italic", text, unicode_ok=unicode_ok)
            out.rows = self._flow("│ ", "rule", body, "quote", avail, indent,
                                  repeat=True)
        elif kind == S.CODE:
            # Verbatim means verbatim: keep the spacing, do not re-wrap words.
            body = T.transform("mono", block.shape.text, unicode_ok=unicode_ok)
            out.rows = [[(None, " " * indent), ("rule", "▏ "), ("code", line)]
                        for line in _clip(body, max(4, avail - 2))]
        elif kind == S.CALLOUT:
            body = T.transform("bold", text, unicode_ok=unicode_ok)
            out.rows = self._flow("▍ ", "callout_bar", body, "callout", avail,
                                  indent, repeat=True)
        else:
            out.rows = self._flow("", None, text, "body", avail, indent)

        if stamps and maxcol >= 74 and out.rows and block.show_stamp:
            self._stamp(out.rows[0], maxcol, note.stamp())
        self._label(block, out, maxcol, indent + 2)
        return out

    # --- pieces -----------------------------------------------------------
    @staticmethod
    def _math_or_text(raw: str, unicode_ok: bool) -> str:
        """A value that is nothing but maths gets typeset as maths."""
        body = raw.strip()
        if len(body) > 2 and body.startswith("$") and body.endswith("$"):
            return latex.inline(body.strip("$"))
        return T.inline(latex.substitute(body), unicode_ok=unicode_ok)

    def _prose(self, raw: str, block: Block, unicode_ok: bool) -> str:
        """Inline maths, then inline markup, then the model's emphasis."""
        text = T.inline(latex.substitute(raw), unicode_ok=unicode_ok)
        emphasis = getattr(block.note, "emphasis", "")
        if emphasis and block.kind in (S.PARA, S.ITEM, S.CHECK, S.QUOTE, S.TERM):
            text = T.emphasise(text, emphasis, unicode_ok=unicode_ok)
        return text

    def _text(self, block: Block, unicode_ok: bool) -> str:
        text = T.inline(latex.substitute(block.shape.text), unicode_ok=unicode_ok)
        emphasis = getattr(block.note, "emphasis", "")
        if emphasis and block.kind in (S.PARA, S.ITEM, S.CHECK, S.QUOTE):
            text = T.emphasise(text, emphasis, unicode_ok=unicode_ok)
        return text

    @staticmethod
    def _flow(marker: str, marker_attr: str, text: str, attr: str,
              avail: int, indent: int, repeat: bool = False) -> list[Row]:
        """One paragraph: marker on the first line, hanging indent after.

        A newline inside the note is a break the writer asked for, so it is
        kept: each piece wraps on its own, under the same hanging indent.
        """
        hang = T.cols(marker)
        rows: list[Row] = []
        for piece in text.split("\n"):
            for line in T.wrap(piece, max(4, avail - hang)):
                head = ((marker_attr or None, marker) if repeat or not rows
                        else (None, " " * hang))
                rows.append([(None, " " * indent), head, (attr, line)])
        return rows

    def _list(self, block: Block, text: str, mark: str, mark_attr: str,
              attr: str, avail: int, indent: int) -> list[Row]:
        """A list item -- or several, when the model split the note up."""
        pieces = block.items or [text]
        rows: list[Row] = []
        for piece in pieces:
            rows += self._flow(mark, mark_attr, piece, attr, avail, indent)
        return rows

    def _kv(self, block: Block, out: Layout, avail: int, indent: int,
            unit: int, unicode_ok: bool) -> list[Row]:
        """A key/value pair, aligned with the rest of its run.

        Key column, a short run of dot leaders, then the value column. The
        whole run makes the same call, so the table never goes ragged: if the
        columns cannot fit, every row in the run stacks instead.
        """
        key = T.inline(latex.substitute(block.key), unicode_ok=unicode_ok)
        value = self._math_or_text(block.value, unicode_ok)
        keys = max(block.key_width, T.cols(key))
        values = max(block.value_width, T.cols(value))
        table = min(avail, keys + values + 14)
        leaders = table - keys - values - 2
        if leaders >= 1 and keys <= max(8, avail // 2):
            shown = value.rjust(values) if block.numeric else value
            return [[(None, " " * indent), ("kv_key", key.ljust(keys)),
                     ("leader", " " + LEADER * leaders + " "),
                     ("kv_value", shown)]]
        # Too narrow for two columns: put the value under its key.
        rows = [[(None, " " * indent), ("kv_key", key)]]
        rows += self._flow("", None, value, "kv_value", max(6, avail - unit),
                           indent + max(1, unit))
        return rows

    def _math(self, block: Block, out: Layout, measure: int, offset: int,
              unicode_ok: bool) -> Layout:
        """Display maths: typeset, then centred in the text column."""
        lines = latex.display(block.shape.text)
        if max((T.cols(x) for x in lines), default=0) > measure:
            # Too wide to stack: fall back to the one-line form, wrapped if
            # even that will not fit.
            lines = T.wrap(latex.inline(block.shape.text), measure)
        # Centre the block as one piece: line by line would shear the rows
        # of a matrix out of alignment with each other.
        widest = max((T.cols(line) for line in lines), default=0)
        pad = offset + max(0, (measure - widest) // 2)
        for line in lines:
            out.rows.append([(None, " " * pad), ("math", line)])
        return out

    def _table(self, block: Block, avail: int, indent: int,
               unicode_ok: bool) -> list[Row]:
        """One row of a table, in the column widths its run agreed on."""
        values = cells(block.shape.text)
        widths = list(block.columns) or [T.cols(v) for v in values]
        room = avail - 2 * (len(widths) - 1)
        while sum(widths) > room and max(widths) > 4:
            widths[widths.index(max(widths))] -= 1
        pieces: list = [(None, " " * indent)]
        attr = "table_head" if block.header else "body"
        for i, width in enumerate(widths):
            value = self._math_or_text(values[i] if i < len(values) else "",
                                       unicode_ok)
            if T.cols(value) > width:
                value = value[:max(1, width - 1)] + "…"
            numeric = (block.numeric_columns[i]
                       if i < len(block.numeric_columns) else False)
            pieces.append((attr, value.rjust(width) if numeric
                           else value.ljust(width)))
            if i < len(widths) - 1:
                pieces.append(("leader", "  "))
        rows = [pieces]
        if block.header:
            rows.append([(None, " " * indent),
                         ("rule", "─" * min(avail, sum(widths)
                                            + 2 * (len(widths) - 1)))])
        return rows

    def _term(self, block: Block, avail: int, indent: int, unit: int,
              unicode_ok: bool) -> list[Row]:
        """A definition: the term, an em dash, then what it means."""
        term = T.transform("bold",
                           T.inline(latex.substitute(block.shape.key),
                                    unicode_ok=unicode_ok),
                           unicode_ok=unicode_ok)
        body = self._prose(block.shape.value, block, unicode_ok)
        gap = " — "
        head = T.cols(term) + len(gap)
        if head < avail // 2:
            lines = T.wrap(body, max(6, avail - head))
            rows = [[(None, " " * indent), ("term", term), ("leader", gap),
                     ("term_body", lines[0])]]
            rows += [[(None, " " * (indent + head)), ("term_body", line)]
                     for line in lines[1:]]
            return rows
        rows = [[(None, " " * indent), ("term", term)]]
        rows += self._flow("", None, body, "term_body", max(6, avail - unit),
                           indent + max(1, unit))
        return rows

    def _panes(self, block: Block, out: Layout, avail: int, indent: int,
               unicode_ok: bool) -> Layout:
        """Boxes side by side: equal by default, ``{2}`` for a wider one.

        Below a usable pane width they stack instead of squeezing -- the same
        call a page of CSS columns has to make.
        """
        parts = S.panes(block.shape.text)
        if len(block.pane_weights) == len(parts):
            parts = [(w, text) for w, (_old, text) in
                     zip(block.pane_weights, parts)]
        gap = 2                       # "│ " drawn inside each pane but the first
        total = sum(w for w, _t in parts)
        room = avail - gap * (len(parts) - 1)
        widths = [max(1, int(room * w / total)) for w, _t in parts]
        widths[-1] += room - sum(widths)

        if len(parts) > 1 and min(widths) >= MIN_PANE:
            for i, ((_weight, text), width) in enumerate(zip(parts, widths)):
                rows = self._pane_rows(text, width, unicode_ok,
                                       header=block.header)
                if i:
                    rows = [[("rule", "│ ")] + row for row in rows]
                    width += gap
                out.panes.append((width, rows))
            height = max(len(rows) for _w, rows in out.panes)
            centred = []
            for w, rows in out.panes:
                spare = height - len(rows)
                above = spare // 2
                centred.append((w, [[]] * above + rows
                                + [[]] * (spare - above)))
            out.panes = centred
            out.rows = self._merge(out.panes, indent)
            return out

        # Stacked: each pane becomes its own paragraph, kept together.
        for i, (_weight, text) in enumerate(parts):
            if not text.strip():
                continue
            rows = self._pane_rows(text, max(6, avail - 2), unicode_ok)
            out.rows += [[(None, " " * indent), ("rule", "▏ ")] + row
                         for row in rows]
        return out

    def _pane_rows(self, text: str, width: int, unicode_ok: bool,
                   header: bool = False) -> list[Row]:
        """One pane's content, formatted in its own little column."""
        shape = S.classify(text)
        body = T.inline(latex.substitute(shape.text), unicode_ok=unicode_ok)
        # Everything in a pane is short, so "short means heading" would make
        # the whole grid bold. Only honour a heading the writer marked.
        if header or (shape.kind in (S.TITLE, S.SECTION, S.HEAD) and shape.explicit):
            body = T.transform("bold", body, unicode_ok=unicode_ok)
            attr, marker = ("table_head", "")
        elif shape.kind in (S.TITLE, S.SECTION, S.HEAD):
            attr, marker = ("body", "")
        elif shape.kind == S.CHECK:
            attr, marker = ("check", "☑ " if shape.done else "☐ ")
        elif shape.kind == S.ITEM:
            attr, marker = ("body", MARKERS[0] + " ")
        elif shape.kind == S.QUOTE:
            body = T.transform("italic", body, unicode_ok=unicode_ok)
            attr, marker = ("quote", "")
        elif shape.kind == S.CODE:
            body = T.transform("mono", body, unicode_ok=unicode_ok)
            attr, marker = ("code", "")
        elif shape.kind == S.MATH:
            lines = latex.display(shape.text)
            if max((T.cols(x) for x in lines), default=0) > width:
                lines = T.wrap(latex.inline(shape.text), width)
            return [[("math", line)] for line in lines]
        else:
            attr, marker = ("body", "")
        hang = len(marker)
        rows: list[Row] = []
        for i, line in enumerate(T.wrap(body, max(2, width - hang))):
            head = ("marker", marker) if i == 0 and marker else (None, " " * hang)
            rows.append([head, (attr, line)])
        return rows

    @staticmethod
    def _merge(panes: list, indent: int) -> list[Row]:
        """Flatten side-by-side panes into screen rows."""
        height = max(len(rows) for _w, rows in panes)
        merged: list[Row] = []
        for i in range(height):
            row: Row = [(None, " " * indent)]
            for width, rows in panes:
                cells = rows[i] if i < len(rows) else []
                used = sum(T.cols(text) for _attr, text in cells)
                row += cells
                if width - used > 0:
                    row.append((None, " " * (width - used)))
            merged.append(row)
        return merged

    def _title(self, block, text, out, maxcol, measure, offset, maxrow,
               unicode_ok, big) -> Layout:
        fitted = T.title_font(text, measure, maxrow) if big else None
        if fitted:
            out.big, out.align = fitted, "center"
            return out
        body = T.transform("bold", text, unicode_ok=unicode_ok)
        lines = T.wrap(body, measure)
        for line in lines:
            pad = offset + max(0, (measure - T.cols(line)) // 2)
            out.rows.append([(None, " " * pad), ("title", line)])
        rule = min(measure, max(T.cols(x) for x in lines) + 4)
        out.rows.append([(None, " " * (offset + (measure - rule) // 2)),
                         ("rule", "━" * rule)])
        return out

    @staticmethod
    def _label(block: Block, out: Layout, maxcol: int, indent: int,
               align: str = "left", measure: int = 0) -> None:
        """The little grey word under a block, when there is room for it."""
        if not block.tag or maxcol < 60 or not out.rows:
            return
        pad = indent
        if align == "center" and measure:
            pad = indent + max(0, (measure - T.cols(block.tag)) // 2)
        out.rows.append([(None, " " * pad), ("tag", block.tag)])

    @staticmethod
    def _stamp(row: Row, maxcol: int, stamp: str) -> None:
        used = sum(T.cols(text) for _attr, text in row)
        pad = maxcol - used - T.cols(stamp) - 1
        if pad >= 2:
            row.append((None, " " * pad))
            row.append(("meta", stamp))
