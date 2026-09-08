"""
The customer-facing web app.

    python -m uvicorn web.main:app --reload      # http://127.0.0.1:8000

What this file mostly does is decide what *not* to send. The pipeline produces
scrape logs, coverage percentages, z-scores, chart-engine rule names, tier
arithmetic and a note about which model wrote the paragraph. None of it reaches
the browser. A customer needs to know which sources were used, how far the
number moved, which points were odd, and what that means -- and every one of
those is a sentence, not a metric.

The progress the page shows is a phase and a trace, not a log. `pipeline.run`
emits unindented lines for the stage it is entering and indented lines for
detail; only the former become "Đang thu thập số liệu…". Alongside them it
emits typed `TraceEvent`s -- this domain is being tried, it scored this much,
it was kept or dropped -- and those do reach the browser, because the searching
is the part a customer has no other way to see. Everything else the pipeline
knows still stops here. The operator running the server sees the lot on
stdout: different audiences, not different verbosity levels of one.

Three mechanics worth naming. The scrape runs in a worker thread, because
Playwright's sync API refuses to start inside a running asyncio loop and
rewriting the collector to suit a web page would be the tail wagging the dog.
The job's status is polled, because a job whose state is a string and whose
phase is another string is something a reader can hold in their head. And the
trace is *pushed*, over SSE, because polling it would put the events on a
one-second grid and the whole claim being made is that the customer is
watching the run rather than a replay of it.

**Why the trace is also on the poll response.** SSE is one more thing that can
fail -- a proxy that buffers, a tab restored from cache. The poll already runs,
so it carries the events too and the page renders whichever arrives; a run
whose stream never connected still shows its working, a second late.
"""

from __future__ import annotations

import datetime as dt
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydanticField

from modes.research import bank_rates, history, pipeline, rate_query, snapshots
from modes.research.pipeline import ResearchRequest
from modes.research.trace import Trace, TraceEvent
from src.timeseries import CALENDAR_PRESETS

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)

# Long enough for the yearly indicators, which are the whole reason the range
# is not capped at a year: inflation over two decades is a normal request.
MAX_RANGE_DAYS = 40 * 366
MAX_ANOMALIES_SHOWN = 5
HISTORY_SHOWN = 40

# What the form's checkboxes mean, in the vocabulary `src/scoring` uses.
TIER_VALUES = {"government", "academic", "bank", "press", "aggregator"}
COMPARISONS = {"auto", "month", "quarter", "year"}

app = FastAPI(title="Argo")


class RunRequest(BaseModel):
    topic: str = PydanticField(min_length=2, max_length=200)
    start: dt.date
    end: dt.date
    metric: str = PydanticField(default="", max_length=200)
    scope: str = PydanticField(default="", max_length=300)
    prefer: list[str] = PydanticField(default_factory=list)
    exclude: list[str] = PydanticField(default_factory=list)
    compare: str = "auto"
    notes: str = PydanticField(default="", max_length=1000)

    def to_pipeline(self) -> ResearchRequest:
        return ResearchRequest(
            topic=self.topic.strip(),
            start=self.start,
            end=self.end,
            metric=self.metric.strip(),
            scope=self.scope.strip(),
            notes=self.notes.strip(),
            # Anything the form did not send is dropped rather than trusted:
            # these values decide which sources run.
            prefer=tuple(t for t in self.prefer if t in TIER_VALUES),
            exclude=tuple(t for t in self.exclude if t in TIER_VALUES),
            compare=self.compare if self.compare in COMPARISONS else "auto",
        )


# How long a stream waits for the next event before sending a keep-alive.
# Proxies and browsers hang up on a connection that goes quiet, and a scrape
# can legitimately spend a minute inside one slow page load.
STREAM_HEARTBEAT_S = 15
# A stream that nobody is reading must not pin the job's events in memory
# forever, and a slow reader must not slow the scrape down. Past this depth the
# oldest events are dropped from *that listener's* queue only; the job's own
# list stays complete, so a reconnect still gets the whole trace.
STREAM_BACKLOG = 500


@dataclass
class Job:
    id: str
    status: str = "running"        # running | done | refused | failed
    phase: str = "Đang chuẩn bị…"
    error: str = ""
    payload: dict | None = None
    # Kept for the operator; never sent to the browser.
    log: list[str] = field(default_factory=list)
    # Sent to the browser, and the reason this file has a stream at all.
    events: list[dict] = field(default_factory=list)
    # One queue per open stream. A job with no watchers simply has none.
    listeners: list[queue.Queue] = field(default_factory=list)

    def publish(self, event: dict) -> None:
        """Record one trace event and hand it to whoever is watching.

        The position is stamped on before it goes out. EventSource reconnects
        on its own, and a reconnect replays the backlog, so without a number
        on each event a dropped connection would show the customer the whole
        run a second time.
        """
        with _LOCK:
            event = {**event, "i": len(self.events)}
            self.events.append(event)
            watchers = list(self.listeners)
        for watcher in watchers:
            try:
                watcher.put_nowait(event)
            except queue.Full:
                pass

    def subscribe(self) -> tuple[list[dict], queue.Queue]:
        """Everything so far, plus the queue for everything after it.

        Both under one lock, which is what makes the handover gapless: an
        event published between the snapshot and the subscription would
        otherwise be in neither.
        """
        with _LOCK:
            backlog = list(self.events)
            watcher: queue.Queue = queue.Queue(maxsize=STREAM_BACKLOG)
            self.listeners.append(watcher)
        return backlog, watcher

    def unsubscribe(self, watcher: queue.Queue) -> None:
        with _LOCK:
            if watcher in self.listeners:
                self.listeners.remove(watcher)

    def close_streams(self) -> None:
        """Tell every watcher the run is over, so their loops end."""
        with _LOCK:
            watchers = list(self.listeners)
        for watcher in watchers:
            try:
                watcher.put_nowait(None)
            except queue.Full:
                pass


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _direction_word(change: float) -> str:
    return "tăng" if change > 0 else "giảm" if change < 0 else "gần như không đổi"


def _sources(result: pipeline.ResearchResult) -> list[dict]:
    """The source list, which the customer gets whether or not a chart follows.

    A run that refuses is exactly when this matters most: "we could not verify
    this" is an assertion, and the customer is owed the working -- which sites
    were consulted and what each one scored. Sending only the refusal sentence
    would ask them to take it on trust, which is the posture this whole
    pipeline exists to avoid.
    """
    return [
        {
            "label": s.label,
            "site": s.site,
            "score": s.credibility.total if s.credibility else 0,
            "accepted": s.accepted,
            "tier": (s.credibility.lines[0].label if s.credibility and s.credibility.lines
                     else ""),
            "corroborated": bool(s.credibility and s.credibility.agrees_with),
            "verified": bool(s.credibility and s.credibility.verified),
            "points": s.valid_rows,
            "failed": not s.ok,
        }
        for s in result.sources
    ]


def _payload(result: pipeline.ResearchResult) -> dict:
    analysis = result.analysis
    metric = result.plan.metric_label if result.plan else result.topic
    period = analysis.periods[0] if analysis.periods else None

    return {
        "topic": result.topic,
        "metric": metric,
        "unit": analysis.unit,
        "caveats": result.caveats,
        "window": {
            "start": f"{analysis.first_date:%d/%m/%Y}",
            "end": f"{analysis.last_date:%d/%m/%Y}",
            "points": analysis.points,
            "cadence": analysis.cadence,
        },
        "sources": _sources(result),
        "summary": {
            "first": analysis.first_value,
            "last": analysis.last_value,
            "change": analysis.change,
            # "%" for a price, "điểm phần trăm" for a rate. The page prints
            # whichever it is handed rather than assuming one.
            "change_unit": analysis.unit_label,
            "direction": _direction_word(analysis.change),
            "minimum": analysis.minimum,
            "maximum": analysis.maximum,
            "period_label": period.label if period else "",
            "period_change": period.change if period else None,
            "period_unit": period.unit_label if period else "",
        },
        "anomalies": [
            {
                "date": f"{a.date:%d/%m/%Y}",
                "change": a.change,
                "change_unit": a.unit_label,
                "direction": a.direction,
                "value": a.value,
            }
            for a in analysis.anomalies[:MAX_ANOMALIES_SHOWN]
        ],
        "anomaly_total": len(analysis.anomalies),
        "chart": {
            "url": f"/outputs/{result.charts[0].name}" if result.charts else "",
            # Not lower-cased: the metric is a proper noun often enough
            # ("USD/VND", "SJC", "Việt Nam") that folding its case reads as a typo.
            "caption": f"Diễn biến {metric} từ {analysis.first_date:%d/%m/%Y} "
                       f"đến {analysis.last_date:%d/%m/%Y}",
            "insight": result.insight.text if result.insight else "",
        },
    }


def _worker(job: Job, request: RunRequest) -> None:
    def log(line: str) -> None:
        print(f"[{job.id}] {line}", flush=True)
        with _LOCK:
            job.log.append(line)
            if line and not line.startswith(" "):
                job.phase = line

    trace = Trace(sink=lambda event: job.publish(event.as_dict()))

    try:
        result = pipeline.run(request.to_pipeline(), output_dir=OUTPUTS, log=log,
                              trace=trace)
    except Exception as exc:
        with _LOCK:
            job.status = "failed"
            job.error = ("Không hoàn tất được yêu cầu. Bạn thử lại sau ít phút, "
                         "hoặc mô tả chủ đề cụ thể hơn.")
            job.log.append(f"{type(exc).__name__}: {exc}")
        print(f"[{job.id}] FAILED {type(exc).__name__}: {exc}", flush=True)
        job.close_streams()
        return

    with _LOCK:
        if result.refusal or not result.ok:
            job.status = "refused"
            job.error = (result.refusal
                         or "Không đủ số liệu để dựng biểu đồ cho khoảng thời gian này.")
            job.payload = {
                "metric": result.plan.metric_label if result.plan else result.topic,
                "sources": _sources(result),
                "caveats": result.caveats,
                "category": result.category,
            }
        else:
            job.status = "done"
            job.payload = _payload(result)
    job.close_streams()


@app.post("/api/run")
def start_run(request: RunRequest) -> dict:
    if request.end < request.start:
        raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu.")
    if (request.end - request.start).days > MAX_RANGE_DAYS:
        raise HTTPException(400, "Khoảng thời gian tối đa là 40 năm.")

    job = Job(id=uuid.uuid4().hex[:12])
    with _LOCK:
        _JOBS[job.id] = job
    threading.Thread(target=_worker, args=(job, request), daemon=True).start()
    return {"id": job.id}


@app.get("/api/run/{job_id}")
def poll_run(job_id: str, since: int = 0) -> dict:
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Phiên chạy không tồn tại.")
    # Deliberately narrow: status, one friendly phase, the trace of what was
    # tried, and the result or a reason. `since` lets a page that already has
    # the first events ask only for what it is missing.
    with _LOCK:
        events = job.events[max(since, 0):]
    return {"status": job.status, "phase": job.phase, "message": job.error,
            "result": job.payload, "events": events, "event_total": len(job.events)}


@app.get("/api/run/{job_id}/events")
def stream_events(job_id: str) -> StreamingResponse:
    """The trace, pushed as it happens.

    Server-sent events rather than a WebSocket: nothing here travels from the
    browser to the server, and a one-way stream that reconnects by itself is
    the smaller thing to get right. The generator is synchronous, so FastAPI
    runs it in a worker thread and a blocking `get` on the queue costs nothing
    but that thread.
    """
    with _LOCK:
        job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Phiên chạy không tồn tại.")

    return StreamingResponse(trace_frames(job), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        # nginx buffers by default, which would collect the whole run and
        # deliver it at the end -- the exact failure this endpoint exists to
        # avoid, and an invisible one in development.
        "X-Accel-Buffering": "no",
    })


def trace_frames(job: Job):
    """The SSE body for one job: everything so far, then everything after.

    A plain generator, deliberately, and not nested inside the route.
    Streaming is the one property of this endpoint a test client cannot
    observe -- it collects the whole response before handing it back, so a
    stream that buffered until the run ended would look identical to one that
    did not. Pulled directly, this generator can be asked the question that
    matters: does it hand over the first frames while the job is still
    running?
    """
    backlog, watcher = job.subscribe()
    try:
        for event in backlog:
            yield _frame(event)
        # A job that finished before anyone connected has nothing more to
        # send, and its watcher would otherwise wait out the timeout.
        while job.status == "running":
            try:
                event = watcher.get(timeout=STREAM_HEARTBEAT_S)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                break
            yield _frame(event)
        yield "event: end\ndata: {}\n\n"
    finally:
        job.unsubscribe(watcher)


def _frame(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


@app.get("/api/history")
def run_history() -> dict:
    """Past runs, for the second tab. Not a log: no traces, no scores broken
    down, no phases -- just what was asked and whether it came back."""
    entries = history.load()[:HISTORY_SHOWN]
    return {
        "runs": [
            {
                "at": entry.started_at,
                "topic": entry.topic,
                "metric": entry.metric,
                "window": entry.window,
                "seconds": entry.seconds,
                "outcome": entry.outcome,
                "summary": entry.summary,
                "sources_total": len(entry.sources),
                "sources_passed": entry.sources_passed,
                "sources": [{"label": s.label, "score": s.score, "accepted": s.accepted,
                             "ok": s.ok} for s in entry.sources],
            }
            for entry in entries
        ]
    }


# --- the savings-rate dashboard ------------------------------------------

@app.get("/api/dashboard")
def dashboard(tenor: int = bank_rates.HEADLINE_TENOR, banks: str = "") -> dict:
    """Everything the dashboard shows, from whatever has been captured.

    Read-only and cheap: it never scrapes. Capturing is a separate action, so
    opening the page a second time cannot hammer the source.
    """
    stored = snapshots.load()
    comparison = bank_rates.compare(stored, tenor=tenor)
    if comparison is None:
        return {"ready": False,
                "message": "Chưa có lần cập nhật nào. Bấm Cập nhật để lấy bảng lãi suất."}

    # Default to the three highest-paying banks, which is the comparison
    # someone opening the page is most likely to want. Three is also the
    # number of series colours that stay distinguishable.
    chosen = [b for b in banks.split(",") if b.strip()] or              [row.bank for row in comparison.rows[:bank_rates.MAX_TREND_BANKS]]
    chosen = [b for b in chosen if any(r.bank == b for r in comparison.rows)]
    chosen = chosen[:bank_rates.MAX_TREND_BANKS]

    chart_url = ""
    stamp = comparison.captured_at[:10].replace("-", "")
    path = OUTPUTS / f"lai_suat_{tenor}m_{stamp}.png"
    if bank_rates.render_trend(stored, chosen, path, tenor=tenor):
        chart_url = f"/outputs/{path.name}?t={comparison.captured_at}"

    check = comparison.crosscheck or {}
    return {
        "ready": True,
        "tenor": tenor,
        "captured_at": comparison.captured_at,
        "updates": comparison.snapshot_count,
        "has_history": comparison.has_history,
        "banks_available": [row.bank for row in comparison.rows],
        "banks_selected": chosen,
        "banks_missing": list(bank_rates.UNAVAILABLE),
        "kpis": {
            "top_bank": comparison.top_bank,
            "top_rate": round(comparison.top_rate, 2),
            "average": round(comparison.average, 2),
            "change": (round(comparison.average_change, 2)
                       if comparison.average_change is not None else None),
        },
        "tenors": comparison.tenors,
        "rows": [
            {"bank": row.bank, "big_four": row.is_big_four,
             "rates": {str(t): row.rates.get(t) for t in comparison.tenors}}
            for row in comparison.rows
        ],
        "highest": {str(t): b for t, b in comparison.highest.items()},
        "lowest": {str(t): b for t, b in comparison.lowest.items()},
        "chart": chart_url,
        "insight": bank_rates.insight_line(comparison, tenor),
        "crosscheck": {
            "checked": bool(check.get("checked")),
            "agrees": bool(check.get("agrees")),
            "tenors": check.get("tenors_compared") or [],
            "mismatched": check.get("mismatched") or [],
        },
    }


# --- the structured rate query -------------------------------------------
#
# Synchronous, unlike `/api/run`: this reads a JSON file and draws at most six
# charts, so there is no scrape to wait on and nothing to poll for. The charts
# are named after their own contents, so asking the same question twice costs
# one file check instead of a second render.

class CompareRequest(BaseModel):
    banks: list[str] = PydanticField(min_length=1, max_length=12)
    tenors: list[int] = PydanticField(min_length=1, max_length=12)
    mode: str = "banks"
    preset: str = "month"
    board: str = "counter"
    # Only read when preset is "custom"; the four together are one choice, and
    # a partial one is rejected rather than half-applied.
    current_start: dt.date | None = None
    current_end: dt.date | None = None
    previous_start: dt.date | None = None
    previous_end: dt.date | None = None

    def to_query(self) -> rate_query.RateQuery:
        preset = self.preset if self.preset in (
            *CALENDAR_PRESETS, rate_query.CUSTOM) else "month"
        current = previous = None
        if preset == rate_query.CUSTOM:
            current = (self.current_start, self.current_end)
            previous = (self.previous_start, self.previous_end)
            if not all(current + previous):
                raise HTTPException(400, "Cần chọn đủ ngày bắt đầu và kết thúc cho "
                                         "cả hai khoảng thời gian.")
            if current[1] < current[0] or previous[1] < previous[0]:
                raise HTTPException(400, "Ngày kết thúc phải sau ngày bắt đầu.")
        return rate_query.RateQuery(
            banks=tuple(dict.fromkeys(self.banks)),
            tenors=tuple(dict.fromkeys(self.tenors)),
            mode=self.mode if self.mode in rate_query.MODES else "banks",
            preset=preset,
            current=current,
            previous=previous,
            board=self.board if self.board in {"counter", "online"} else "counter",
        )


@app.get("/api/rates/options")
def rate_options(board: str = "counter") -> dict:
    """What the form may offer, taken from the captures rather than a constant."""
    return rate_query.available(snapshots.load(), board=board)


@app.post("/api/rates/compare")
def rate_compare(request: CompareRequest) -> dict:
    answer = rate_query.answer(request.to_query(), output_dir=OUTPUTS)
    if not answer.ok:
        return {"ok": False, "message": answer.message}

    def chart_url(path) -> str:
        # The capture time is on the query string so a fresh capture busts the
        # browser's cache even though the file name is content-addressed.
        return f"/outputs/{path.name}?t={answer.captured_at}"

    return {
        "ok": True,
        "mode": answer.mode,
        "board": answer.board,
        "captured_at": answer.captured_at,
        "updates": answer.updates,
        "tenors": answer.tenors,
        "period": {
            "label": answer.period_label,
            "current": answer.period_current,
            "previous": answer.period_previous,
        },
        "rows": [
            {
                "bank": row.bank,
                "big_four": row.is_big_four,
                "cells": {
                    str(tenor): {"rate": cell.rate, "change": cell.change,
                                 "note": cell.note}
                    for tenor, cell in row.cells.items()
                },
            }
            for row in answer.rows
        ],
        "highest": {str(t): b for t, b in answer.highest.items()},
        "lowest": {str(t): b for t, b in answer.lowest.items()},
        "insights": answer.insights,
        "caveats": answer.caveats,
        "charts": {
            "snapshot": {str(t): chart_url(p)
                         for t, p in answer.snapshot_charts.items()},
            "trend": {str(t): chart_url(p) for t, p in answer.trend_charts.items()},
        },
    }


@app.post("/api/refresh")
def refresh() -> dict:
    """Fetch today's board. Runs in a thread; the page polls for the phase."""
    job = Job(id=uuid.uuid4().hex[:12])
    with _LOCK:
        _JOBS[job.id] = job

    def work() -> None:
        def log(line: str) -> None:
            print(f"[{job.id}] {line}", flush=True)
            with _LOCK:
                if line and not line.startswith(" "):
                    job.phase = line
        try:
            result = bank_rates.capture(log=log)
        except Exception as exc:
            print(f"[{job.id}] FAILED {type(exc).__name__}: {exc}", flush=True)
            with _LOCK:
                job.status, job.error = "failed", (
                    "Không lấy được bảng lãi suất lúc này. Bạn thử lại sau ít phút.")
            return
        with _LOCK:
            if result.ok:
                snapshots.append(result.snapshot)
                job.status = "done"
            else:
                job.status = "failed"
                job.error = ("Không lấy được bảng lãi suất: "
                             + "; ".join(result.errors or ["nguồn không phản hồi"]))

    threading.Thread(target=work, daemon=True).start()
    return {"id": job.id}


@app.get("/api/updates")
def updates() -> dict:
    """When the board was captured, and whether each capture matched BIDV."""
    return {
        "updates": [
            {
                "at": s.captured_at,
                "banks": len(s.banks("counter")),
                "quotes": len(s.quotes),
                "source": s.source,
                "agrees": bool((s.crosscheck or {}).get("agrees")),
                "checked": bool((s.crosscheck or {}).get("checked")),
            }
            for s in reversed(snapshots.load())
        ][:60]
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
