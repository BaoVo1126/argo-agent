from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from modes.research import discovery, history
from modes.research.trace import Trace
from modes.research.collector import SourceResult, browser_page, collect
from modes.research.registry import (CATALOGUE, TopicEntry, match_category,
                                     match_keywords, planner_catalogue)
from modes.research.schema import Field, Schema, ValidationReport, validate
from modes.research.sources import Source
from src.chart_engine import ChartSpec, choose, render
from src.llm.insight import Insight, write as write_insight
from src.llm.planner import ResearchPlan, plan as make_plan
from src.scoring import CredibilityScore, HealthRecord, SourceEvidence, score
from src.scoring.domains import classify
from src.scoring.health import HIGH_TIERS

OUTPUT_DIR = Path("outputs")


@dataclass
class ResearchRequest:
    topic: str
    start: dt.date
    end: dt.date
    metric: str = ""                  
    scope: str = ""              
    prefer: tuple[str, ...] = ()     
    exclude: tuple[str, ...] = ()     
    compare: str = "auto"          
    notes: str = ""


@dataclass
class SourceReport:
    name: str
    label: str
    site: str
    url: str
    ok: bool
    raw_rows: int = 0
    valid_rows: int = 0
    coverage: float = 0.0
    elapsed_s: float = 0.0
    error: str = ""
    credibility: CredibilityScore | None = None

    @property
    def accepted(self) -> bool:
        return bool(self.credibility and self.credibility.accepted)


@dataclass
class ResearchResult:
    topic: str
    start: dt.date
    end: dt.date
    plan: ResearchPlan | None = None
    sources: list[SourceReport] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    report: ValidationReport | None = None
    analysis: object | None = None          
    spec: ChartSpec | None = None
    charts: list[Path] = field(default_factory=list)
    insight: Insight | None = None
    refusal: str = ""
    threshold_enforced: bool = Tru
    caveats: list[str] = field(default_factory=list)
    category: str = ""
    trace: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rows) and self.analysis is not None and not self.refusal

    @property
    def accepted_sources(self) -> list[SourceReport]:
        return [s for s in self.sources if s.accepted]

    @property
    def rejected_sources(self) -> list[SourceReport]:
        return [s for s in self.sources if s.ok and not s.accepted]


def _dates(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def _clip_window(entry, start: dt.date, end: dt.date) -> tuple[dt.date, dt.date, str]:
    limit = getattr(entry, "max_span_days", None)
    if not limit or (end - start).days <= limit:
        return start, end, ""
    clipped = end - dt.timedelta(days=limit)
    return clipped, end, (
        f"Nguồn này công bố theo từng ngày, nên hệ thống lấy {limit} ngày gần nhất "
        f"({clipped:%d/%m/%Y} – {end:%d/%m/%Y}) thay vì toàn bộ khoảng bạn chọn."
    )


def _resolve_sources(page, plan: ResearchPlan, start: dt.date, end: dt.date,
                     emit: Callable[[str], None], trace: Trace,
                     health: HealthRecord,
                     threshold: int) -> tuple[list[Source], TopicEntry | None, str, str]:
    keyword_key = match_keywords(plan.topic)
    if keyword_key:
        entry = CATALOGUE[keyword_key]
        if plan.registry_key and plan.registry_key != keyword_key:
            emit(f"    (mô hình đề xuất '{plan.registry_key}', nhưng từ khoá trong "
                 f"chủ đề khớp với '{keyword_key}' — dùng từ khoá)")
        plan.registry_key = keyword_key
    else:
        entry = CATALOGUE.get(plan.registry_key or "")

    if entry is not None:
        emit(f"    dùng bộ nguồn đã lập trình sẵn: {entry.metric_label}")
        trace.event("detail",
                    f"Đã có bộ nguồn viết sẵn cho đại lượng này: {entry.metric_label}")
        return entry.build(_dates(start, end)), entry, entry.category, ""

    category = match_category(plan.topic)
    if not category:
        return [], None, "", (
            "Hệ thống chưa hỗ trợ lĩnh vực này. Argo chỉ lấy số liệu từ danh sách "
            "nguồn đã được duyệt trước cho từng lĩnh vực, và chủ đề bạn nhập không "
            "thuộc lĩnh vực nào trong số đó. Hệ thống không tự đi tìm trên web để tránh "
            "đưa về số liệu không rõ nguồn gốc."
        )

    emit(f"    chưa có bộ nguồn sẵn, dò danh sách nguồn đã duyệt của lĩnh vực {category}")
    query = (plan.search_queries or [plan.topic])[0]
    sources = discovery.probe_pool(page, category, query, plan.value_field, start, end,
                                   threshold=threshold, health=health, trace=trace,
                                   hints=plan.domain_hints, log=emit)
    return sources, None, category, ""


def _validate_source(outcome: SourceResult, source: Source,
                     start: dt.date, end: dt.date) -> tuple[list[dict], ValidationReport]:
    schema = Schema(
        name=source.value_field,
        fields=[Field("date", "date", required=True),
                Field(source.value_field, "number", required=True)],
        key=("date",),
    )
    rows, report = validate(outcome.rows, schema)
    rows = [r for r in rows if start <= r["date"] <= end]
    return rows, report


def _merge(accepted: list[tuple[SourceReport, list[dict]]], value_field: str) -> list[dict]:
    ordered = sorted(accepted, key=lambda pair: pair[0].credibility.total, reverse=True)
    merged: dict[dt.date, dict] = {}
    for _, rows in ordered:
        for row in rows:
            merged.setdefault(row["date"], {"date": row["date"],
                                            value_field: row[value_field]})
    return [merged[day] for day in sorted(merged)]


def run(request: ResearchRequest, threshold: int = 60,
        model: str | None = None, headless: bool | None = None,
        output_dir: Path = OUTPUT_DIR,
        log: Callable[[str], None] | None = None,
        trace: Trace | None = None) -> ResearchResult:
    line_out = log or (lambda _line: None)
    tracer = trace if trace is not None else Trace()

    def emit(line: str) -> None:
        line_out(line)
        tracer.event("detail" if line.startswith(" ") else "phase", line.strip())

    started = time.monotonic()
    topic, start, end = request.topic, request.start, request.end
    result = ResearchResult(topic=topic, start=start, end=end)

    emit("Đang xác định loại dữ liệu cần tìm…")
    briefing = "\n".join(part for part in (
        topic,
        f"Chỉ số cần theo dõi: {request.metric}" if request.metric else "",
        f"Phạm vi: {request.scope}" if request.scope else "",
        f"Ghi chú thêm: {request.notes}" if request.notes else "",
    ) if part)
    plan = make_plan(briefing, start, end, planner_catalogue(), model=model)
    plan.topic = topic
    result.plan = plan
    emit(f"    đại lượng: {plan.metric_label}"
         + ("" if plan.from_model else " (khớp bằng từ khoá, không dùng mô hình)"))

    collected: list[tuple[SourceReport, list[dict]]] = []
    evidences: list[SourceEvidence] = []
    value_field = plan.value_field
    unit = plan.unit

    health = HealthRecord.load()

    with browser_page(headless) as page:
        sources, entry, category, refusal = _resolve_sources(
            page, plan, start, end, emit, tracer, health, threshold)
        result.category = category
        if refusal:
            result.refusal = refusal
            tracer.event("summary", refusal)
            emit("    chưa hỗ trợ lĩnh vực này — dừng lại, không tìm trên web mở")
            _remember(request, result, time.monotonic() - started, tracer)
            return result
        if entry is not None:
            start, end, clip_note = _clip_window(entry, start, end)
            if clip_note:
                result.caveats.append(clip_note)
                result.start, result.end = start, end
                emit(f"    {clip_note}")
                sources = entry.build(_dates(start, end))
            value_field, unit = entry.value_field, entry.unit
            plan.metric_label = entry.metric_label

        if request.exclude:
            kept, dropped = [], []
            for source in sources:
                (dropped if classify(source.url).tier.value in request.exclude
                 else kept).append(source.label)
            if dropped:
                result.caveats.append(
                    "Theo yêu cầu của bạn, hệ thống đã bỏ qua: " + ", ".join(dropped) + "."
                )
                sources = [s for s in sources
                           if classify(s.url).tier.value not in request.exclude]

        if request.prefer:
            sources.sort(key=lambda s: classify(s.url).tier.value not in request.prefer)

        if not sources:
            result.refusal = (
                "Không còn nguồn nào để lấy số liệu sau khi áp dụng các ràng buộc bạn "
                "đặt ra. Bạn thử nới bớt phần loại trừ."
                if request.exclude else
                "Đã dò qua danh sách nguồn đã duyệt của lĩnh vực này nhưng không trang nào "
                "công bố bảng số liệu theo ngày trong khoảng bạn chọn. Hệ thống không tìm "
                "thêm trên web mở. Bạn thử nới rộng khoảng thời gian hoặc mô tả chỉ số cụ thể hơn."
            )
            _remember(request, result, time.monotonic() - started, tracer)
            return result

        emit(f"Đang thu thập từ {len(sources)} nguồn…")
        for source in sources:
            outcome = collect(page, source, verbose=False)
            report = SourceReport(
                name=source.name, label=source.label, site=source.site,
                url=source.url, ok=outcome.ok, raw_rows=outcome.row_count,
                elapsed_s=round(outcome.elapsed_s, 1), error=outcome.error,
            )
            rows: list[dict] = []
            if outcome.ok:
                rows, validation = _validate_source(outcome, source, start, end)
                report.valid_rows = len(rows)
                report.coverage = round(validation.coverage(source.value_field), 1)
                if rows:
                    evidences.append(SourceEvidence(
                        name=source.name, url=source.url, rows=rows,
                        value_field=source.value_field, structured=source.structured,
                        label=source.label,
                    ))
                else:
                    report.ok = False
                    report.error = "không có số liệu nào nằm trong khoảng thời gian đã chọn"
            emit(f"    {source.label}: "
                 + (f"{report.valid_rows} mốc dữ liệu" if report.ok else "không lấy được"))
            collected.append((report, rows))
            result.sources.append(report)

    if not evidences:
        result.refusal = ("Không nguồn nào trả về số liệu dùng được trong khoảng thời gian "
                          "đã chọn. Chưa có biểu đồ nào được vẽ.")
        _remember(request, result, time.monotonic() - started, tracer)
        return result

    for report, rows in collected:
        if report.ok and rows:
            health.record_success(report.url, classify(report.url).tier, len(rows))
    health.save()
    result.threshold_enforced = health.threshold_active()
    if not result.threshold_enforced:
        result.caveats.append(
            "Hệ thống chưa xác minh được nguồn chính thức nào (cơ quan nhà nước "
            "hoặc tổ chức quốc tế), nên chưa áp dụng ngưỡng lọc tin cậy. Mọi nguồn "
            "lấy được số liệu đều được dùng, kèm điểm để bạn tự cân nhắc."
        )

    emit("Đang chấm độ tin cậy của từng nguồn…")
    scores = {s.source: s for s in score(evidences, threshold=threshold, health=health)}
    for report, _ in collected:
        report.credibility = scores.get(report.label)
        verdict = report.credibility
        if verdict is None:
            continue
        tracer.event("keep" if verdict.accepted else "drop",
                     f"{report.label}: {verdict.total}/100 — {verdict.verdict}",
                     domain=report.site, score=verdict.total, threshold=threshold)

    accepted = [(r, rows) for r, rows in collected if r.accepted and rows]
    if not accepted:
        best = max((r.credibility.total for r, _ in collected if r.credibility), default=0)
        scored = [r.credibility for r, _ in collected if r.credibility]
        official = [c for c in scored if c.tier in HIGH_TIERS and c.verified]
        if len(official) >= 2 and not any(c.agrees_with for c in official):
            names = " và ".join(sorted({c.source for c in official}))
            result.refusal = (
                f"{names} đều là nguồn chính thức, nhưng số liệu hai bên công bố "
                f"chênh nhau quá nhiều để coi là xác nhận lẫn nhau, nên không nguồn "
                f"nào đạt {threshold}/100. Đây là điểm đáng lưu ý về chính số liệu: "
                f"các tổ chức đang đưa ra những con số khác nhau cho cùng một chỉ số."
            )
        else:
            result.refusal = (
                f"Nguồn có điểm cao nhất chỉ đạt {best}/100, trong khi mức tối thiểu "
                f"để được dùng là {threshold}/100. Vì vậy hệ thống không hiển thị số "
                f"liệu. Số liệu có thể vẫn đúng, nhưng chưa có cơ quan công bố chính "
                f"thức hoặc nguồn độc lập nào xác nhận lại."
            )
        emit("    không nguồn nào đạt ngưỡng — dừng lại, không vẽ biểu đồ")
        _remember(request, result, time.monotonic() - started, tracer)
        return result

    emit(f"    {len(accepted)}/{len(collected)} nguồn đạt ngưỡng")
    tracer.event("summary", f"Đã xác nhận {len(accepted)}/{len(collected)} nguồn, "
                            f"đang tổng hợp số liệu")

    merged = _merge(accepted, value_field)
    schema = Schema(
        name=value_field,
        fields=[Field("date", "date", required=True),
                Field(value_field, "number", required=True, unit=unit)],
        key=("date",),
    )
    result.rows, result.report = validate(merged, schema)

    if len(result.rows) < 2:
        result.refusal = "Chỉ thu được một mốc dữ liệu, chưa đủ để vẽ xu hướng."
        _remember(request, result, time.monotonic() - started, tracer)
        return result

    emit("Đang phân tích xu hướng và điểm bất thường…")
    from src.timeseries import analyse  

    analysis = analyse(result.rows, value_field=value_field, unit=unit,
                       compare=request.compare)
    result.analysis = analysis

    emit("Đang vẽ biểu đồ…")
    result.spec = choose(result.rows, title=plan.metric_label)
    result.spec.y_labels = {value_field: f"{plan.metric_label} ({unit})" if unit
                            else plan.metric_label}
    result.spec.x_label = analysis.cadence.capitalize()
    sites = ", ".join(sorted({r.site for r, _ in accepted}))
    path = Path(output_dir) / f"{value_field}_{dt.date.today():%Y%m%d}.png"
    result.charts.append(render(
        result.spec, result.rows, path,
        subtitle=f"{analysis.first_date:%d/%m/%Y} – {analysis.last_date:%d/%m/%Y}"
                 f" · {analysis.points} mốc dữ liệu",
        source_note=f"Nguồn: {sites}",
        markers={value_field: [(a.date, a.value) for a in analysis.anomalies]},
    ))

    emit("Đang viết nhận định…")
    result.insight = write_insight(analysis, plan.metric_label, model=model)
    _remember(request, result, time.monotonic() - started, tracer)
    return result


def _remember(request: ResearchRequest, result: ResearchResult, seconds: float,
              trace: Trace | None = None) -> None:
    if trace is not None:
        result.trace = trace.snapshot()
    analysis = result.analysis
    if result.refusal:
        summary = result.refusal.split(".")[0][:140]
    elif analysis is not None:
        summary = (f"{analysis.points} mốc, {analysis.change:+.2f} "
                   f"{analysis.unit_label} cả kỳ")
    else:
        summary = ""

    try:
        history.append(history.RunEntry(
            started_at=history.now(),
            topic=request.topic,
            metric=result.plan.metric_label if result.plan else "",
            window=f"{request.start:%d/%m/%Y} – {request.end:%d/%m/%Y}",
            seconds=round(seconds, 1),
            outcome="refused" if result.refusal or not result.ok else "done",
            summary=summary,
            sources=[
                history.SourceOutcome(
                    label=s.label,
                    score=s.credibility.total if s.credibility else 0,
                    accepted=s.accepted, ok=s.ok, rows=s.valid_rows,
                )
                for s in result.sources
            ],
        ))
    except Exception:
        pass
