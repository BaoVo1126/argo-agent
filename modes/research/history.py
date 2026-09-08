from __future__ import annotations
import datetime as dt
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("data") / "run_history.json"

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
    outcome: str                      
    summary: str = ""                
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
        return []
    entries = []
    for item in raw.get("runs") or []:
        try:
            sources = [SourceOutcome(**s) for s in item.pop("sources", [])]
            entries.append(RunEntry(sources=sources, **item))
        except TypeError:
            continue  
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
