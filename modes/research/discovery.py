from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Callable

from modes.research import pool
from modes.research.schema import parse_date, parse_number
from modes.research.sources import Source
from modes.research.trace import Trace
from src.scoring.credibility import CONSENSUS_POINTS_MAX, STRUCTURE_POINTS
from src.scoring.domains import classify
from src.scoring.health import SUSPENSION_DAYS, HealthRecord

PROBE_TIMEOUT_MS = 15000

MIN_PAIRS = 5

_TABLES_JS = r"""
() => Array.from(document.querySelectorAll('table')).slice(0, 12).map(table => ({
  rows: Array.from(table.rows).slice(0, 500).map(
    row => Array.from(row.cells).map(c => (c.innerText || '').trim())
  )
}))
"""


@dataclass
class PoolCandidate:
    domain: str
    label: str
    url: str
    title: str
    rows: list[dict] = field(default_factory=list)
    live_score: int = 0
    ceiling: int = 0
    tier_reason: str = ""


def _best_table(tables: list[dict], start: dt.date, end: dt.date) -> list[tuple] | None:
    best: list[tuple] | None = None

    for table in tables:
        rows = [r for r in table.get("rows") or [] if len(r) >= 2]
        if len(rows) < MIN_PAIRS:
            continue
        width = min(len(r) for r in rows)

        for date_col in range(min(width, 4)):
            dates = [parse_date(r[date_col]) for r in rows]
            if sum(d is not None for d in dates) < max(MIN_PAIRS, len(rows) * 0.6):
                continue
            for value_col in range(width):
                if value_col == date_col:
                    continue
                pairs = [
                    (d, parse_number(r[value_col]))
                    for d, r in zip(dates, rows)
                    if d is not None and start <= d <= end
                ]
                pairs = [(d, v) for d, v in pairs if v is not None]
                if len(pairs) >= MIN_PAIRS and (best is None or len(pairs) > len(best)):
                    best = pairs

    return best


def _read_table(page, url: str, value_field: str,
                start: dt.date, end: dt.date) -> tuple[list[dict], str]:
    page.goto(url, wait_until="domcontentloaded", timeout=PROBE_TIMEOUT_MS)
    title = (page.title() or "")[:120]
    pairs = _best_table(page.evaluate(_TABLES_JS), start, end)
    if not pairs:
        return [], title
    return [{"date": day, value_field: value} for day, value in pairs], title


def pool_source(candidate: PoolCandidate, value_field: str) -> Source:
    rows = list(candidate.rows)
    return Source(
        name="pool_" + re.sub(r"[^a-z0-9]+", "_", candidate.domain)[:24],
        label=candidate.label,
        site=candidate.domain,
        url=candidate.url,
        plan=[],
        extract=lambda _page: rows,
        value_field=value_field,
        note=candidate.title or "Trang dữ liệu trên nguồn đã được duyệt trước",
        meta={"from_pool": True, "live_score": candidate.live_score},
    )


def _ordered(domains: tuple[pool.PoolDomain, ...],
             hints: list[str] | None) -> list[pool.PoolDomain]:
    wanted = {h.lower().removeprefix("www.") for h in (hints or [])}
    if not wanted:
        return list(domains)
    return sorted(domains, key=lambda d: not any(
        d.domain == h or d.domain.endswith("." + h) for h in wanted))


def probe_pool(page, category: str, query: str, value_field: str,
               start: dt.date, end: dt.date, *, threshold: int,
               health: HealthRecord, trace: Trace,
               hints: list[str] | None = None,
               log: Callable[[str], None] | None = None) -> list[Source]:
    emit = log or (lambda _line: None)
    domains = _ordered(pool.for_category(category), hints)
    if not domains:
        return []

    trace.event("phase", f"Đang dò {len(domains)} nguồn đã duyệt trong lĩnh vực này…")
    kept: list[PoolCandidate] = []
    probed = 0

    for entry in domains:
        if len(kept) >= pool.MAX_ACCEPTED:
            trace.event("skip", f"Đã đủ {len(kept)} nguồn, dừng dò để không làm phiền "
                                f"các trang còn lại")
            break
        if probed >= pool.MAX_PROBES:
            trace.event("skip", f"Đã thử {probed} nguồn trong lượt này, tạm dừng ở đây")
            break

        note = health.suspension_note(entry.domain)
        if note:
            trace.event("skip", f"Bỏ qua {entry.domain} — {note}", domain=entry.domain)
            emit(f"    bỏ qua {entry.domain}: {note}")
            continue

        probed += 1
        trace.event("probe", f"Đang kiểm tra {entry.domain}…", domain=entry.domain)
        emit(f"    đang kiểm tra {entry.domain}")

        rows: list[dict] = []
        title = ""
        hit_url = ""
        reached = False
        last_error = ""
        for url in entry.urls(query):
            try:
                rows, title = _read_table(page, url, value_field, start, end)
                reached = True
            except Exception as exc:
                last_error = type(exc).__name__
                continue
            if rows:
                hit_url = url
                break

        if not rows:
            why = ("mở được trang nhưng không có bảng số liệu theo ngày trong "
                   "khoảng đã chọn" if reached else
                   f"không truy cập được ({last_error or 'không phản hồi'})")
            rested = health.record_failure(f"https://{entry.domain}/",
                                           classify(entry.domain).tier, why)
            trace.event("miss", f"{entry.domain}: {why}", domain=entry.domain)
            emit(f"    {entry.domain}: {why}")
            if rested:
                trace.event("suspend",
                            f"{entry.domain} hỏng nhiều lần liên tiếp — tạm ngưng "
                            f"{SUSPENSION_DAYS} ngày. Nguồn này vẫn nằm trong danh "
                            f"sách và sẽ được thử lại sau đó.", domain=entry.domain)
                emit(f"    {entry.domain}: tạm ngưng {SUSPENSION_DAYS} ngày")
            continue

        verdict = classify(hit_url)
        health.record_success(hit_url, verdict.tier, len(rows))
        live = verdict.points + STRUCTURE_POINTS
        ceiling = live + CONSENSUS_POINTS_MAX
        candidate = PoolCandidate(
            domain=entry.domain, label=entry.label, url=hit_url, title=title,
            rows=rows, live_score=live, ceiling=ceiling, tier_reason=verdict.reason,
        )
        trace.event("hit", f"{entry.domain} trả về {len(rows)} mốc dữ liệu — "
                           f"{verdict.reason}", domain=entry.domain)

        if ceiling < threshold:
            trace.event("drop",
                        f"Không đạt, loại bỏ: {live}/100 và dù có nguồn khác xác nhận "
                        f"cũng chỉ tới {ceiling}/100, dưới mức {threshold}/100",
                        domain=entry.domain, score=live, threshold=threshold)
            emit(f"    {entry.domain}: loại (trần {ceiling}/100 < {threshold})")
            continue

        kept.append(candidate)
        if live >= threshold:
            trace.event("keep", f"Đạt ngưỡng {live}/100 — đưa vào danh sách dùng",
                        domain=entry.domain, score=live, threshold=threshold)
        else:
            trace.event("keep", f"Tạm giữ lại ở {live}/100, cần một nguồn khác xác "
                                f"nhận mới đủ {threshold}/100",
                        domain=entry.domain, score=live, threshold=threshold)
        emit(f"    {entry.domain}: giữ lại ({live}/100)")

    trace.event("summary",
                f"Đã xác nhận {len(kept)}/{probed} nguồn, đang tổng hợp số liệu…")
    health.save()
    return [pool_source(c, value_field) for c in kept]
