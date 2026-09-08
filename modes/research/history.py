"""
A log of what was asked and what came back, for the customer's second tab.

Not a debug log. Nothing here is a stack trace, a selector, a score breakdown
or a phase name -- it is the answer to "what did I run last week, and did it
work?", which is a question a person asks about their own work rather than
about the machine.

Kept as one JSON file, newest first, capped. A database for a list somebody
scrolls occasionally would be a dependency bought with nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("data") / "run_history.json"

# Enough to cover a working week of experimenting; past that the oldest go.
MAX_ENTRIES = 200

_LOCK = threading.Lock()


@dataclass
class SourceOutcome:
    label: str
    score: int
    accepted: bool
    ok: bool
    rows: int = 0


@dataclass
class RunEntry:
    started_at: str
    topic: str
    metric: str
    window: str
    seconds: float
    outcome: str                      # "done" | "refused" | "failed"
    summary: str = ""                 # one line the customer can scan
    sources: list[SourceOutcome] = field(default_factory=list)

    @property
    def sources_passed(self) -> int:
        return sum(1 for s in self.sources if s.accepted)


def load(path: Path | str = DEFAULT_PATH) -> list[RunEntry]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A corrupt history is worth less than a missing one is harmful: an
        # empty list keeps the page working and loses only the listing.
        return []
    entries = []
    for item in raw.get("runs") or []:
        try:
            sources = [SourceOutcome(**s) for s in item.pop("sources", [])]
            entries.append(RunEntry(sources=sources, **item))
        except TypeError:
            continue   # an entry written by an older shape is skipped, not fatal
    return entries


def append(entry: RunEntry, path: Path | str = DEFAULT_PATH) -> None:
    path = Path(path)
    with _LOCK:
        entries = [entry] + load(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"runs": [asdict(e) for e in entries[:MAX_ENTRIES]]},
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")
