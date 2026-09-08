from __future__ import annotations
import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from modes.research import bank_rates, snapshots
from modes.research.bank_rates import BankGap, RateChange
from modes.research.snapshots import RateSnapshot
from src.timeseries import CALENDAR_PRESETS, PRESET_LABELS, preset_windows


MODES = ("time", "banks", "both")


CUSTOM = "custom"

MAX_INSIGHTS = 6

MAX_CHART_TENORS = 3


def _chart_path(output_dir: Path, kind: str, board: str, tenor: int,
                banks: list[str], stamp: str) -> Path:
    digest = hashlib.sha1("|".join(sorted(banks)).encode("utf-8")).hexdigest()[:8]
    return output_dir / f"{kind}_{board}_{tenor}m_{stamp}_{digest}.png"


@dataclass
class RateQuery:
    banks: tuple[str, ...]
    tenors: tuple[int, ...]
    mode: str = "banks"                
    preset: str = "month"            
    current: tuple[dt.date, dt.date] | None = None      
    previous: tuple[dt.date, dt.date] | None = None
    board: str = "counter"           

    @property
    def wants_time(self) -> bool:
        return self.mode in ("time", "both")

    @property
    def wants_banks(self) -> bool:
        return self.mode in ("banks", "both")

    def windows(self, today: dt.date | None = None):
        if self.preset == CUSTOM:
            return (self.current, self.previous) if self.current and self.previous \
                else None
        return preset_windows(self.preset, today)


@dataclass
class Cell:
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
    highest: dict[int, str] = field(default_factory=dict)
    lowest: dict[int, str] = field(default_factory=dict)
    gaps: list[BankGap] = field(default_factory=list)
    changes: list[RateChange] = field(default_factory=list)
    insights: list[str] = field(default_factory=list)
    snapshot_charts: dict[int, Path] = field(default_factory=dict)
    trend_charts: dict[int, Path] = field(default_factory=dict)
    period_current: str = ""
    period_previous: str = ""
    period_label: str = ""
    caveats: list[str] = field(default_factory=list)


def available(history: list[RateSnapshot], board: str = "counter") -> dict:
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

    lead = result.tenors[0]
    result.rows.sort(key=lambda r: (r.cells[lead].rate is None,
                                    -(r.cells[lead].rate or 0)))

    for tenor in result.tenors:
        offered_now = {b: rates_now[tenor][b] for b in banks if b in rates_now[tenor]}
        if len(set(offered_now.values())) > 1:
            result.highest[tenor] = max(offered_now, key=offered_now.get)
            result.lowest[tenor] = min(offered_now, key=offered_now.get)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = latest.captured_at[:10].replace("-", "")

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

    if query.wants_banks:
        for tenor in result.tenors:
            pairs = bank_rates.gaps_at(latest, tenor, banks, query.board)
            if pairs:
                result.gaps.append(pairs[0])
                result.insights.append(bank_rates.gap_sentence(pairs[0]))

    if query.wants_time and changes:
        _, short = PRESET_LABELS.get(query.preset, ("", "kỳ so sánh"))
        measured = [c for c in changes if c.change is not None]
        for moved in sorted(measured, key=lambda c: abs(c.change or 0), reverse=True):
            result.insights.append(bank_rates.change_sentence(moved, short))

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
