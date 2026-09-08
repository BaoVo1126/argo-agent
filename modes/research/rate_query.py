"""
The structured question the rate form asks, answered from stored captures.

The form replaced a free-text box, and that is a change of kind rather than of
convenience. A typed topic has to be interpreted before anything can be
computed -- which is why the macro flow needs a planner, a catalogue lookup and
a guard against the model picking the wrong indicator. A savings-rate question
has exactly four moving parts: which banks, which tenors, compared how, over
which two periods. All four are things a person can point at, so they are
selected rather than described, and the model is out of the loop entirely.

This module is orchestration and nothing else. The comparison between banks is
`bank_rates.gaps_at`, the comparison between periods is
`src/timeseries.compare_windows`, the charts are `bank_rates.render_snapshot`
and `bank_rates.render_trend`, and the sentences are the templates next to
them. What is here is the part none of those should own: turning one query
into one answer, and saying plainly which parts of it the stored history
cannot support.

**Why every mode still reads the same store.** `snapshots.py` holds bank x
tenor x capture date. "Between banks" fixes the date and varies the bank;
"over time" fixes the bank and varies the date; "both" varies neither and
reports the cell. Three questions, one table, no second pipeline -- and the
credibility story is untouched, because none of this changes where a number
came from.

**Why an answer can be mostly empty and still be an answer.** A rate board is
a history of captures, not a daily publication, so a period a person picks may
contain no observation at all. That is a fact about the record rather than
about the rate, and the honest response is to say which period is empty and
still show everything else -- not to refuse the whole query, and not to print
a zero that reads as "the rate did not move".
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from modes.research import bank_rates, snapshots
from modes.research.bank_rates import BankGap, RateChange
from modes.research.snapshots import RateSnapshot
from src.timeseries import CALENDAR_PRESETS, PRESET_LABELS, preset_windows

# What the form's radio buttons mean here.
MODES = ("time", "banks", "both")

# A custom range is two windows the person drew themselves; the presets build
# their own. Named rather than a bare boolean so the answer can say which was
# used without the caller having to infer it.
CUSTOM = "custom"

# How many sentences the insight block prints. Past this the reader is being
# handed a list to search rather than a finding to read, and the table below
# already holds every number.
MAX_INSIGHTS = 6

# Charts are drawn for at most this many of the chosen tenors. Not a display
# preference: each one is a matplotlib render, and seven tenors in "both" mode
# is fourteen of them -- twelve seconds of a person waiting on a request that
# otherwise only reads a JSON file. The table still carries every tenor the
# query asked for, so what the cap costs is a picture rather than a number.
MAX_CHART_TENORS = 3


def _chart_path(output_dir: Path, kind: str, board: str, tenor: int,
                banks: list[str], stamp: str) -> Path:
    """A name that is the same for the same picture and different otherwise.

    The bank list is in the name because it changes the chart: a snapshot of
    three banks and a snapshot of seven at the same tenor on the same day are
    different images, and a name that ignored the difference would serve the
    first one for the second. With the list in the name, a repeat query can
    skip the render entirely -- which is what makes selecting a tenor twice
    cost nothing.
    """
    digest = hashlib.sha1("|".join(sorted(banks)).encode("utf-8")).hexdigest()[:8]
    return output_dir / f"{kind}_{board}_{tenor}m_{stamp}_{digest}.png"


@dataclass
class RateQuery:
    """One question from the form, already validated by the caller."""

    banks: tuple[str, ...]
    tenors: tuple[int, ...]
    mode: str = "banks"                 # time | banks | both
    preset: str = "month"               # week | month | year | custom
    current: tuple[dt.date, dt.date] | None = None      # required when custom
    previous: tuple[dt.date, dt.date] | None = None
    board: str = "counter"              # counter | online

    @property
    def wants_time(self) -> bool:
        return self.mode in ("time", "both")

    @property
    def wants_banks(self) -> bool:
        return self.mode in ("banks", "both")

    def windows(self, today: dt.date | None = None):
        """The two date windows this query compares, or None for neither."""
        if self.preset == CUSTOM:
            return (self.current, self.previous) if self.current and self.previous \
                else None
        return preset_windows(self.preset, today)


@dataclass
class Cell:
    """One bank at one tenor: where it stands, and how it moved."""

    tenor: int
    rate: float | None = None
    change: float | None = None
    note: str = ""


@dataclass
class Row:
    bank: str
    is_big_four: bool = False
    cells: dict[int, Cell] = field(default_factory=dict)


@dataclass
class RateAnswer:
    ok: bool = False
    message: str = ""
    mode: str = "banks"
    board: str = "counter"
    captured_at: str = ""
    updates: int = 0
    tenors: list[int] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    # Best and worst per tenor, so the table can colour them the way the
    # dashboard already does.
    highest: dict[int, str] = field(default_factory=dict)
    lowest: dict[int, str] = field(default_factory=dict)
    gaps: list[BankGap] = field(default_factory=list)
    changes: list[RateChange] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    # Absolute paths; the web layer turns them into URLs.
    snapshot_charts: dict[int, Path] = field(default_factory=dict)
    trend_charts: dict[int, Path] = field(default_factory=dict)
    period_current: str = ""
    period_previous: str = ""
    period_label: str = ""
    # Sentences about what the stored history could not answer.
    caveats: list[str] = field(default_factory=list)


def available(history: list[RateSnapshot], board: str = "counter") -> dict:
    """What the form may offer, read off the captures rather than hard-coded.

    A form listing a bank the board has never carried is a choice that can only
    end in an empty result, so the options come from the data. The tenor list
    is intersected with `bank_rates.TENORS` because the board also publishes
    promotional variants the comparison deliberately drops.
    """
    if not history:
        return {"banks": [], "tenors": [], "boards": [], "updates": 0,
                "first": "", "last": ""}
    latest = history[-1]
    return {
        "banks": latest.banks(board),
        "tenors": [t for t in bank_rates.TENORS if t in set(latest.tenors(board))],
        "boards": latest.boards(),
        "updates": len(history),
        "first": history[0].captured_at[:10],
        "last": latest.captured_at[:10],
        "unavailable": list(bank_rates.UNAVAILABLE),
        "big_four": list(bank_rates.BIG_FOUR),
    }


def _period_labels(query: RateQuery, windows) -> tuple[str, str, str]:
    """How to name the two windows in a sentence a customer reads."""
    if windows is None:
        return "", "", ""
    (current_start, current_end), (previous_start, previous_end) = windows
    if query.preset in CALENDAR_PRESETS:
        title, short = PRESET_LABELS[query.preset]
    else:
        title, short = "Kỳ đã chọn", "kỳ so sánh"
    return (
        f"{current_start:%d/%m/%Y} – {current_end:%d/%m/%Y}",
        f"{previous_start:%d/%m/%Y} – {previous_end:%d/%m/%Y}",
        f"{title} so với {short}",
    )


def answer(query: RateQuery, history: list[RateSnapshot] | None = None,
           output_dir: Path = Path("outputs"),
           today: dt.date | None = None) -> RateAnswer:
    """Everything the page shows for one query. Never raises for missing data."""
    history = snapshots.load() if history is None else history
    result = RateAnswer(mode=query.mode, board=query.board)

    if not history:
        result.message = ("Chưa có lần cập nhật nào. Bấm Cập nhật để lấy bảng lãi "
                          "suất trước khi so sánh.")
        return result

    latest = history[-1]
    result.captured_at = latest.captured_at
    result.updates = len(history)

    offered = set(latest.tenors(query.board))
    result.tenors = [t for t in query.tenors if t in offered]
    banks = [b for b in query.banks if b in set(latest.banks(query.board))]

    if not banks or not result.tenors:
        result.message = ("Bảng lãi suất mới nhất không có ngân hàng hoặc kỳ hạn bạn "
                          "chọn. Bạn thử chọn lại từ danh sách bên trên.")
        return result

    # --- the table, which every mode shows ---------------------------------
    windows = query.windows(today) if query.wants_time else None
    changes: list[RateChange] = []
    if windows is not None:
        changes = bank_rates.rate_changes(history, banks, result.tenors,
                                          windows[0], windows[1], query.board)
        result.changes = changes
        result.period_current, result.period_previous, result.period_label = \
            _period_labels(query, windows)
    elif query.wants_time:
        result.caveats.append(
            "Chưa chọn đủ hai khoảng thời gian để so sánh, nên bảng chỉ hiển thị "
            "mức lãi suất hiện tại."
        )

    by_pair = {(c.bank, c.tenor): c for c in changes}
    rates_now = {t: latest.by_tenor(t, query.board) for t in result.tenors}

    for bank in banks:
        row = Row(bank=bank, is_big_four=bank in bank_rates.BIG_FOUR)
        for tenor in result.tenors:
            moved = by_pair.get((bank, tenor))
            row.cells[tenor] = Cell(
                tenor=tenor,
                rate=rates_now[tenor].get(bank),
                change=moved.change if moved else None,
                note=moved.note if moved else "",
            )
        result.rows.append(row)

    # Best first at the first chosen tenor, for the same reason the dashboard
    # sorts: the table's first job is to answer "who pays most".
    lead = result.tenors[0]
    result.rows.sort(key=lambda r: (r.cells[lead].rate is None,
                                    -(r.cells[lead].rate or 0)))

    for tenor in result.tenors:
        offered_now = {b: rates_now[tenor][b] for b in banks if b in rates_now[tenor]}
        # Nothing is marked best or worst when every bank quotes the same rate.
        # "Cao nhất ở kỳ hạn đó" is a claim that one of them differs, and
        # colouring an arbitrary row green when none of them does would be the
        # table asserting a difference the numbers do not contain.
        if len(set(offered_now.values())) > 1:
            result.highest[tenor] = max(offered_now, key=offered_now.get)
            result.lowest[tenor] = min(offered_now, key=offered_now.get)

    # --- charts -------------------------------------------------------------
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = latest.captured_at[:10].replace("-", "")

    # One chart per tenor rather than one chart holding every line: three banks
    # at three tenors is nine series, and the chart engine caps a line chart at
    # the number of colours that stay apart from one another.
    charted = result.tenors[:MAX_CHART_TENORS]
    chosen = banks[:bank_rates.MAX_TREND_BANKS]

    for tenor in charted:
        if query.wants_banks:
            path = _chart_path(output_dir, "ss", query.board, tenor, banks, stamp)
            if path.is_file() or bank_rates.render_snapshot(
                    latest, banks, tenor, path, query.board):
                result.snapshot_charts[tenor] = path
        path = _chart_path(output_dir, "tr", query.board, tenor, chosen, stamp)
        if path.is_file() or bank_rates.render_trend(
                history, chosen, path, tenor, query.board):
            result.trend_charts[tenor] = path

    if len(result.tenors) > len(charted):
        result.caveats.append(
            "Biểu đồ chỉ vẽ cho " + ", ".join(f"{t} tháng" for t in charted)
            + ". Bảng bên trên vẫn đủ tất cả kỳ hạn bạn chọn."
        )

    if not result.trend_charts:
        result.caveats.append(
            "Chưa đủ số lần cập nhật để vẽ diễn biến theo thời gian. Cần ít nhất "
            "hai lần cập nhật ở cùng kỳ hạn."
        )
    if len(banks) > bank_rates.MAX_TREND_BANKS:
        result.caveats.append(
            f"Biểu đồ theo thời gian chỉ vẽ {bank_rates.MAX_TREND_BANKS} ngân hàng "
            f"đầu tiên bạn chọn ({', '.join(chosen)}); bảng bên trên vẫn đủ "
            f"{len(banks)} ngân hàng."
        )

    # --- the sentences ------------------------------------------------------
    if query.wants_banks:
        for tenor in result.tenors:
            pairs = bank_rates.gaps_at(latest, tenor, banks, query.board)
            if pairs:
                result.gaps.append(pairs[0])
                result.insights.append(bank_rates.gap_sentence(pairs[0]))

    if query.wants_time and changes:
        _, short = PRESET_LABELS.get(query.preset, ("", "kỳ so sánh"))
        measured = [c for c in changes if c.change is not None]
        # Biggest movers first: a list in bank order buries the finding under
        # whichever names happen to sort early.
        for moved in sorted(measured, key=lambda c: abs(c.change or 0), reverse=True):
            result.insights.append(bank_rates.change_sentence(moved, short))

        # The cells with nothing to compare are one fact about the record, not
        # one finding per cell. Repeating "chưa có lần cập nhật nào" six times
        # under a heading that says "Nhận định" buries the two real sentences
        # among four copies of an apology, so it is said once, as a caveat.
        blocked = [c for c in changes if c.change is None]
        if blocked:
            reasons = "; ".join(sorted({c.note for c in blocked if c.note}))
            result.caveats.append(
                f"Không so sánh được với {short} ở {len(blocked)}/{len(changes)} ô"
                + (f" — {reasons}." if reasons else ".")
            )

    result.insights = result.insights[:MAX_INSIGHTS]
    result.ok = True
    return result
