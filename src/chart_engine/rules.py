from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from statistics import median

from src.chart_engine.theme import MAX_SERIES

DUAL_AXIS_RATIO = 5.0
MAX_BAR_CATEGORIES = 25

SPARSE_MAX_POINTS = 30
SPARSE_MIN_GAP_DAYS = 25


class Kind(str, Enum):
    TEMPORAL = "temporal"
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    EMPTY = "empty"


class ChartType(str, Enum):
    LINE = "line"
    DUAL_AXIS_LINE = "dual_axis_line"
    BAR = "bar"
    HISTOGRAM = "histogram"
    SCATTER = "scatter"


@dataclass
class ChartSpec:
    chart_type: ChartType
    x: str | None
    ys: list[str]
    reason: str
    secondary_y: str | None = None
    title: str = ""
    x_label: str = ""
    y_labels: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        axes = " + ".join(self.ys) if self.ys else "-"
        return f"{self.chart_type.value}({self.x} -> {axes}): {self.reason}"


def classify(values: list) -> Kind:
    present = [v for v in values if v is not None and v != ""]
    if not present:
        return Kind.EMPTY
    if all(isinstance(v, (dt.date, dt.datetime)) for v in present):
        return Kind.TEMPORAL
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return Kind.NUMERIC
    return Kind.CATEGORICAL


def profile(rows: list[dict]) -> dict[str, Kind]:
    columns: dict[str, list] = {}
    for row in rows:
        for key, value in row.items():
            columns.setdefault(key, []).append(value)
    return {name: classify(values) for name, values in columns.items()}


def _median_gap_days(rows: list[dict], column: str) -> int:
    stamps = sorted(r[column] for r in rows if r.get(column) is not None)
    if len(stamps) < 2:
        return 0
    gaps = sorted((b - a).days for a, b in zip(stamps, stamps[1:]))
    return gaps[len(gaps) // 2]


def _typical(rows: list[dict], column: str) -> float:
    values = [abs(r[column]) for r in rows if isinstance(r.get(column), (int, float))]
    return median(values) if values else 0.0


def choose(rows: list[dict], title: str = "") -> ChartSpec:
    if not rows:
        raise ValueError("chart_engine: no rows to plot")

    kinds = profile(rows)
    temporal = [c for c, k in kinds.items() if k is Kind.TEMPORAL]
    numeric = [c for c, k in kinds.items() if k is Kind.NUMERIC]
    categorical = [c for c, k in kinds.items() if k is Kind.CATEGORICAL]

    if temporal and numeric:
        x = temporal[0]
        ys = numeric[:MAX_SERIES]

        gap = _median_gap_days(rows, x)
        if (len(rows) <= SPARSE_MAX_POINTS and gap >= SPARSE_MIN_GAP_DAYS
                and len(ys) == 1):
            return ChartSpec(
                ChartType.BAR,
                x=x,
                ys=ys,
                reason=(f"'{x}' is a date but the {len(rows)} observations sit about "
                        f"{gap} days apart, so each one is a period rather than a "
                        f"point on a curve"),
                title=title,
            )
        if len(ys) == 2:
            first, second = (_typical(rows, y) for y in ys)
            if first and second and max(first, second) / min(first, second) >= DUAL_AXIS_RATIO:
                return ChartSpec(
                    ChartType.DUAL_AXIS_LINE,
                    x=x,
                    ys=ys,
                    secondary_y=ys[1],
                    reason=(
                        f"'{x}' is a date and '{ys[0]}'/'{ys[1]}' are numeric, so a time "
                        f"series; their medians differ by "
                        f"{max(first, second) / min(first, second):.0f}x, so each gets its "
                        f"own y-axis"
                    ),
                    title=title,
                )
        return ChartSpec(
            ChartType.LINE,
            x=x,
            ys=ys,
            reason=f"'{x}' is a date and {ys} are numeric -> time series",
            title=title,
        )

    declined = ""
    if categorical and numeric:
        x = categorical[0]
        groups = len({r.get(x) for r in rows})
        if groups <= MAX_BAR_CATEGORIES:
            return ChartSpec(
                ChartType.BAR,
                x=x,
                ys=numeric[:1],
                reason=f"'{x}' is categorical with {groups} groups -> grouped comparison",
                title=title,
            )
        declined = (f"a bar chart was declined because '{x}' has {groups} groups "
                    f"(limit {MAX_BAR_CATEGORIES}); ")

    if len(numeric) >= 2 and not temporal:
        return ChartSpec(
            ChartType.SCATTER,
            x=numeric[0],
            ys=numeric[1:2],
            reason=f"two numeric columns and no date -> relationship between them",
            title=title,
        )

    if len(numeric) == 1:
        return ChartSpec(
            ChartType.HISTOGRAM,
            x=numeric[0],
            ys=[],
            reason=declined + f"a single numeric column '{numeric[0]}' -> distribution",
            title=title,
        )

    raise ValueError(
        f"chart_engine: no rule matches these columns "
        f"({ {c: k.value for c, k in kinds.items()} })"
    )
