from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Callable

from modes.research import snapshots
from modes.research.collector import browser_page
from modes.research.snapshots import RateQuote, RateSnapshot

BOARD_URL = "https://webgia.com/lai-suat/"
BIDV_PAGE = "https://bidv.com.vn/vn/tra-cuu-lai-suat"
BIDV_ENDPOINT = "/ServicesBIDV/InterestDetailServlet"


TENORS = (1, 3, 6, 9, 12, 24, 36)

HEADLINE_TENOR = 12

WANTED = {
    "vietcombank": "Vietcombank",
    "bidv": "BIDV",
    "vietinbank": "VietinBank",
    "agribank": "Agribank",
    "mb": "MB",
    "vpbank": "VPBank",
    "tpbank": "TPBank",
}
UNAVAILABLE = ("Techcombank", "ACB", "Sacombank")

BIG_FOUR = ("Vietcombank", "BIDV", "VietinBank", "Agribank")

CROSSCHECK_TOLERANCE = 0.05

_BOARD_JS = r"""
() => Array.from(document.querySelectorAll('table')).map(t => {
  let heading = '';
  let node = t.parentElement, hops = 0;
  while (node && hops < 3) {
    const h = node.querySelector('h1,h2,h3,h4');
    if (h) { heading = (h.innerText || '').trim(); break; }
    node = node.parentElement; hops++;
  }
  const rows = Array.from(t.rows).map(
    r => Array.from(r.cells).map(c => (c.innerText || '').trim()));
  return { heading: heading, rows: rows };
})
"""

_BIDV_JS = r"""
async (path) => {
  const res = await fetch(path, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return await res.json();
}
"""


def _rate(cell: str) -> float | None:
    text = (cell or "").strip().replace("%", "").replace(",", ".")
    if not text or text in {"-", "--", "—"}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0 <= value <= 25 else None


def _tenor(label: str) -> int | None:
    match = re.search(r"(\d{1,2})\s*tháng", (label or "").lower())
    return int(match.group(1)) if match else None


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _board_kind(heading: str) -> str | None:
    text = (heading or "").lower()
    if "trực tuyến" in text or "online" in text:
        return "online"
    if "quầy" in text:
        return "counter"
    return None


def parse_board(tables: list) -> list[RateQuote]:
    quotes: list[RateQuote] = []
    for entry in tables:
        heading = entry.get("heading", "") if isinstance(entry, dict) else ""
        table = entry.get("rows", []) if isinstance(entry, dict) else entry
        board = _board_kind(heading)
        if board is None:
            continue
        quotes.extend(_parse_one(table, board))
    return quotes


def _parse_one(table: list, board: str) -> list[RateQuote]:
    header_row, header_index = None, None
    for index, row in enumerate(table[:3]):
        if sum(1 for cell in row if _tenor(cell)) >= 4:
            header_row, header_index = row, index
            break
    if header_row is None:
        return []

    columns = {position: _tenor(cell) for position, cell in enumerate(header_row)
               if _tenor(cell) in TENORS}
    if not columns:
        return []

    quotes: list[RateQuote] = []
    for row in table[header_index + 1:]:
        if len(row) < 2:
            continue
        display = WANTED.get(_normalise(row[0]))
        if not display:
            continue
        for position, tenor in columns.items():
            value = _rate(row[position + 1]) if position + 1 < len(row) else None
            if value is not None:
                quotes.append(RateQuote(display, tenor, value, board))
    return quotes


def parse_bidv(payload: dict) -> dict[int, float]:
    rows = ((payload or {}).get("hcm") or {}).get("data") or []
    out: dict[int, float] = {}
    for row in rows:
        tenor = _tenor(row.get("title_vi", ""))
        value = _rate(row.get("VND", ""))
        if tenor in TENORS and value is not None:
            out[tenor] = value
    return out


@dataclass
class CaptureResult:
    snapshot: RateSnapshot | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.snapshot is not None and bool(self.snapshot.quotes)


def capture(headless: bool | None = None,
            log: Callable[[str], None] | None = None) -> CaptureResult:
    emit = log or (lambda _line: None)
    result = CaptureResult()
    quotes: list[RateQuote] = []
    official: dict[int, float] = {}

    with browser_page(headless) as page:
        emit("Đang đọc bảng lãi suất các ngân hàng…")
        try:
            page.goto(BOARD_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            quotes = parse_board(page.evaluate(_BOARD_JS))
            emit(f"    lấy được {len(quotes)} mức lãi suất của "
                 f"{len({q.bank for q in quotes})} ngân hàng "
                 f"({len({q.board for q in quotes})} bảng: tại quầy / trực tuyến)")
        except Exception as exc:
            result.errors.append(f"bảng tổng hợp: {type(exc).__name__}")

        emit("Đang đối chiếu với số BIDV tự công bố…")
        try:
            page.goto(BIDV_PAGE, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(3000)
            official = parse_bidv(page.evaluate(_BIDV_JS, BIDV_ENDPOINT))
            emit(f"    BIDV công bố {len(official)} kỳ hạn")
        except Exception as exc:
            result.errors.append(f"BIDV: {type(exc).__name__}")

    if not quotes:
        return result

    board_bidv = {q.tenor_months: q.rate_pct for q in quotes
                  if q.bank == "BIDV" and q.board == "counter"}
    shared = sorted(set(board_bidv) & set(official))
    mismatched = [t for t in shared
                  if abs(board_bidv[t] - official[t]) > CROSSCHECK_TOLERANCE]
    crosscheck = {
        "bank": "BIDV",
        "tenors_compared": shared,
        "mismatched": mismatched,
        "agrees": bool(shared) and not mismatched,
        "checked": bool(shared),
    }
    if shared:
        emit(f"    đối chiếu {len(shared)} kỳ hạn: "
             + ("khớp toàn bộ" if not mismatched else f"lệch ở {mismatched}"))

    result.snapshot = RateSnapshot(
        captured_at=snapshots.now(),
        source="webgia.com",
        quotes=quotes,
        crosscheck=crosscheck,
    )
    return result

@dataclass
class BankRow:
    bank: str
    rates: dict[int, float]
    is_big_four: bool = False

    def best_tenor(self) -> int | None:
        return max(self.rates, key=self.rates.get) if self.rates else None


@dataclass
class Comparison:
    captured_at: str
    board: str = "counter"
    previous_at: str = ""
    tenors: list[int] = field(default_factory=list)
    rows: list[BankRow] = field(default_factory=list)
    highest: dict[int, str] = field(default_factory=dict)
    lowest: dict[int, str] = field(default_factory=dict)
    top_bank: str = ""
    top_rate: float = 0.0
    average: float = 0.0
    average_change: float | None = None
    movers: list[tuple[str, float]] = field(default_factory=list)
    crosscheck: dict = field(default_factory=dict)
    snapshot_count: int = 0

    @property
    def has_history(self) -> bool:
        return self.snapshot_count >= 2


def compare(history: list[RateSnapshot], tenor: int = HEADLINE_TENOR,
            board: str = "counter") -> Comparison | None:
    if not history:
        return None

    latest = history[-1]
    previous = history[-2] if len(history) >= 2 else None
    result = Comparison(captured_at=latest.captured_at,
                        board=board,
                        previous_at=previous.captured_at if previous else "",
                        tenors=[t for t in TENORS if t in set(latest.tenors(board))],
                        crosscheck=latest.crosscheck,
                        snapshot_count=len(history))

    for bank in latest.banks(board):
        rates = {q.tenor_months: q.rate_pct for q in latest.quotes
                 if q.bank == bank and q.board == board}
        result.rows.append(BankRow(bank=bank, rates=rates, is_big_four=bank in BIG_FOUR))
    
    result.rows.sort(key=lambda r: r.rates.get(tenor, -1), reverse=True)

    for column in result.tenors:
        offered = {r.bank: r.rates[column] for r in result.rows if column in r.rates}
        if offered:
            result.highest[column] = max(offered, key=offered.get)
            result.lowest[column] = min(offered, key=offered.get)

    headline = latest.by_tenor(tenor, board)
    if headline:
        result.top_bank = max(headline, key=headline.get)
        result.top_rate = headline[result.top_bank]
        result.average = sum(headline.values()) / len(headline)

    if previous:
        before = previous.by_tenor(tenor, board)
        if before:
            result.average_change = result.average - sum(before.values()) / len(before)
            moved = [(bank, headline[bank] - before[bank])
                     for bank in headline if bank in before
                     and abs(headline[bank] - before[bank]) >= 0.01]
            result.movers = sorted(moved, key=lambda pair: abs(pair[1]), reverse=True)

    return result


def _vn(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def insight_line(comparison: Comparison, tenor: int = HEADLINE_TENOR) -> str:
    if not comparison or not comparison.top_bank:
        return ""

    parts = [f"Ngân hàng {comparison.top_bank} hiện trả cao nhất kỳ hạn {tenor} tháng: "
             f"{_vn(comparison.top_rate)}%/năm."]
    parts.append(f"Trung bình {len(comparison.rows)} ngân hàng đang ở "
                 f"{_vn(comparison.average)}%/năm.")

    if comparison.average_change is not None:
        if abs(comparison.average_change) < 0.005:
            parts.append("Mặt bằng chung không đổi so với lần cập nhật trước.")
        else:
            way = "tăng" if comparison.average_change > 0 else "giảm"
            parts.append(f"Mặt bằng chung {way} {_vn(abs(comparison.average_change))} "
                         f"điểm phần trăm so với lần cập nhật trước.")
            if comparison.movers:
                bank, delta = comparison.movers[0]
                moved = "tăng" if delta > 0 else "giảm"
                parts.append(f"Thay đổi mạnh nhất là {bank}, {moved} "
                             f"{_vn(abs(delta))} điểm phần trăm.")
    return " ".join(parts)


@dataclass(frozen=True)
class BankGap:
    higher: str
    lower: str
    tenor: int
    gap: float                 
    higher_rate: float = 0.0
    lower_rate: float = 0.0


def gaps_at(snapshot: RateSnapshot, tenor: int, banks: list[str],
            board: str = "counter") -> list[BankGap]:
    rates = snapshot.by_tenor(tenor, board)
    offered = [(bank, rates[bank]) for bank in banks if bank in rates]

    out: list[BankGap] = []
    for i, (bank_a, rate_a) in enumerate(offered):
        for bank_b, rate_b in offered[i + 1:]:
            higher, lower = ((bank_a, rate_a), (bank_b, rate_b))                 if rate_a >= rate_b else ((bank_b, rate_b), (bank_a, rate_a))
            out.append(BankGap(higher=higher[0], lower=lower[0], tenor=tenor,
                               gap=higher[1] - lower[1],
                               higher_rate=higher[1], lower_rate=lower[1]))
    return sorted(out, key=lambda g: g.gap, reverse=True)


@dataclass
class RateChange:
    bank: str
    tenor: int
    current: float | None = None
    previous: float | None = None
    change: float | None = None
    note: str = ""


def rate_changes(history: list[RateSnapshot], banks: list[str], tenors: list[int],
                 current: tuple[dt.date, dt.date], previous: tuple[dt.date, dt.date],
                 board: str = "counter") -> list[RateChange]:
    from src.timeseries import compare_windows

    out: list[RateChange] = []
    for bank in banks:
        for tenor in tenors:
            rows = snapshots.series(history, bank, tenor, board)
            verdict = compare_windows(rows, current, previous,
                                      value_field="rate_pct", unit="%")
            if verdict is None:
                covered = {r["date"] for r in rows}
                missing = ("kỳ hiện tại"
                           if not any(current[0] <= d <= current[1] for d in covered)
                           else "kỳ so sánh")
                out.append(RateChange(
                    bank=bank, tenor=tenor,
                    note=f"Chưa có lần cập nhật nào trong {missing}"
                         if rows else "Chưa có số liệu nào cho ngân hàng này",
                ))
                continue
            out.append(RateChange(
                bank=bank, tenor=tenor,
                current=verdict.current_mean,
                previous=verdict.previous_mean,
                change=verdict.change,
            ))
    return out

def gap_sentence(gap: BankGap) -> str:
    if gap.gap < 0.005:
        return (f"{gap.higher} và {gap.lower} đang trả bằng nhau ở kỳ hạn "
                f"{gap.tenor} tháng ({_vn(gap.higher_rate)}%/năm).")
    return (f"{gap.higher} trả cao hơn {gap.lower} {_vn(gap.gap)} điểm phần trăm "
            f"ở kỳ hạn {gap.tenor} tháng.")


def change_sentence(change: RateChange, previous_label: str) -> str:
    if change.change is None:
        return f"{change.bank}, kỳ hạn {change.tenor} tháng: {change.note}."
    if abs(change.change) < 0.005:
        return (f"{change.bank} hiện không đổi so với {previous_label} "
                f"ở kỳ hạn {change.tenor} tháng.")
    way = "tăng" if change.change > 0 else "giảm"
    return (f"{change.bank} hiện {way} {_vn(abs(change.change))} điểm phần trăm "
            f"so với {previous_label} ở kỳ hạn {change.tenor} tháng.")

MAX_TREND_BANKS = 3


def trend_rows(history: list[RateSnapshot], banks: list[str],
               tenor: int = HEADLINE_TENOR, board: str = "counter") -> list[dict]:
    rows = []
    for snapshot in history:
        board_rates = snapshot.by_tenor(tenor, board)
        row = {"date": snapshot.captured_date}
        for bank in banks:
            if bank in board_rates:
                row[bank] = board_rates[bank]
        if len(row) > 1:
            rows.append(row)
    return rows


def render_snapshot(snapshot: RateSnapshot, banks: list[str], tenor: int, out_path,
                    board: str = "counter"):
    rates = snapshot.by_tenor(tenor, board)
    rows = [{"bank": bank, "rate_pct": rates[bank]} for bank in banks if bank in rates]
    if len(rows) < 2:
        return None

    from src.chart_engine import choose, render

    spec = choose(rows, title=f"Lãi suất kỳ hạn {tenor} tháng theo ngân hàng")
    spec.x_label = "Ngân hàng"
    spec.y_labels = {"rate_pct": "Lãi suất (%/năm)"}
    return render(
        spec, rows, out_path,
        subtitle=f"{'Gửi tại quầy' if board == 'counter' else 'Gửi trực tuyến'}"
                 f" · cập nhật {snapshot.captured_at[:10]}",
        source_note="Nguồn: webgia.com, đối chiếu với BIDV",
    )


def render_trend(history: list[RateSnapshot], banks: list[str], out_path,
                 tenor: int = HEADLINE_TENOR, board: str = "counter"):
    chosen = list(banks)[:MAX_TREND_BANKS]
    rows = trend_rows(history, chosen, tenor, board)
    if len(rows) < 2 or not chosen:
        return None

    from src.chart_engine import choose, render

    spec = choose(rows, title=f"Lãi suất kỳ hạn {tenor} tháng theo thời gian")
    spec.x_label = "Ngày cập nhật"
    spec.y_labels = {bank: bank for bank in chosen}
    return render(
        spec, rows, out_path,
        subtitle=f"Gửi tại quầy · {len(rows)} lần cập nhật",
        source_note="Nguồn: webgia.com, đối chiếu với BIDV",
    )
