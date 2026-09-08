"""
Dated captures of the whole rate board, so a trend can exist at all.

No source publishes historical savings rates. Banks show today's board and
nothing else, and the aggregator that covers all of them has no per-date
pages either -- unlike its gold section, which does. So the history has to be
made rather than fetched: every run stores what it saw, and the trend chart is
built from those stored captures.

That has one consequence worth being honest about on the page: **the first run
produces a single point and no trend.** The dashboard says so rather than
drawing a flat line through one observation, because a flat line reads as "the
rate did not move" when it means "we have only looked once".

One JSON file, newest last, capped. A database for a list that grows by one
row a day would be a dependency bought with nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path("data") / "rate_snapshots.json"

# Roughly two years of daily captures. Past that the oldest are dropped.
MAX_SNAPSHOTS = 800

_LOCK = threading.Lock()


@dataclass(frozen=True)
class RateQuote:
    """One bank's advertised rate for one tenor, as published.

    `board` separates two products the source publishes side by side: money
    paid in at a counter, and money paid in through the app. They are not
    variants of one number -- a bank that quotes nothing at the counter for a
    twelve-month deposit may pay 6.20% online -- so mixing them would show
    banks as offering nothing when they offer more.
    """

    bank: str
    tenor_months: int
    rate_pct: float
    board: str = "counter"          # "counter" | "online"


@dataclass
class RateSnapshot:
    captured_at: str                  # ISO, to the second
    source: str                       # which site the board came from
    quotes: list[RateQuote] = field(default_factory=list)
    # Banks whose official page was cross-checked, and whether it matched.
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
    """Every stored capture, oldest first."""
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A corrupt file loses the history, which is recoverable by running
        # again. Raising here would take the dashboard down with it.
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
            continue      # an entry from an older shape is skipped, not fatal
    return sorted(out, key=lambda s: s.captured_at)


def append(snapshot: RateSnapshot, path: Path | str = DEFAULT_PATH) -> None:
    """Store one capture. Same-day captures replace, they do not accumulate.

    Running twice in an afternoon is a person checking their work, not two
    observations. Keeping both would put two points on the same day and make
    an unchanged board look like movement.
    """
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
    """One bank's rate at one tenor over time, ready for `src/timeseries`."""
    rows = []
    for snapshot in snapshots:
        rate = snapshot.by_tenor(tenor, board).get(bank)
        if rate is not None:
            rows.append({"date": snapshot.captured_date, "rate_pct": rate})
    return rows


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")
