from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

Z_THRESHOLD = 2.5

IQR_MULTIPLIER = 1.5

MIN_POINTS_FOR_ANOMALY = 12


@dataclass
class Anomaly:
    date: dt.date
    value: float
    change: float
    unit_label: str
    z_score: float
    methods: list[str]               
    direction: str                   

    @property
    def flagged_by_both(self) -> bool:
        return len(self.methods) > 1


@dataclass
class PeriodComparison:
    label: str                     
    current_label: str
    previous_label: str
    current_mean: float
    previous_mean: float
    change: float
    unit_label: str


@dataclass
class SeriesAnalysis:
    field_name: str
    unit: str
    points: int
    first_date: dt.date
    last_date: dt.date
    first_value: float
    last_value: float
    change: float
    minimum: float
    maximum: float
    mean: float
    volatility: float
    is_rate: bool = False

    cadence: str = "ngày"
    periods: list[PeriodComparison] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)

    @property
    def unit_label(self) -> str:
        return "điểm phần trăm" if self.is_rate else "%"

    @property
    def direction(self) -> str:
        if self.change > 0.005:
            return "tăng"
        if self.change < -0.005:
            return "giảm"
        return "gần như đi ngang"

    @property
    def span_days(self) -> int:
        return (self.last_date - self.first_date).days


def _changes(values: list[float], is_rate: bool) -> list[float]:
    if is_rate:
        return [b - a for a, b in zip(values, values[1:])]
    return [100.0 * (b - a) / a for a, b in zip(values, values[1:]) if a]


def _cadence(dates: list[dt.date]) -> str:
    if len(dates) < 2:
        return "kỳ"
    gaps = sorted((b - a).days for a, b in zip(dates, dates[1:]))
    typical = gaps[len(gaps) // 2]
    if typical >= 300:
        return "năm"
    if typical >= 25:
        return "tháng"
    return "ngày"


def _iqr_fence(values: list[float]) -> tuple[float, float]:
    ordered = sorted(values)
    n = len(ordered)
    q1 = statistics.median(ordered[: n // 2])
    q3 = statistics.median(ordered[(n + 1) // 2:])
    spread = q3 - q1
    return q1 - IQR_MULTIPLIER * spread, q3 + IQR_MULTIPLIER * spread


def _anomalies(dates: list[dt.date], values: list[float],
               is_rate: bool, unit_label: str) -> list[Anomaly]:
    if len(values) < MIN_POINTS_FOR_ANOMALY:
        return []

    changes = _changes(values, is_rate)
    if len(changes) < MIN_POINTS_FOR_ANOMALY - 1:
        return []

    moved = [c for c in changes if c != 0.0]
    carried_forward = len(moved) < len(changes)
    if carried_forward and len(moved) >= MIN_POINTS_FOR_ANOMALY - 1:
        reference, testable = moved, moved
    else:
        reference, testable = changes, changes

    mean = statistics.fmean(reference)
    deviation = statistics.pstdev(reference)
    low, high = _iqr_fence(reference)

    scale = max(abs(mean), max((abs(c) for c in reference), default=0.0), 1e-12)
    z_usable = deviation > scale * 1e-9
    iqr_usable = (high - low) > scale * 1e-9

    if not z_usable and not iqr_usable:
        return []

    found: list[Anomaly] = []
    for index, change in enumerate(changes):
        if carried_forward and testable is moved and change == 0.0:
            continue
        methods = []
        z = (change - mean) / deviation if z_usable else 0.0
        if z_usable and abs(z) >= Z_THRESHOLD:
            methods.append("z-score")
        if iqr_usable and (change < low or change > high):
            methods.append("IQR")
        if not methods:
            continue
        found.append(Anomaly(
            date=dates[index + 1],
            value=values[index + 1],
            change=change,
            unit_label=unit_label,
            z_score=z,
            methods=methods,
            direction="tăng" if change > 0 else "giảm",
        ))

    return sorted(found, key=lambda a: abs(a.z_score), reverse=True)


def _mean_between(dates: list[dt.date], values: list[float],
                  start: dt.date, end: dt.date) -> float | None:
    window = [v for d, v in zip(dates, values) if start <= d < end]
    return statistics.fmean(window) if window else None


COMPARE_SCALES = {
    "month": (30, "Tháng gần nhất so với tháng liền trước"),
    "quarter": (91, "Quý gần nhất so với quý liền trước"),
    "year": (365, "Năm gần nhất so với năm liền trước"),
}

CALENDAR_PRESETS = ("week", "month", "year")

PRESET_LABELS = {
    "week": ("Tuần này", "tuần trước"),
    "month": ("Tháng này", "tháng trước"),
    "year": ("Năm nay", "năm ngoái"),
}


def preset_windows(preset: str, today: dt.date | None = None
                   ) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]] | None:
    if preset not in CALENDAR_PRESETS:
        return None
    today = today or dt.date.today()

    if preset == "week":
        current_start = today - dt.timedelta(days=today.weekday())
        previous_start = current_start - dt.timedelta(days=7)
    elif preset == "month":
        current_start = today.replace(day=1)
        previous_start = (current_start - dt.timedelta(days=1)).replace(day=1)
    else:
        current_start = today.replace(month=1, day=1)
        previous_start = current_start.replace(year=current_start.year - 1)

    return ((current_start, today),
            (previous_start, current_start - dt.timedelta(days=1)))


def compare_windows(rows: list[dict], current: tuple[dt.date, dt.date],
                    previous: tuple[dt.date, dt.date], date_field: str = "date",
                    value_field: str = "value", unit: str = "",
                    label: str = "") -> PeriodComparison | None:
    pairs = sorted(
        (row[date_field], float(row[value_field]))
        for row in rows
        if row.get(date_field) is not None
        and isinstance(row.get(value_field), (int, float))
    )
    if not pairs:
        return None
    dates = [d for d, _ in pairs]
    values = [v for _, v in pairs]

    day = dt.timedelta(days=1)
    current_mean = _mean_between(dates, values, current[0], current[1] + day)
    previous_mean = _mean_between(dates, values, previous[0], previous[1] + day)
    if current_mean is None or previous_mean is None:
        return None

    is_rate = "%" in (unit or "")
    unit_label = "điểm phần trăm" if is_rate else "%"
    if not is_rate and previous_mean == 0:
        return None

    return PeriodComparison(
        label=label or "Kỳ hiện tại so với kỳ trước",
        current_label=f"{current[0]:%d/%m/%Y} – {current[1]:%d/%m/%Y}",
        previous_label=f"{previous[0]:%d/%m/%Y} – {previous[1]:%d/%m/%Y}",
        current_mean=current_mean,
        previous_mean=previous_mean,
        change=(current_mean - previous_mean) if is_rate
               else 100.0 * (current_mean - previous_mean) / previous_mean,
        unit_label=unit_label,
    )


def _periods(dates: list[dt.date], values: list[float],
             is_rate: bool, unit_label: str,
             compare: str = "auto") -> list[PeriodComparison]:
    first, last = dates[0], dates[-1]
    span = (last - first).days
    out: list[PeriodComparison] = []

    def add(label: str, length_days: int, _period_name: str) -> None:
        mid = last - dt.timedelta(days=length_days)
        start = mid - dt.timedelta(days=length_days)
        current = _mean_between(dates, values, mid, last + dt.timedelta(days=1))
        previous = _mean_between(dates, values, start, mid)
        if current is None or previous is None or previous == 0:
            return
        out.append(PeriodComparison(
            label=label,
            current_label=f"{mid:%d/%m/%Y} – {last:%d/%m/%Y}",
            previous_label=f"{start:%d/%m/%Y} – {mid:%d/%m/%Y}",
            current_mean=current,
            previous_mean=previous,
            change=(current - previous) if is_rate
                   else 100.0 * (current - previous) / previous,
            unit_label=unit_label,
        ))

    if compare in COMPARE_SCALES:
        length, label = COMPARE_SCALES[compare]
        if span >= length * 2:
            add(label, length, compare)
        if out:
            return out

    if span >= 60:
        add("Tháng gần nhất so với tháng liền trước", 30, "tháng")
    if span >= 730:
        add("Năm gần nhất so với năm liền trước", 365, "năm")

    if not out and span >= 6:
        half = max(1, span // 2)
        add("Nửa sau kỳ so với nửa đầu kỳ", half, "nửa kỳ")

    return out


def analyse(rows: list[dict], date_field: str = "date", value_field: str = "value",
            unit: str = "", compare: str = "auto") -> SeriesAnalysis:
    pairs = sorted(
        (r[date_field], float(r[value_field]))
        for r in rows
        if r.get(date_field) is not None and isinstance(r.get(value_field), (int, float))
    )
    if len(pairs) < 2:
        raise ValueError(f"timeseries: need at least two points for '{value_field}'")

    dates = [d for d, _ in pairs]
    values = [v for _, v in pairs]
              
    is_rate = "%" in (unit or "")
    unit_label = "điểm phần trăm" if is_rate else "%"
    changes = _changes(values, is_rate)

    if is_rate:
        change = values[-1] - values[0]
    else:
        change = 100.0 * (values[-1] - values[0]) / values[0] if values[0] else 0.0

    return SeriesAnalysis(
        field_name=value_field,
        unit=unit,
        points=len(values),
        first_date=dates[0],
        last_date=dates[-1],
        first_value=values[0],
        last_value=values[-1],
        change=change,
        minimum=min(values),
        maximum=max(values),
        mean=statistics.fmean(values),
        volatility=statistics.pstdev(changes) if len(changes) > 1 else 0.0,
        is_rate=is_rate,
        cadence=_cadence(dates),
        periods=_periods(dates, values, is_rate, unit_label, compare),
        anomalies=_anomalies(dates, values, is_rate, unit_label),
    )
