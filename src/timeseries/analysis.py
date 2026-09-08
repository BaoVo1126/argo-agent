"""
What a series did, computed in plain Python. No model, no ML, no fitting.

Everything the insight text will later say has to be a number produced here
first. That ordering is the whole design: a model handed raw data invents a
trend, and the invented trend is fluent enough to pass review. A model handed
"-6.18% between these two dates, two unusual days, here they are" can only
rephrase what is already true.

Three questions, three answers:

- **Trend** -- where did it start, where did it end, how far apart is that.
  How that gap is expressed depends on what the series measures. For a price,
  the useful answer is a percentage. For a series whose values are *already*
  percentages -- an inflation rate, an interest rate -- it is the difference in
  percentage points, because inflation moving from 0.63% to 2.67% is a rise of
  two points, and reporting it as "up 322%" is arithmetically true and
  useless. `is_rate` picks between them, and everything downstream follows.
- **Period comparison** -- is the recent stretch above or below the one before
  it. The caller can name the scale (month, quarter, year); left to itself the
  function takes whatever the range supports, down to an even split, so a short
  range still gets an honest comparison instead of a missing one. A scale the
  data cannot support is not silently substituted: it is dropped, and the
  automatic choice is used instead.
- **Anomalies** -- which days moved unlike the others, by two independent
  rules. A z-score asks "how many standard deviations is this move", which is
  sharp on a well-behaved series and blunt when a few violent days inflate the
  standard deviation they belong to. The IQR rule asks "is this outside the
  middle half by a wide margin", which those same days cannot distort. Running
  both and recording which fired is more honest than picking one and hoping.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass, field

# |z| above this is unusual. 2.5 rather than 2.0 because a daily financial
# series has fat tails and 2.0 flags roughly one day a month as remarkable,
# which makes "remarkable" meaningless.
Z_THRESHOLD = 2.5

# The textbook Tukey fence. Kept at 1.5 rather than tuned, because a fence
# tuned until it flags the days you already believed in is not a test.
IQR_MULTIPLIER = 1.5

# Below this many points, neither rule has enough to say anything.
MIN_POINTS_FOR_ANOMALY = 12


@dataclass
class Anomaly:
    date: dt.date
    value: float
    # Relative percent for a price, percentage points for a rate. `unit_label`
    # says which, so a caller never has to guess.
    change: float
    unit_label: str
    z_score: float
    methods: list[str]                 # "z-score", "IQR", or both
    direction: str                     # "tăng" | "giảm"

    @property
    def flagged_by_both(self) -> bool:
        return len(self.methods) > 1


@dataclass
class PeriodComparison:
    label: str                         # "Tháng gần nhất so với tháng trước"
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
    # Relative percent for a price, percentage points for a rate.
    change: float
    minimum: float
    maximum: float
    mean: float
    # Spread of the step-to-step move, in the same unit as `change`: how jumpy
    # the series is, independent of its scale.
    volatility: float
    # True when the values are themselves percentages.
    is_rate: bool = False
    # "ngày" / "tháng" / "năm" -- what one step of this series actually is, so
    # a yearly series is never described as moving "per day".
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
    """Step-to-step movement, in whichever unit describes this series."""
    if is_rate:
        return [b - a for a, b in zip(values, values[1:])]
    return [100.0 * (b - a) / a for a, b in zip(values, values[1:]) if a]


def _cadence(dates: list[dt.date]) -> str:
    """How far apart the observations are, in words."""
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
    """Days whose move stands out, by z-score, by IQR, or by both.

    The thresholds are set from the days the series actually moved, not from
    every step in it. Many published series carry the last value forward when
    nothing was published -- a bank quotes no rate at the weekend, so roughly
    three steps in ten are a change of exactly zero. Those zeros are an artefact
    of the publishing calendar rather than observations of a quiet market, and
    leaving them in shrinks the standard deviation until any real movement
    looks extreme: on a ninety-day exchange-rate series this flagged fourteen
    days, a sixth of the period, which is not what "unusual" can mean.

    Once the zeros are excluded from the yardstick they have to be excluded
    from the test as well, and the first version of this function was not: it
    measured the carried-forward days against a spread computed without them,
    and on a series whose real moves are consistent that made *the zeros* the
    outliers -- twenty of seventy days flagged, every one of them a weekend.
    A day the source did not publish is not a day the market did something
    unusual, so those days are not candidates at all.

    Both rules also stand down when their yardstick has no width. A series
    that moves by the same amount every time has a standard deviation of zero
    and an interquartile range of zero, and dividing by either produces an
    enormous z-score for anything that differs at all -- a rule that flags
    everything is not a rule.
    """
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

    # A yardstick with no width cannot measure anything. Scaled against the
    # data so the check means the same on a series in percent and one in
    # millions.
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
        # index i of `changes` is the move landing on point i+1.
        found.append(Anomaly(
            date=dates[index + 1],
            value=values[index + 1],
            change=change,
            unit_label=unit_label,
            z_score=z,
            methods=methods,
            direction="tăng" if change > 0 else "giảm",
        ))

    # Strongest first: a caller showing only a few should show the clearest.
    return sorted(found, key=lambda a: abs(a.z_score), reverse=True)


def _mean_between(dates: list[dt.date], values: list[float],
                  start: dt.date, end: dt.date) -> float | None:
    window = [v for d, v in zip(dates, values) if start <= d < end]
    return statistics.fmean(window) if window else None


# What each named comparison is worth in days, and what to call it.
COMPARE_SCALES = {
    "month": (30, "Tháng gần nhất so với tháng liền trước"),
    "quarter": (91, "Quý gần nhất so với quý liền trước"),
    "year": (365, "Năm gần nhất so với năm liền trước"),
}


# The calendar periods the rate form offers, and how to build the two windows
# each one means. Separate from COMPARE_SCALES above because they answer a
# different question: that table slides a fixed number of days back from the
# last observation, which is what a series of arbitrary dates needs, while
# these are anchored to the calendar a person actually thinks in. "Tháng này"
# starts on the first of the month whether or not there is an observation on
# it.
CALENDAR_PRESETS = ("week", "month", "year")

PRESET_LABELS = {
    "week": ("Tuần này", "tuần trước"),
    "month": ("Tháng này", "tháng trước"),
    "year": ("Năm nay", "năm ngoái"),
}


def preset_windows(preset: str, today: dt.date | None = None
                   ) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]] | None:
    """The (current, previous) date windows a named calendar period means.

    The current window runs from the start of the period to today and is
    therefore usually partial, while the previous one is the whole preceding
    period. That asymmetry would badly distort a total, and does not distort
    these: every comparison built on these windows is between *means*, so
    "the average rate so far this month" against "the average rate last
    month" is a fair question even when the month is four days old. Trimming
    the previous window to the same length would answer a narrower question
    -- the first four days of last month -- that nobody asked.
    """
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
    """Two explicit date windows, compared the way `_periods` compares its own.

    The same arithmetic `analyse` already performs, with the windows supplied
    instead of derived. That is the whole generalisation: a caller who knows
    which two stretches it wants -- a calendar preset, or two ranges a person
    picked on a form -- no longer has to express that wish as a number of days
    back from the last observation and hope the anchor lands where they meant.

    None when either window holds no observation. A rate board's history is
    made of captures rather than published daily, so "there is no reading in
    that period" is a normal answer and a caller has to be able to say it
    rather than print a zero.
    """
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
    # `_mean_between` is end-exclusive, and a window a person picked on a form
    # includes the day they picked.
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
    """Recent stretch against the one before it, at the scale asked for."""
    first, last = dates[0], dates[-1]
    span = (last - first).days
    out: list[PeriodComparison] = []

    # The third argument is unused decoration; it was named `unit_label` and
    # shadowed the enclosing one, so every period reported its change in
    # "nửa kỳ" instead of percentage points.
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
        # Two of the requested period have to fit inside the range, or the
        # "previous" half is empty and the comparison is against nothing.
        if span >= length * 2:
            add(label, length, compare)
        if out:
            return out
        # Asked for a scale the data cannot support: fall through to the
        # automatic choice rather than return nothing, and the label will say
        # which scale the customer actually got.

    if span >= 60:
        add("Tháng gần nhất so với tháng liền trước", 30, "tháng")
    if span >= 730:
        add("Năm gần nhất so với năm liền trước", 365, "năm")

    if not out and span >= 6:
        # Neither a month nor a year fits, so split the range down the middle
        # rather than report nothing.
        half = max(1, span // 2)
        add("Nửa sau kỳ so với nửa đầu kỳ", half, "nửa kỳ")

    return out


def analyse(rows: list[dict], date_field: str = "date", value_field: str = "value",
            unit: str = "", compare: str = "auto") -> SeriesAnalysis:
    """Describe one series. Rows must already be validated and sorted-able."""
    pairs = sorted(
        (r[date_field], float(r[value_field]))
        for r in rows
        if r.get(date_field) is not None and isinstance(r.get(value_field), (int, float))
    )
    if len(pairs) < 2:
        raise ValueError(f"timeseries: need at least two points for '{value_field}'")

    dates = [d for d, _ in pairs]
    values = [v for _, v in pairs]

    # A series whose values are already percentages is compared in percentage
    # points. Nothing else in this module has to know why.
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
