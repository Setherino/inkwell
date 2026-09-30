"""A small LaTeX-to-terminal math typesetter.

Real math is two-dimensional, so this is a box model rather than a string
substitution: every fragment is a ``Box`` (some lines plus the index of its
baseline), and boxes are glued together with their baselines aligned. That
is what makes ``\\frac`` stack, ``\\sum`` carry its limits above and below,
and ``\\begin{bmatrix}`` come out square.

Two modes:

* **inline** (``$...$`` inside a sentence) is forced onto one line -- unicode
  super/subscripts, and a ``∕`` fraction where both halves are digits --
  because prose has to keep flowing
* **display** (``$$...$$`` on its own) may use as many rows as it likes

Anything it cannot read is passed through unchanged rather than mangled.

Scripts
-------

Unicode's super/subscript coverage is patchy, so a script that has no unicode
form has to be said another way. It is never said with a bare ``^`` or ``_``:
those are the writer's source, not typesetting, and on the page they read as a
mistake. Instead:

* the script is wrapped in tiny parentheses beside its base: ``⁽ ⁾`` for a
  superscript, ``₍ ₎`` for a subscript -- ``k₍B₎``, ``w₍i,j₎ᵏ``, ``e⁽iπ⁾``.
  The delimiters are the size cue; the content stays full size and therefore
  stays readable. Display does this too, and gets the same answer inline
  would.
* **only a base that takes limits** grows rows for them: ``\sum``, ``\int``,
  the ``\lim``-like words, and an already-tall base such as a bracketed
  matrix. Display used to park *any* unshrinkable script on its own row, which
  reads well alone and badly in company: the row above a fraction holds the
  numerators and the row below holds the denominators, so
  ``\frac{r\dot\phi_L}{2}`` left a lone ``L`` sitting over the rule with
  nothing to say whose it was.

Word-like scripts stay in full-size letters on purpose (see ``scriptify``), and
if any script of a given kind in an expression has no unicode form then none of
them use one -- half-typeset scripts look like a bug.

Prescripts
----------

``^A_B R`` -- a superscript and a subscript that *precede* their base -- is the
core notation of robot kinematics (the transform from frame B to frame A).
Display sets it as a genuine pre-script box, the two letters right-aligned in a
column tight against the base::

    A
     R
    B

Inline it is written ``⁽ᴬ⁾₍B₎R``: the scripts keep their source order relative
to the base, and a prescript is **always** parenthesised -- even when a bare
modifier letter exists -- so that ``Rᴮ`` (B is R's superscript) cannot be
confused with ``⁽ᴮ⁾P`` (B is P's prescript).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ",
    "Omega": "Ω",
}

SYMBOLS = {
    "sum": "∑", "prod": "∏", "int": "∫", "iint": "∬", "oint": "∮",
    "bigcup": "⋃", "bigcap": "⋂", "partial": "∂", "nabla": "∇",
    "infty": "∞", "pm": "±", "mp": "∓", "times": "×", "div": "÷",
    "cdot": "⋅", "ast": "∗", "star": "⋆", "circ": "∘", "bullet": "∙",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼", "simeq": "≃", "cong": "≅",
    "propto": "∝", "ll": "≪", "gg": "≫", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "in": "∈", "notin": "∉", "ni": "∋",
    "cup": "∪", "cap": "∩", "setminus": "∖", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "nexists": "∄", "neg": "¬", "lnot": "¬",
    "land": "∧", "wedge": "∧", "lor": "∨", "vee": "∨", "oplus": "⊕",
    "otimes": "⊗", "to": "→", "rightarrow": "→", "leftarrow": "←",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔",
    "Leftrightarrow": "⇔", "mapsto": "↦", "implies": "⟹", "iff": "⟺",
    "uparrow": "↑", "downarrow": "↓", "angle": "∠", "perp": "⊥",
    "parallel": "∥", "prime": "′", "hbar": "ℏ", "ell": "ℓ", "Re": "ℜ",
    "Im": "ℑ", "aleph": "ℵ", "degree": "°", "deg": "°", "dots": "…",
    "ldots": "…", "cdots": "⋯", "vdots": ":", "ddots": "·", "surd": "√",
    "checkmark": "✓", "therefore": "∴", "because": "∵", "top": "T",
    "bot": "⊥", "models": "⊨", "vdash": "⊢", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋", "langle": "⟨", "rangle": "⟩",
    "Diamond": "◇", "diamond": "⋄", "rightrightarrows": "⇉",
    "leftleftarrows": "⇇", "rightleftarrows": "⇄", "square": "□",
}

FUNCTIONS = ("sin", "cos", "tan", "sec", "csc", "cot", "arcsin", "arccos",
             "arctan", "sinh", "cosh", "tanh", "log", "ln", "exp", "lim",
             "max", "min", "sup", "inf", "det", "dim", "ker", "gcd", "arg",
             "mod", "Pr")

SPACES = {"quad": "  ", "qquad": "    ", ",": " ", ";": " ", ":": " ",
          "!": "", " ": " ", "enskip": " ", "enspace": " ",
          "thinspace": " ", "medspace": " ", "thickspace": " "}

# Commands that say something about *style*, not about the math. They leave
# nothing on the page.
NOOPS = {"displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle",
         "limits", "nolimits", "hline", "centering", "noalign", "protect",
         "nonumber", "notag"}
# The same, but followed by a length assignment ("\\arraycolsep=2pt") that has
# to be swallowed with them.
DIMENS = {"arraycolsep", "arrayrulewidth", "tabcolsep", "arraystretch",
          "baselineskip", "abovedisplayskip", "belowdisplayskip"}
# A change of face is nothing a terminal can show, so these just render their
# argument -- but as math, not as raw text, or "\\boldsymbol{\\hat{x}}" would put
# braces on the page.
FONTS = ("mathbf", "bf", "boldsymbol", "mathit", "it", "mathsf", "mathnormal",
         "textbf", "textit", "textsl", "textsf", "texttt", "textnormal",
         "emph", "bm", "pmb")

ACCENTS = {"vec": "⃗", "hat": "̂", "bar": "̄", "tilde": "̃",
           "dot": "̇", "ddot": "̈", "overline": "̄",
           "check": "̌", "acute": "́", "grave": "̀"}
# A rule, not a point: it is drawn across everything under it.
WIDE_ACCENTS = {"overline"}

# Only the letters a monospace face actually carries. 𝔼, 𝔽 and 𝟙 live in the
# astral math planes, which Menlo -- the face inkwell/pdf.py draws with -- does
# not have, and a letter the reader can see beats one they cannot.
BLACKBOARD = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "P": "ℙ",
              "H": "ℍ"}

SUPERS = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
          "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "+": "⁺", "-": "⁻",
          "=": "⁼", "(": "⁽", ")": "⁾", "n": "ⁿ", "i": "ⁱ", "a": "ᵃ",
          "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ",
          "h": "ʰ", "j": "ʲ", "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "o": "ᵒ",
          "p": "ᵖ", "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ",
          "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ", "T": "ᵀ", "*": "*"}
# The U+1D2C block. Note the gaps: there is no modifier capital C, F, Q, S, X,
# Y or Z, so a superscript capital is only sometimes available -- which is what
# the "all or none" rule in Parser.plain is for.
SUPER_CAPS = {"A": "ᴬ", "B": "ᴮ", "D": "ᴰ", "E": "ᴱ", "G": "ᴳ", "H": "ᴴ",
              "I": "ᴵ", "J": "ᴶ", "K": "ᴷ", "L": "ᴸ", "M": "ᴹ", "N": "ᴺ",
              "O": "ᴼ", "P": "ᴾ", "R": "ᴿ", "T": "ᵀ", "U": "ᵁ", "V": "ⱽ",
              "W": "ᵂ"}
SUPERS.update(SUPER_CAPS)

# Unicode has no subscript capitals at all, and only some lowercase ones, so a
# script that cannot be set in tiny letters is marked by tiny brackets instead.
SUP_PAREN = ("⁽", "⁾")
SUB_PAREN = ("₍", "₎")

SUBS = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅",
        "6": "₆", "7": "₇", "8": "₈", "9": "₉", "+": "₊", "-": "₋",
        "=": "₌", "(": "₍", ")": "₎", "a": "ₐ", "e": "ₑ", "h": "ₕ",
        "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ", "m": "ₘ", "n": "ₙ",
        "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ",
        "v": "ᵥ", "x": "ₓ"}

# Tiny fractions are built only out of these. The 0-9 super/subscripts are a
# complete, evenly drawn set, so "¹∕₇" reads like the precomposed "½" beside
# it; the letter forms are patchy and small enough to misread.
DIGITS = frozenset("0123456789")
MAX_TINY = 3            # digits a side, past which tiny stops being legible


def _tiny_digits(text: str) -> bool:
    """ASCII 0-9 only, and few enough to stay readable when shrunk.

    Deliberately not ``str.isdigit()``: that is also true of "²" and "٣",
    and shrinking something already tiny is how "ʳ∕₂" happened.
    """
    return 0 < len(text) <= MAX_TINY and all(ch in DIGITS for ch in text)


VULGAR = {("1", "2"): "½", ("1", "3"): "⅓", ("2", "3"): "⅔", ("1", "4"): "¼",
          ("3", "4"): "¾", ("1", "5"): "⅕", ("1", "6"): "⅙", ("1", "8"): "⅛",
          ("3", "8"): "⅜", ("5", "8"): "⅝", ("7", "8"): "⅞"}

BIG_OPS = "∑∏∫∬∮⋃⋂"
# Operators written as words that still take their limits under them the way
# \sum does. Without these \lim would set "x → 0" beside "lim" instead.
LIMIT_WORDS = frozenset(("lim", "max", "min", "sup", "inf",
                         "argmax", "argmin", "limsup", "liminf"))
CLOSERS = set(")]}⟩⌉⌋|")
# Relations and binary operators keep the space the writer typed around them;
# a letter-like symbol (\Delta S -> ΔS) does not.
RELATIONS = set("=≤≥≠≈≡∼≃≅∝≪≫⊂⊆⊃⊇∈∉∋∪∩∖±∓×÷⋅∗⋆∘∙⊕⊗→←↔⇒⇐⇔↦∧∨⟹⟺∴∵⊨⊢")
BRACKETS = {"[": ("⎡", "⎢", "⎣"), "]": ("⎤", "⎥", "⎦"),
            "(": ("⎛", "⎜", "⎝"), ")": ("⎞", "⎟", "⎠"),
            "{": ("⎧", "⎨", "⎩"), "}": ("⎫", "⎬", "⎭"),
            "|": ("│", "│", "│")}


@dataclass
class Box:
    """Some lines and the index of the one everything else lines up with."""

    lines: list
    baseline: int = 0

    @property
    def width(self) -> int:
        return max((len(line) for line in self.lines), default=0)

    @property
    def height(self) -> int:
        return len(self.lines)

    def padded(self) -> "Box":
        width = self.width
        return Box([line.ljust(width) for line in self.lines], self.baseline)

    @staticmethod
    def text(value: str) -> "Box":
        return Box([value], 0)


def hcat(boxes: list) -> Box:
    """Glue boxes side by side, baselines aligned."""
    boxes = [b for b in boxes if b.height]
    if not boxes:
        return Box([""], 0)
    above = max(b.baseline for b in boxes)
    below = max(b.height - b.baseline for b in boxes)
    lines = [""] * (above + below)
    for box in boxes:
        box = box.padded()
        pad_top = above - box.baseline
        for i in range(above + below):
            source = i - pad_top
            piece = box.lines[source] if 0 <= source < box.height else " " * box.width
            lines[i] += piece
    return Box(lines, above)


def stack(over: Box, middle: Box, under: Box) -> Box:
    """Centre three boxes vertically -- limits, or a fraction."""
    width = max(over.width, middle.width, under.width)
    lines = ([line.center(width) for line in over.lines]
             + [line.center(width) for line in middle.lines]
             + [line.center(width) for line in under.lines])
    return Box(lines, over.height + middle.baseline)


def scriptify(text: str, table: dict) -> str | None:
    # A whole word in tiny letters is harder to read than "_word", and the
    # unicode coverage is patchy, so keep words plain and be consistent.
    if len(text) > 1 and text.isalpha():
        return None
    out = ""
    for ch in text:
        if ch not in table:
            return None
        out += table[ch]
    return out


# --- tokenizer --------------------------------------------------------------
_TOKEN = re.compile(r"\\[A-Za-z]+|\\.|[{}^_&]|\s+|[^\\{}^_&\s]")


def tokenize(src: str) -> list:
    return [t for t in _TOKEN.findall(src) if t.strip() or t == " "]


def _payload_text(token: str) -> str:
    """A token as it will actually be set, so coverage is judged on the glyph.

    "^\\top" ends up as a T, which has a superscript form; judging it on the
    letters "top" would wrongly condemn every superscript in the expression.
    """
    if not token.startswith("\\"):
        return token
    name = token[1:]
    return GREEK.get(name) or SYMBOLS.get(name) or name


def _script_payloads(tokens: list) -> list:
    """The text of every ^ or _ argument, so coverage can be judged up front."""
    out = []
    for i, token in enumerate(tokens):
        if token not in ("^", "_"):
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].isspace():
            j += 1
        if j >= len(tokens):
            continue
        if tokens[j] != "{":
            out.append((token, _payload_text(tokens[j])))
            continue
        depth, body = 1, ""
        j += 1
        while j < len(tokens) and depth:
            if tokens[j] == "{":
                depth += 1
            elif tokens[j] == "}":
                depth -= 1
                if not depth:
                    break
            body += _payload_text(tokens[j])
            j += 1
        out.append((token, body))
    return out


class Parser:
    def __init__(self, tokens: list, display: bool) -> None:
        self.tokens = tokens
        self.i = 0
        self.display = display
        self.depth = 0          # how deep inside a matrix or cases we are
        # Half-typeset scripts look like a mistake: "T_c/Tₕ" reads worse than
        # "T_c/T_h". So if any script in this expression has no unicode form,
        # none of them use one.
        self.plain = {"_": False, "^": False}
        for kind, payload in _script_payloads(tokens):
            # Only judge leaf scripts. A payload with its own scripts or
            # commands ("\int_{T_1}") is drawn as a box, not scripted, so it
            # says nothing about coverage.
            if not payload or any(c in payload for c in "_^{}"):
                continue
            table = SUBS if kind == "_" else SUPERS
            if scriptify(payload, table) is None:
                self.plain[kind] = True

    # --- helpers ----------------------------------------------------------
    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.i += 1
        return token

    def group(self) -> Box:
        """The next {...} group, or the next single atom."""
        while self.peek() is not None and self.peek().isspace():
            self.take()
        if self.peek() == "{":
            self.take()
            return self.run(stop="}")
        token = self.take()
        return self.atom(token) if token is not None else Box.text("")

    @staticmethod
    def _eats_space(token: str) -> bool:
        """LaTeX swallows the space after a command name -- but a relation
        wants to keep its breathing room."""
        if not token.startswith("\\") or len(token) <= 2:
            return False
        name = token[1:]
        if name in GREEK or name in FUNCTIONS or name in SPACES:
            return True
        return name in SYMBOLS and SYMBOLS[name] not in RELATIONS

    def _maybe_eat_space(self, token: str) -> None:
        """Drop the space after \Delta in "\Delta S", keep it in "\alpha + b"."""
        if not self._eats_space(token):
            return
        j = self.i
        while j < len(self.tokens) and self.tokens[j] == " ":
            j += 1
        nxt = self.tokens[j] if j < len(self.tokens) else ""
        operator = (nxt in "+-*/<>=|," or nxt in RELATIONS
                    or (nxt.startswith("\\")
                        and (nxt[1:] in FUNCTIONS
                             or (nxt[1:] in SYMBOLS
                                 and SYMBOLS[nxt[1:]] in RELATIONS))))
        if not operator:
            self.i = j

    @staticmethod
    def _despace(box: Box) -> Box:
        """A trailing space must not come between a base and its script."""
        if box.height == 1 and box.lines[0].endswith(" "):
            return Box.text(box.lines[0].rstrip())
        return box

    def run(self, stop=None, stop_at=()) -> Box:
        boxes: list = []
        while True:
            token = self.peek()
            if token is None:
                break
            if stop is not None and token == stop:
                self.take()
                break
            if token in stop_at:
                break
            self.take()
            if token == "{":
                boxes.append(self.run(stop="}"))
                continue
            if token in ("^", "_"):
                if boxes and _is_base(boxes[-1]):
                    boxes.append(self.script(self._despace(boxes.pop()), token))
                else:
                    boxes.append(self.prescript(token))
                continue
            box = self.atom(token)
            if (box.height == 1 and box.lines[0] in CLOSERS
                    and boxes and boxes[-1].lines == [" "]):
                boxes.pop()            # "⟨3, -1, 3 ⟩" -> "⟨3, -1, 3⟩"
            boxes.append(box)
            self._maybe_eat_space(token)
        return hcat(boxes) if boxes else Box.text("")

    # --- atoms ------------------------------------------------------------
    def atom(self, token: str) -> Box:
        # An author sometimes types these straight into the source. No
        # monospace face draws them, so keep the meaning, swap the glyph.
        if token.isspace():
            return Box.text(" ")
        if not token.startswith("\\"):
            return Box.text(token.translate(TYPED))

        name = token[1:]
        if name in SPACES:
            return Box.text(SPACES[name])
        if name in GREEK:
            return Box.text(GREEK[name])
        if name in SYMBOLS:
            return Box.text(SYMBOLS[name])
        if name in FUNCTIONS:
            return Box.text(name + " ")
        if name == "frac" or name == "dfrac" or name == "tfrac":
            # Read both halves one level deeper, exactly as a script's
            # argument is read: the fraction already owns the vertical, and a
            # numerator that stacks a subscript onto its own row puts that
            # letter among the other numerators on the line.
            self.depth += 1
            try:
                num, den = self.group(), self.group()
            finally:
                self.depth -= 1
            return self.frac(num, den)
        if name == "sqrt":
            return self.sqrt()
        if name in NOOPS:
            return Box.text("")
        if name in DIMENS:
            self._skip_dimen()
            return Box.text("")
        if name in FONTS:
            return self.group()
        if name == "overrightarrow":
            return self.over_arrow()
        # \mathcal and \mathscr set ordinary capitals: their script letters
        # (ℒ, 𝒪 ...) have no glyph in any monospace face, and a letter the
        # reader can see beats a box the font cannot fill.
        if name in ("text", "textrm", "mathrm", "operatorname", "mbox",
                    "mathcal", "mathscr"):
            return Box.text(self.raw_group())
        if name == "mathbb":
            return Box.text("".join(BLACKBOARD.get(c, c) for c in self.raw_group()))
        if name in ACCENTS:
            return self.accent(ACCENTS[name], whole=name in WIDE_ACCENTS)
        if name == "left":
            return self.fenced(self.take() or "")
        if name == "right":                 # unmatched: just the delimiter
            delim = self.take() or ""
            return Box.text("" if delim == "." else delim)
        if name == "begin":
            return self.environment(self.raw_group())
        if name == "end":
            self.raw_group()
            return Box.text("")
        if name == "\\" or name == "newline":
            return Box.text(" ")
        if len(name) == 1:                  # escaped punctuation: \% \& \$ \_
            return Box.text(name)
        # unknown: hand it back exactly as it was typed, braces and all
        return Box.text("\\" + name + self._verbatim_group())

    def raw_group(self) -> str:
        """The literal text of the next group, commands stripped."""
        while self.peek() is not None and self.peek().isspace():
            self.take()
        if self.peek() != "{":
            token = self.take() or ""
            return token.lstrip("\\")
        self.take()
        out = ""
        depth = 1
        while self.peek() is not None:
            token = self.take()
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                if not depth:
                    break
            out += token if not token.startswith("\\") else token[1:]
        return out

    def frac(self, num: Box, den: Box) -> Box:
        """A fraction: stacked over a rule where there is room for it.

        Not inside a matrix, though -- a cell three rows tall would drag the
        whole grid apart, so there a fraction stays on its line, full size.
        And the precomposed glyphs (⅔) are for inline prose only: at display
        size they come out tiny next to an ordinary letter.
        """
        if num.height == 1 and den.height == 1:
            top, bottom = num.lines[0].strip(), den.lines[0].strip()
            if self.depth:
                return Box.text(f"{_paren(top)}/{_paren(bottom)}")
            if not self.display:
                if (top, bottom) in VULGAR:
                    return Box.text(VULGAR[(top, bottom)])
                # Tiny only for plain digits -- see _tiny_digits. A letter set
                # small is the thing that made "ʳ∕₂" and "ᵃ⁺ᵇ∕₂" unreadable,
                # and a solidus with the loose side bracketed says the same
                # in glyphs the reader already knows.
                if _tiny_digits(top) and _tiny_digits(bottom):
                    up, down = scriptify(top, SUPERS), scriptify(bottom, SUBS)
                    if up and down:
                        return Box.text(f"{up}∕{down}")
                return Box.text(f"{_paren(top)}/{_paren(bottom)}")
        width = max(num.width, den.width) + 2
        return stack(num, Box.text("─" * width), den)

    def sqrt(self) -> Box:
        arg = self.group()
        if arg.height == 1 and len(arg.lines[0].strip()) == 1:
            return Box.text("√" + arg.lines[0].strip() + "̄")
        if not self.display:
            return Box.text("√(" + " ".join(x.strip() for x in arg.lines) + ")")
        arg = arg.padded()
        rule = "─" * (arg.width + 1)
        lines = ["  " + rule] + ["√ " + line for line in arg.lines]
        return Box(lines, arg.baseline + 1)

    def fenced(self, opening: str) -> Box:
        r"""``\left<d> ... \right<d>``: delimiters as tall as what they hold.

        A flat "[" printed beside a grown "⎡" is the giveaway that the
        delimiter was emitted as text instead of being sized, which is what
        the book's homogeneous transforms used to look like.
        """
        body = self.run(stop_at=("\\right",))
        closing = ""
        if self.peek() == "\\right":
            self.take()
            closing = self.take() or ""
        pieces = []
        if opening not in ("", "."):
            pieces.append(_fence(opening, body.height, body.baseline))
        pieces.append(body)
        if closing not in ("", "."):
            pieces.append(_fence(closing, body.height, body.baseline))
        return hcat(pieces)

    def accent(self, mark: str, whole: bool = False) -> Box:
        """A hat sits over one letter; a bar is drawn across the whole group.

        "\\hat{q_i}" is a hat on the q -- putting one on every glyph gives
        "q̂ᵢ̂", which reads as two accidents rather than one accent.
        """
        arg = self.group()
        if arg.height != 1:
            return arg
        text = arg.lines[0]
        if whole:
            return Box.text("".join(ch + mark for ch in text))
        if not text:
            return Box.text(mark)
        return Box.text(text[0] + mark + text[1:])

    def over_arrow(self) -> Box:
        """\\overrightarrow: a drawn arrow where there is a row for it."""
        arg = self.group()
        if self.display and not self.depth and arg.height == 1 and arg.width:
            rule = "─" * (arg.width - 1) + "→"
            return Box([rule, arg.lines[0]], 1)
        if arg.height != 1:
            return arg
        # One line, so there is no row to draw the arrow on. A combining arrow
        # would sit over one letter only -- wrong for "\\overrightarrow{AB}",
        # and Menlo cannot draw it either -- so the arrowhead trails instead.
        return Box.text(arg.lines[0] + "→")

    def _skip_dimen(self) -> None:
        """Swallow the "=2pt" of a length assignment."""
        while self.peek() == " ":
            self.take()
        if self.peek() == "=":
            self.take()
        while self.peek() is not None and (self.peek().isalnum()
                                           or self.peek() == "."):
            self.take()

    def _verbatim_group(self) -> str:
        """The source text of the next {...}, braces included."""
        if self.peek() != "{":
            return ""
        out, depth = "", 0
        while self.peek() is not None:
            token = self.take()
            out += token
            if token == "{":
                depth += 1
            elif token == "}":
                depth -= 1
                if not depth:
                    break
        return out

    def _scripts(self, kind: str):
        """Read a ^/_ argument, and its partner if the writer gave one.

        The arguments are read one level deeper, so a tall construct inside a
        script (a \\frac in an exponent) comes back as a linear "a/b" instead
        of a stack of rule characters that the script cannot hold.
        """
        self.depth += 1
        try:
            first = self.group()
            second = second_kind = None
            while self.peek() in ("^", "_") and second is None:
                second_kind = self.take()
                second = self.group()
        finally:
            self.depth -= 1
        if second_kind is None:
            return (first, None) if kind == "^" else (None, first)
        return (first, second) if kind == "^" else (second, first)

    def script(self, base: Box, kind: str) -> Box:
        sup, sub = self._scripts(kind)
        return self.attach(base, sup, sub)

    def prescript(self, kind: str) -> Box:
        """A ^ or _ with no base: the scripts belong to what comes next.

        "^A_BR" is the frame-B-to-frame-A rotation, one atom, not a stray
        column of letters beside an R.
        """
        sup, sub = self._scripts(kind)
        base = self.group()
        if self.peek() in ("^", "_"):
            post_sup, post_sub = self._scripts(self.take())
            base = self.attach(base, post_sup, post_sub)
        up, down = _flatten(sup), _flatten(sub)
        if not up and not down:
            return base
        if self.display and not self.depth:
            width = max(len(up), len(down))
            column = _column(up.rjust(width), down.rjust(width))
        else:
            # Always bracketed, even where a bare "ᴬ" exists, so a prescript
            # can never be read as the previous atom's script.
            column = Box.text(_marked(up, SUPERS, SUP_PAREN)
                              + _marked(down, SUBS, SUB_PAREN))
        return hcat([column, base])

    def attach(self, base: Box, sup: Box | None, sub: Box | None) -> Box:
        """Hang a superscript and a subscript off a base."""
        flat = base.lines[0].strip() if base.height == 1 else ""
        takes_limits = flat in BIG_OPS or flat in LIMIT_WORDS or base.height > 1
        if self.display and not self.depth and takes_limits:
            # Limits go over and under: \sum, \int, \lim, a bracketed matrix.
            return stack(sup or Box.text(""), base, sub or Box.text(""))
        up, down = _flatten(sup), _flatten(sub)
        if not up and not down:
            return base
        forms = {}
        for text, table, kind in ((down, SUBS, "_"), (up, SUPERS, "^")):
            if text:
                forms[kind] = None if self.plain[kind] else scriptify(text, table)
        # Anything else keeps its scripts beside the base, display or not. A
        # letter parked on the row above or below is read as part of whatever
        # else is on that row: next to a fraction it lands among the
        # numerators, which is how "rφ̇/2" grew a stray L over the rule.
        # Subscript first, then superscript: x_i^2 reads as xᵢ².
        pieces = [base]
        for text, parens, kind in ((down, SUB_PAREN, "_"), (up, SUP_PAREN, "^")):
            if not text:
                continue
            pieces.append(Box.text(forms[kind] or parens[0] + text + parens[1]))
        return hcat(pieces)

    # --- environments -----------------------------------------------------
    def environment(self, name: str) -> Box:
        self.depth += 1
        try:
            return self._environment(name)
        finally:
            self.depth -= 1

    def _environment(self, name: str) -> Box:
        rows: list = []
        row: list = []
        ruled: set = set()                  # rows \hline draws a rule above
        while self.peek() is not None:
            token = self.peek()
            if token == "\\end":
                self.take()
                self.raw_group()
                break
            if token == "\\hline":
                self.take()
                ruled.add(len(rows))
                continue
            if token == "\\\\":
                self.take()
                rows.append(row)
                row = []
                continue
            if token == "&":
                self.take()
                row.append(None)            # column break
                continue
            self.take()
            if token == "{":
                row.append(self.run(stop="}"))
                continue
            if token in ("^", "_"):
                if row and row[-1] is not None and _is_base(row[-1]):
                    row.append(self.script(row.pop(), token))
                else:
                    row.append(self.prescript(token))
                continue
            row.append(self.atom(token))
        rows.append(row)
        grid: list = []
        rules: set = set()
        kept: set = set()
        for index, r in enumerate(rows):
            if not any(x is not None and "".join(x.lines).strip() for x in r):
                continue                    # a row break with nothing after it
            if index in ruled:
                rules.add(len(grid))
            kept.add(index)
            grid.append(_split_cells(r))
        if grid and ruled - kept:
            rules.add(len(grid))            # \hline just before \end: a closing rule
        if not grid:
            return Box.text("")
        if not self.display:
            rows_text = ["  ".join(" ".join(x.strip() for x in cell.lines).strip()
                                   for cell in row) for row in grid]
            body_text = "; ".join(r for r in rows_text if r)
            # A plain "matrix" -- and the "array" tex2ink rewrites into one --
            # has no delimiters of its own in LaTeX. \left...\right supplies
            # them, so adding a pair here printed both.
            fences = {"bmatrix": "[]", "bsmallmatrix": "[]", "pmatrix": "()",
                      "psmallmatrix": "()", "vmatrix": "||", "Bmatrix": "{}",
                      "cases": "{ "}.get(name, "")
            if not fences:
                return Box.text(body_text)
            return Box.text(f"{fences[0]}{body_text}{fences[1]}".rstrip())
        body = _grid(grid, gap=2 if name.endswith("matrix") else 3, rules=rules)
        left = {"bmatrix": "[", "bsmallmatrix": "[", "pmatrix": "(",
                "psmallmatrix": "(", "vmatrix": "|", "Bmatrix": "{"}.get(name)
        if left:
            right = {"[": "]", "(": ")", "|": "|", "{": "}"}[left]
            pad = Box([" " * 1] * body.height, body.baseline)
            return hcat([_fence(left, body.height, body.baseline), pad, body,
                         pad, _fence(right, body.height, body.baseline)])
        if name == "cases":
            pad = Box([" " * 1] * body.height, body.baseline)
            return hcat([_fence("{", body.height, body.baseline), pad, body])
        return body


def _split_cells(row: list) -> list:
    cells: list = []
    current: list = []
    for item in row:
        if item is None:
            cells.append(hcat(current) if current else Box.text(""))
            current = []
        else:
            current.append(item)
    cells.append(hcat(current) if current else Box.text(""))
    return cells


def _grid(rows: list, gap: int = 2, rules=()) -> Box:
    """Lay cells out in columns, however tall any one of them is."""
    columns = max(len(row) for row in rows)
    widths = [max((row[c].width for row in rows if c < len(row)), default=0)
              for c in range(columns)]
    stacked = []
    for row in rows:
        pieces = []
        for c in range(columns):
            cell = row[c] if c < len(row) else Box.text("")
            pieces.append(_centred(cell, widths[c]))
            if c < columns - 1:
                pieces.append(Box.text(" " * gap))
        stacked.append(hcat(pieces))
    return _pile(stacked, rules)


def _centred(box: Box, width: int) -> Box:
    return Box([line.center(width) for line in box.padded().lines], box.baseline)


def _pile(boxes: list, rules=()) -> Box:
    """Rows one under another, the middle row carrying the baseline.

    ``rules`` names the rows an ``\\hline`` partitions off; the rule is drawn
    right across the body rather than printed as the word the writer typed.
    """
    width = max((box.width for box in boxes), default=0)
    lines = []
    middles = []
    for index, box in enumerate(boxes):
        if index in rules:
            lines.append("─" * width)
        middles.append(len(lines) + box.baseline)
        lines += [line.ljust(width) for line in box.padded().lines]
    if len(boxes) in rules:
        lines.append("─" * width)
    return Box(lines, middles[len(middles) // 2] if middles else 0)


TYPED = {0x2223: "|", 0x2225: "||", 0x2016: "||"}


def _fence(kind: str, height: int, baseline: int | None = None) -> Box:
    """A bracket as tall as what it holds.

    It takes the *contents'* baseline, or gluing the two together shifts one
    against the other and the brackets end up round the wrong rows.
    """
    if height == 1:
        return Box.text(kind)
    top, mid, bottom = BRACKETS.get(kind, ("|", "|", "|"))
    lines = [top] + [mid] * (height - 2) + [bottom]
    return Box(lines, height // 2 if baseline is None else baseline)


def _paren(text: str) -> str:
    """Parenthesise only what could otherwise be misread.

    An operator already inside brackets is not loose, so "(x-μ)²" is left
    alone and only "x-μ" is wrapped.
    """
    if len(text) < 2:
        return text
    depth = 0
    for ch in text:
        if ch in "([{⟨":
            depth += 1
        elif ch in ")]}⟩":
            depth = max(0, depth - 1)
        elif not depth and ch in "+-= /":
            return f"({text})"
    return text


def _flatten(box: Box | None) -> str:
    """A script argument as one line of text."""
    if box is None or not box.height:
        return ""
    return " ".join(line.strip() for line in box.lines).strip()


def _column(sup: str, sub: str) -> Box:
    """A script that has to be stacked: above the baseline, below it, or both."""
    if sup and sub:
        return Box([sup, " " * max(len(sup), len(sub)), sub], 1)
    if sup:
        return Box([sup, ""], 1)
    return Box(["", sub], 0)


def _marked(text: str, table: dict, parens: tuple) -> str:
    """A script on one line, in tiny brackets: the prescript form."""
    if not text:
        return ""
    return parens[0] + (scriptify(text, table) or text) + parens[1]


def _is_base(box: Box) -> bool:
    """Could this be carrying a script, or is the script's base empty?

    An "=" or a "[" cannot take a superscript, so "=^BQ" is a Q with a
    prescript rather than an equals sign wearing a B.
    """
    if not box.height:
        return False
    row = box.lines[box.baseline] if box.baseline < box.height else box.lines[-1]
    row = row.rstrip()
    return bool(row) and row[-1] not in RELATIONS and row[-1] not in "+-*/,;:([{&<>"


# --- public -----------------------------------------------------------------
def render(src: str, *, display: bool = False) -> Box:
    try:
        return Parser(tokenize(src), display).run()
    except Exception:                       # noqa: BLE001 - never lose a note
        return Box.text(src)


def inline(src: str) -> str:
    """One line of math, for use inside a sentence."""
    box = render(src, display=False)
    return " ".join(line.strip() for line in box.lines).strip() if box.height > 1 \
        else box.lines[0].strip()


def display(src: str) -> list:
    """Math on its own, as several lines."""
    box = render(src, display=True)
    lines = [line.rstrip() for line in box.padded().lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or [""]


_MATH = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$", re.S)


def has_math(text: str) -> bool:
    return bool(_MATH.search(text))


def substitute(text: str) -> str:
    """Typeset every ``$...$`` span in a line of prose."""
    return _MATH.sub(lambda m: inline(m.group(1)), text)
