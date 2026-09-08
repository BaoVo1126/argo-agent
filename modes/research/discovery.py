"""
The fallback path: try the vetted domains for a topic's category, one by one.

Used only when the planner matched no catalogue entry. This file used to begin
with a search engine, and the URLs it scraped were whatever that engine ranked
first. That is gone. The addresses tried here come from
`modes/research/pool.py`, which is a list a person wrote down and can be read
in one sitting, and a topic whose category has no pool is refused rather than
widened -- see `registry.match_category`.

Losing the search engine costs reach and buys two things worth more.
Provenance stops depending on a ranking that changes between runs. And the
run becomes something a customer can watch: a fixed list tried in order, each
domain named as it is reached, each answer scored out loud. That is what
`trace.py` carries.

Three rules hold the path together.

**Only published tables are read.** The extractor looks for an HTML table with
a column that parses as dates and a column that parses as numbers, and takes
nothing else. A number pulled out of a sentence is an interpretation, and the
pipeline has no way to check it -- so rather than guess, this returns fewer
sources and says so.

That rule is also, measured against the real pools, the binding limit on how
much this path can find. Probing both pools against the live web returns zero
usable tables today, and the reason is not the addresses: most of these
publishers answer 200 with no `<table>` element on the page at all. Statistics
portals render their figures through PX-Web, a JSON API or a charting widget;
several .gov.vn hosts do not answer headless Chromium; imf.org replies 403.
The authoritative sources that *do* hand over a whole series in one request
are APIs, which is exactly why the ones already covered live in `sources.py`
as hand-written adapters rather than being discovered here. Reaching those
from a pool would mean a pool entry declaring an endpoint and an indicator
code, which is per-topic knowledge this path does not have -- so the honest
description of this module is a working, bounded search whose current yield on
these seventeen-domain pools is low, and which refuses rather than inventing
something when it comes back empty.

**A source is dropped early only when it could never pass.** The live score is
provenance plus structure; corroboration cannot be known until the other
sources are in. So the test at probe time is the source's *ceiling* -- what it
would score if every other source agreed with it. A ceiling below the
threshold means no later evidence can save it, and dropping it then is a fact
rather than a guess. Everything else goes forward and is decided by the real
scorer in `src/scoring/credibility.py`, which this file does not touch.

**A page is fetched once.** The probe navigates and reads the table, so by the
time a domain is accepted its rows are already in hand. The source it becomes
carries those rows instead of an instruction to go and get them again: asking
a ministry twice in ninety seconds for a page we already parsed is not
politeness this pipeline can afford to skip.
"""

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

# How long one address gets before the probe moves to the next. Shorter than
# the collector's allowance on purpose: this is a door being tried, not a
# source being read, and twelve addresses at thirty seconds each is a run
# nobody waits for.
PROBE_TIMEOUT_MS = 15000

# Fewer dated numbers than this on a page and there is no series there, only a
# coincidence. Same figure the table chooser uses, stated once.
MIN_PAIRS = 5

# Every table on the page, as a plain matrix. Choosing which one holds the
# series is done in Python, where the date and number parsers already live.
_TABLES_JS = r"""
() => Array.from(document.querySelectorAll('table')).slice(0, 12).map(table => ({
  rows: Array.from(table.rows).slice(0, 500).map(
    row => Array.from(row.cells).map(c => (c.innerText || '').trim())
  )
}))
"""


@dataclass
class PoolCandidate:
    """A vetted domain that answered with a usable table, and what it is worth."""

    domain: str
    label: str
    url: str
    title: str
    rows: list[dict] = field(default_factory=list)
    # Provenance + structure. Corroboration is not knowable yet.
    live_score: int = 0
    # What it would score if every other accepted source agreed with it.
    ceiling: int = 0
    tier_reason: str = ""


def _best_table(tables: list[dict], start: dt.date, end: dt.date) -> list[tuple] | None:
    """The table with the most usable (date, number) pairs inside the window."""
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
    """Open one address and take the dated series off it, if there is one."""
    page.goto(url, wait_until="domcontentloaded", timeout=PROBE_TIMEOUT_MS)
    title = (page.title() or "")[:120]
    pairs = _best_table(page.evaluate(_TABLES_JS), start, end)
    if not pairs:
        return [], title
    return [{"date": day, value_field: value} for day, value in pairs], title


def pool_source(candidate: PoolCandidate, value_field: str) -> Source:
    """A source built from a page the probe has already read.

    The plan is empty and the extractor hands back what the probe found. That
    is not a shortcut around the action registry: the navigation happened, in
    the same browser, moments ago, and the customer watched it in the trace.
    Repeating it would be a second request for a page already parsed, and the
    only thing it could change is whether the numbers still match -- which is
    a question about the site, not about this run.
    """
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
    """The pool, with any domain the planner named moved to the front.

    This is the one thing the model's `domain_hints` are still allowed to do,
    and it is the same thing they were allowed to do when a search engine
    supplied the candidates: reorder a list somebody else produced. A hint for
    a site outside the pool moves nothing, so a hallucinated domain cannot add
    itself to what gets fetched -- it can only fail to match.
    """
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
    """Walk the category's vetted domains until enough of them answer.

    Every decision is announced as it is taken, because a customer being told
    "we checked" after the fact is being asked to take it on trust, and this
    pipeline exists to avoid that.
    """
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
        # Two failures that look the same in a count and mean opposite things.
        # A site that never answered is an outage or a block, and the customer
        # can only wait. A site that answered without a data table is a
        # publisher who does not put this number in an HTML table, and no
        # amount of waiting changes that. Saying "không lấy được" for both
        # would send half of them looking for the wrong problem.
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

        # Handing over usable rows is what earns a domain its tier, and it is
        # the same rule the collector applies -- recorded here so the score the
        # customer is shown a second later is the real one rather than a zero
        # that will be corrected off-screen.
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
