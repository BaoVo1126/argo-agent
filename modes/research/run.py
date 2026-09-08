"""
Run research mode from the terminal.

    python -m modes.research.run "tỷ giá USD/VND" --from 2026-06-01 --to 2026-08-31
    python -m modes.research.run "giá vàng SJC" --days 90 --model qwen2.5:7b

The web UI calls the same `pipeline.run`, so what prints here and what a
customer sees come from one place. The difference is only how much is shown:
this prints the working, the UI prints the conclusion.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from modes.research import pipeline
from modes.research.pipeline import ResearchRequest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Argo — research & viz")
    parser.add_argument("topic", help="chủ đề, viết tự do")
    parser.add_argument("--from", dest="start", help="ngày bắt đầu, YYYY-MM-DD")
    parser.add_argument("--to", dest="end", help="ngày kết thúc, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=90,
                        help="dùng khi không truyền --from/--to (mặc định 90)")
    parser.add_argument("--threshold", type=int, default=60,
                        help="ngưỡng điểm tin cậy (mặc định 60)")
    parser.add_argument("--model",
                        help="tên model Ollama; bỏ trống để tự chọn model nhỏ nhất "
                             "có hỗ trợ tool calling")
    parser.add_argument("--metric", default="", help="chỉ số cần theo dõi")
    parser.add_argument("--scope", default="", help="ràng buộc và phạm vi, ví dụ khu vực")
    parser.add_argument("--exclude", default="", help="bỏ qua loại nguồn, ngăn cách bằng dấu phẩy "
                                                      "(government/academic/bank/press/aggregator)")
    parser.add_argument("--prefer", default="", help="ưu tiên loại nguồn, cùng danh sách như trên")
    parser.add_argument("--compare", default="auto", choices=("auto", "month", "quarter", "year"),
                        help="mức so sánh giữa hai kỳ")
    parser.add_argument("--notes", default="", help="ghi chú thêm cho phần lập kế hoạch")
    parser.add_argument("--headed", action="store_true", help="hiện cửa sổ trình duyệt")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252, which cannot encode Vietnamese.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = _parse_args(argv)
    end = dt.date.fromisoformat(args.end) if args.end else dt.date.today()
    start = (dt.date.fromisoformat(args.start) if args.start
             else end - dt.timedelta(days=args.days))

    print("=" * 78)
    print(f"ARGO · research & viz    {start:%d/%m/%Y} → {end:%d/%m/%Y}")
    print(f"chủ đề: {args.topic}")
    print("-" * 78)

    def tiers(value: str) -> tuple[str, ...]:
        return tuple(t.strip().lower() for t in value.split(",") if t.strip())

    result = pipeline.run(
        ResearchRequest(
            topic=args.topic, start=start, end=end,
            metric=args.metric, scope=args.scope, notes=args.notes,
            prefer=tiers(args.prefer), exclude=tiers(args.exclude),
            compare=args.compare,
        ),
        threshold=args.threshold, model=args.model,
        headless=not args.headed, log=print,
    )

    print("-" * 78)
    print("NGUỒN")
    for source in result.sources:
        score = source.credibility
        head = (f"{score.total:>3}/{score.threshold}  "
                f"{'ĐẠT ' if score.accepted else 'LOẠI'}" if score else "  —  ----")
        print(f"  {head}  {source.label:<24} {source.site:<24} "
              f"{source.valid_rows:>4} mốc  {source.elapsed_s:>5.1f}s")
        if source.error:
            print(f"        {source.error[:110]}")
        for line in (score.lines if score else []):
            print(f"        +{line.points:<3} {line.label}")

    for caveat in result.caveats:
        print("-" * 78)
        print("LƯU Ý: " + caveat)

    if result.refusal:
        print("-" * 78)
        print("DỪNG LẠI: " + result.refusal)
        return 2

    analysis = result.analysis
    print("-" * 78)
    print("PHÂN TÍCH")
    print(f"  {analysis.points} mốc, {analysis.first_date} → {analysis.last_date}")
    print(f"  {analysis.first_value:,.2f} → {analysis.last_value:,.2f} {analysis.unit}"
          f"   ({analysis.change:+.2f} {analysis.unit_label}, {analysis.direction})")
    for period in analysis.periods:
        print(f"  {period.label}: {period.change:+.2f} {period.unit_label}")
    print(f"  biến động mỗi {analysis.cadence}: {analysis.volatility:.3f} "
          f"{analysis.unit_label}")
    for anomaly in analysis.anomalies[:5]:
        print(f"  bất thường {anomaly.date} {anomaly.change:+.2f} {anomaly.unit_label} "
              f"(z={anomaly.z_score:+.1f}, {'+'.join(anomaly.methods)})")

    print("-" * 78)
    print(f"BIỂU ĐỒ  {result.spec.chart_type.value} — {result.spec.reason}")
    for path in result.charts:
        print(f"         {path.resolve()}")

    print("-" * 78)
    insight = result.insight
    print(f"NHẬN ĐỊNH ({insight.origin})")
    if insight.rejected_numbers:
        print(f"  [đã loại bản do mô hình viết: {insight.rejected_numbers}]")
    print("  " + insight.text)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
