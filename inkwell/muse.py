"""Optional second opinion on how a note should be *formatted*.

The model is a copy editor, not a designer: it says what kind of block a
line is, how deep it sits, whether it continues the line above, whether a
run-on should become a list, and which phrase carries the weight. It never
chooses type sizes -- that is document.py's and typography.py's business.

The heuristics in shaping.py run instantly and are always what you see
first. This lane is **off unless you point it somewhere**: set both
``INKWELL_LLM_URL`` (any OpenAI-compatible /v1 endpoint -- llama.cpp,
vLLM, Ollama, a hosted API) and a key, and each new note is also sent to
the model in a background thread; when the answer lands the note
re-formats in place. Nothing here is on the typing path, and every failure
mode ends in "keep what the markup said", so inkwell is complete without it.

    export INKWELL_LLM_URL=http://localhost:8080/v1
    export INKWELL_LLM_KEY=whatever-your-endpoint-wants
    export INKWELL_LLM_MODEL=some-model        # optional

There is no default endpoint on purpose: a notes app should not send
anything anywhere until its owner has said where.
"""

from __future__ import annotations

import json
import os
import queue
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from . import shaping as S

# No default endpoint: nothing leaves this machine until you name one.
GATEWAY = os.environ.get("INKWELL_LLM_URL", "")
MODEL = os.environ.get("INKWELL_LLM_MODEL", "default")
# Reasoning models want to be told not to monologue; everything else
# would reject the field, so it is sent only when asked for.
EFFORT = os.environ.get("INKWELL_LLM_EFFORT", "")
# A key may also be left in a file, so it stays out of your shell history
# and your environment.
KEY_FILES = (Path.home() / ".config/inkwell/key",)
KEY_ENV = ("INKWELL_LLM_KEY",)

BLOCKS = S.FORMATTABLE

PROMPT = (
    "You are the copy editor for a terminal notebook. You are given the last "
    "few notes for context and then ONE new note. Say how to FORMAT the new "
    "note as part of the document. Fields:\n"
    "block: " + " | ".join(BLOCKS) + "\n"
    "  para = prose; ask = an open question to come back to; item = list item; check = something to do; kv = a "
    "'name: value' fact worth aligning in a column; section = a name for the "
    "part of the document that follows; head = a smaller heading; quote = "
    "someone else's words; code = a command, path or identifier; callout = "
    "urgent.\n"
    "level: 0, 1 or 2 -- indent depth under the notes above.\n"
    "continues: true if this note qualifies or elaborates the note directly "
    "above it -- a fragment starting with 'only if', 'unless', 'but', "
    "'because', or adding a condition to it -- so it should be indented "
    "under that note. Then use the same block as the note above.\n"
    "  e.g. above '- perforated aluminium', the note 'only if the vendor has "
    'it in stock\' -> {"block":"item","continues":true}\n'
    "items: when the note runs several things together -- separated by "
    "'then', 'and', 'also' or commas -- split them here and set block=item "
    "(or check, if they are things to do). Keep each item's own words. "
    "Otherwise [].\n"
    "  e.g. 'cut the plate then bend the flange then clinch it' -> "
    '{"block":"item","items":["cut the plate","bend the flange","clinch it"]}\n'
    "key / value: for block=kv only, the two halves, copied verbatim.\n"
    "emphasis: the most load-bearing phrase copied VERBATIM from the note "
    "(<=5 words), or \"\" -- prose and list items only.\n"
    "tag: one lowercase word naming what THIS note itself is, or \"\". Never "
    "name something that comes after it, and never repeat a word that is "
    "already in the note -- the reader can see those. Most notes want \"\".\n"
    "Keep the wording; you are formatting it, not rewriting it.\n"
    'Reply with JSON only: {"block":...,"level":0,"continues":false,'
    '"items":[],"key":"","value":"","emphasis":"","tag":""}'
)


def resolve_key(env=None) -> Optional[str]:
    env = os.environ if env is None else env
    for var in KEY_ENV:
        if env.get(var):
            return env[var]
    for path in KEY_FILES:
        try:
            text = path.read_text().strip()
        except OSError:
            continue
        if text:
            return text.splitlines()[0].strip()
    return None


def parse(payload: str) -> dict:
    """Pull the formatting fields we trust out of a model reply."""
    try:
        data = json.loads(payload)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    block = str(data.get("block", "")).strip().lower()
    if block in BLOCKS:
        out["block"] = block
    try:
        level = int(data.get("level") or 0)
    except (TypeError, ValueError):
        level = 0
    if 0 < level <= S.MAX_LEVEL:
        out["level"] = level
    if data.get("continues") is True:
        out["continues"] = True
    items = [str(x).strip() for x in (data.get("items") or [])
             if isinstance(x, (str, int, float)) and str(x).strip()]
    if len(items) > 1:
        out["items"] = items[:12]
    for half in ("key", "value"):
        text = str(data.get(half) or "").strip()
        if 0 < len(text) <= 60:
            out[half] = text
    emphasis = str(data.get("emphasis") or "").strip()
    if 0 < len(emphasis) <= 40:
        out["emphasis"] = emphasis
    tag = str(data.get("tag") or "").strip().lower()
    if tag and len(tag) <= 18 and tag.replace("-", "").isalnum():
        out["tag"] = tag
    return out


class Muse:
    """A one-thread work queue in front of the model."""

    def __init__(self, key: Optional[str] = None, url: str = GATEWAY,
                 model: str = MODEL, opener=None, timeout: float = 30.0,
                 effort: str = EFFORT) -> None:
        self.key = key if key is not None else resolve_key()
        # An unset endpoint stays unset -- "" must not become a bare path
        # that looks like somewhere to send notes.
        self.url = (url.rstrip("/") + "/chat/completions") if url.strip() else ""
        self.model = model or "default"
        self.effort = effort
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen
        self._ctx = ssl.create_default_context()
        self._jobs: queue.Queue = queue.Queue()
        self._out: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self.pending = 0
        self.failures = 0

    @property
    def enabled(self) -> bool:
        """Both halves, or nothing: a key with nowhere to go is not a lane."""
        return bool(self.key and self.url)

    def ask(self, note_id: int, text: str, wake: Optional[Callable] = None,
            context: Optional[list] = None) -> None:
        if not self.enabled or len(text.strip()) < 3:
            return
        self.pending += 1
        self._jobs.put((note_id, text, wake, list(context or [])[-6:]))
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def drain(self) -> list[tuple[int, dict]]:
        out = []
        while True:
            try:
                out.append(self._out.get_nowait())
            except queue.Empty:
                return out

    def _run(self) -> None:
        while True:
            try:
                note_id, text, wake, context = self._jobs.get(timeout=1.0)
            except queue.Empty:
                return
            try:
                fields = self.classify(text, context)
            except Exception:                     # noqa: BLE001 - never crash typing
                self.failures += 1
                fields = {}
            finally:
                self.pending = max(0, self.pending - 1)
            if fields:
                self._out.put((note_id, fields))
                if wake:
                    try:
                        wake()
                    except Exception:             # noqa: BLE001
                        pass

    def classify(self, text: str, context: Optional[list] = None) -> dict:
        above = "\n".join(f"- {line}" for line in (context or []))
        user = (f"Notes already on the page:\n{above}\n\nNew note:\n{text}"
                if above else f"New note:\n{text}")
        fields = {
            "model": self.model,
            # Ask for parseable output. Endpoints that do not know the field
            # ignore it; the reply is checked either way.
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": PROMPT},
                         {"role": "user", "content": user}],
        }
        if self.effort:                 # reasoning models only -- see EFFORT
            fields["reasoning_effort"] = self.effort
        body = json.dumps(fields).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.key}"})
        with self._opener(req, timeout=self.timeout, context=self._ctx) as resp:
            payload = json.loads(resp.read().decode())
        content = payload["choices"][0]["message"].get("content") or ""
        return parse(content)
