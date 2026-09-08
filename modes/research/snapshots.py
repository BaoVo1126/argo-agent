from __future__ import annotations
import datetime as dt
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("data") / "rate_snapshots.json"

MAX_SNAPSHOTS = 800

_LOCK = threading.Lock()


@dataclass(frozen=True)
class RateQuote:
    bank: str
    tenor_months: int
    rate_pct: float
    board: str = "counter"         


@dataclass
class RateSnapshot:
    captured_at: str            
    source: str                     
    quotes: list[RateQuote] = field(default_factory=list)
    crosscheck: dict = field(default_factory=dict)

    @property
    def captured_date(self) -> dt.date:
        return dt.date.fromisoformat(self.captured_at[:10])

    def by_tenor(self, tenor: int, board: str = "counter") -> dict[str, float]:
        return {q.bank: q.rate_pct for q in self.quotes
                if q.tenor_months == tenor and q.board == board}

    def banks(self, board: str | None = None) -> list[str]:
        return sorted({q.bank for q in self.quotes if board is None or q.board == board})

    def tenors(self, board: str | None = None) -> list[int]:
        return sorted({q.tenor_months for q in self.quotes
                       if board is None or q.board == board})

    def boards(self) -> list[str]:
        return sorted({q.board for q in self.quotes})


def load(path: Path | str = DEFAULT_PATH) -> list[RateSnapshot]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    out = []
    for item in raw.get("snapshots") or []:
        try:
            quotes = [RateQuote(**q) for q in item.get("quotes", [])]
            out.append(RateSnapshot(
                captured_at=item["captured_at"],
                source=item.get("source", ""),
                quotes=quotes,
                crosscheck=item.get("crosscheck") or {},
            ))
        except (TypeError, KeyError):
            continue  
    return sorted(out, key=lambda s: s.captured_at)


def append(snapshot: RateSnapshot, path: Path | str = DEFAULT_PATH) -> None:
    path = Path(path)
    with _LOCK:
        kept = [s for s in load(path) if s.captured_at[:10] != snapshot.captured_at[:10]]
        kept.append(snapshot)
        kept.sort(key=lambda s: s.captured_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"snapshots": [
                {"captured_at": s.captured_at, "source": s.source,
                 "crosscheck": s.crosscheck,
                 "quotes": [asdict(q) for q in s.quotes]}
                for s in kept[-MAX_SNAPSHOTS:]
            ]},
            ensure_ascii=False, indent=1,
        ), encoding="utf-8")


def series(snapshots: list[RateSnapshot], bank: str, tenor: int,
           board: str = "counter") -> list[dict]:
    rows = []
    for snapshot in snapshots:
        rate = snapshot.by_tenor(tenor, board).get(bank)
        if rate is not None:
            rows.append({"date": snapshot.captured_date, "rate_pct": rate})
    return rows


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")
