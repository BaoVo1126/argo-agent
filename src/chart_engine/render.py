"""
Render a ChartSpec to a PNG. matplotlib/seaborn only, always local.

The renderer never decides what to draw -- `rules.choose` did that. It only
knows how to draw each of the five shapes well: readable ticks, a legend that
names units, and for the dual-axis case a colour link between each series and
its own axis, without which a two-axis chart is a guessing game.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns

from src.chart_engine import theme
from src.chart_engine.rules import ChartSpec, ChartType

FIGSIZE = (11, 5.8)


def _column(rows: list[dict], name: str) -> list:
    return [r.get(name) for r in rows]


def _pairs(rows: list[dict], x: str, y: str) -> tuple[list, list]:
    """x/y with rows missing either value dropped, so a gap stays a gap."""
    xs, ys = [], []
    for row in rows:
        if row.get(x) is not None and row.get(y) is not None:
            xs.append(row[x])
            ys.append(row[y])
    return xs, ys


def _pretty(name: str) -> str:
    return name.replace("_", " ")


def _format_axis(ax, values: list[float]) -> None:
    """Tick labels with enough precision to tell the ticks apart.

    Decimals are chosen from the *spread*, not the magnitude. Rounding to whole
    numbers is right for a price in the millions and useless for interest
    rates: a savings chart spanning 5.70% to 6.20% printed "6" at every tick,
    six times down the axis, which is a chart that cannot be read at all.
    """
    present = [v for v in values if v is not None]
    top = max((abs(v) for v in present), default=0)
    if top >= 1_000_000:
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v / 1e6:,.0f}M"))
        return

    spread = (max(present) - min(present)) if len(present) > 1 else top
    decimals = 2 if spread < 5 else 1 if spread < 50 else 0
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v:,.{decimals}f}"))


def _date_axis(ax, dates: list) -> None:
    if not dates or not isinstance(dates[0], (dt.date, dt.datetime)):
        return
    span_days = (max(dates) - min(dates)).days or 1
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=9))
    # Over several years the month is noise: "01/2008" invites the reader to
    # wonder what happened in January when the figure is the whole year's.
    if span_days <= 400:
        fmt = "%d/%m"
    elif span_days <= 1200:
        fmt = "%m/%Y"
    else:
        fmt = "%Y"
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))


def render(spec: ChartSpec, rows: list[dict], out_path: str | Path,
           subtitle: str = "", source_note: str = "",
           markers: dict[str, list[tuple]] | None = None) -> Path:
    """Draw `spec` over `rows` and write a PNG. Returns the path written.

    `markers` maps a column to the (x, y) points to ring -- the days the
    timeseries module flagged as unusual. They are drawn as hollow rings in
    the annotation colour rather than filled dots, so a marked point still
    shows its own series colour underneath and the eye reads "this one" rather
    than "a different series".
    """
    theme.apply_style()
    sns.set_style("whitegrid", {"axes.facecolor": theme.PAPER, "grid.color": theme.GRID})

    fig, ax = plt.subplots(figsize=FIGSIZE)
    drawer = _DRAWERS[spec.chart_type]
    drawer(ax, spec, rows, markers or {})
    if markers and spec.chart_type is not ChartType.BAR:
        # A bar chart highlights in `_draw_bar`: a ring drawn over a solid bar
        # lands somewhere in its middle and reads as a smudge, while a repainted
        # bar reads as "this one" immediately.
        _mark(ax, spec, markers)

    ax.set_title(spec.title or _pretty(", ".join(spec.ys) or str(spec.x)),
                 fontsize=15, fontweight="bold", pad=18 if subtitle else 10, loc="left")
    if subtitle:
        ax.text(0.0, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9.5, color=theme.INK_SOFT, va="bottom")
    if source_note:
        fig.text(0.005, -0.02, source_note, fontsize=8, color=theme.INK_SOFT)

    theme.strip_frame(ax)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def _mark(ax, spec: ChartSpec, markers: dict[str, list[tuple]]) -> None:
    """Ring the flagged points, on whichever axis their series lives."""
    axes = {spec.ys[0]: ax} if spec.ys else {}
    if spec.chart_type is ChartType.DUAL_AXIS_LINE and len(spec.ys) > 1:
        twins = [a for a in ax.figure.axes if a is not ax]
        if twins:
            axes[spec.ys[1]] = twins[-1]

    labelled = False
    for column, points in markers.items():
        target = axes.get(column, ax)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if not xs:
            continue
        target.scatter(xs, ys, s=110, facecolors="none", edgecolors=theme.VERMILION,
                       linewidths=1.8, zorder=6,
                       label=None if labelled else "Ngày biến động bất thường")
        labelled = True

    if labelled:
        handles, labels = ax.get_legend_handles_labels()
        for other in ax.figure.axes:
            if other is ax:
                continue
            more_handles, more_labels = other.get_legend_handles_labels()
            handles += more_handles
            labels += more_labels
        if handles:
            ax.legend(handles, labels, loc="best", ncol=min(3, len(handles)))


# --- one drawer per chart type ------------------------------------------

def _draw_line(ax, spec: ChartSpec, rows: list[dict], markers=None) -> None:
    for index, column in enumerate(spec.ys):
        xs, ys = _pairs(rows, spec.x, column)
        color = theme.SERIES_COLORS[index % len(theme.SERIES_COLORS)]
        ax.plot(xs, ys, color=color, linewidth=2.0,
                linestyle=theme.SERIES_DASHES[index % len(theme.SERIES_DASHES)],
                label=spec.y_labels.get(column, _pretty(column)))
        # A tinted area under a single line reads as volume; three of them
        # overlapping read as a smear, and the lines are the comparison.
        if len(spec.ys) == 1:
            ax.fill_between(xs, ys, min(ys), color=color, alpha=0.08)
    _format_axis(ax, [v for c in spec.ys for v in _column(rows, c) if v is not None])
    _date_axis(ax, [r[spec.x] for r in rows if r.get(spec.x) is not None])
    ax.set_xlabel(spec.x_label or _pretty(spec.x))
    ax.legend(loc="best")


def _draw_dual_axis_line(ax, spec: ChartSpec, rows: list[dict], markers=None) -> None:
    left_col, right_col = spec.ys[0], spec.ys[1]
    right = ax.twinx()
    right.grid(False)

    lx, ly = _pairs(rows, spec.x, left_col)
    rx, ry = _pairs(rows, spec.x, right_col)

    ax.plot(lx, ly, color=theme.COPPER, linewidth=2.4, linestyle=theme.SERIES_DASHES[0],
            label=spec.y_labels.get(left_col, _pretty(left_col)))
    ax.fill_between(lx, ly, min(ly), color=theme.COPPER_FILL, alpha=0.30)
    right.plot(rx, ry, color=theme.INDIGO, linewidth=2.0,
               linestyle=theme.SERIES_DASHES[1],
               label=spec.y_labels.get(right_col, _pretty(right_col)))

    ax.set_ylabel(spec.y_labels.get(left_col, _pretty(left_col)), color=theme.COPPER)
    right.set_ylabel(spec.y_labels.get(right_col, _pretty(right_col)), color=theme.INDIGO)
    ax.tick_params(axis="y", colors=theme.COPPER)
    right.tick_params(axis="y", colors=theme.INDIGO)
    _format_axis(ax, ly)
    _format_axis(right, ry)
    _date_axis(ax, lx)
    ax.set_xlabel(spec.x_label or _pretty(spec.x))

    for spine in right.spines.values():
        spine.set_visible(False)
    handles = ax.get_lines() + right.get_lines()
    ax.legend(handles, [h.get_label() for h in handles], loc="upper right", ncol=2)


def _draw_bar(ax, spec: ChartSpec, rows: list[dict], markers=None) -> None:
    column = spec.ys[0]
    xs, ys = _pairs(rows, spec.x, column)

    flagged = {x for points in (markers or {}).values() for x, _ in points}
    colors = [theme.VERMILION if x in flagged else theme.COPPER for x in xs]
    dated = bool(xs) and isinstance(xs[0], (dt.date, dt.datetime))
    if dated:
        # Bars over dates need a real width in days, or matplotlib draws them
        # one day wide and the chart looks like a comb.
        span = max(1, (max(xs) - min(xs)).days)
        width = max(1.0, span / max(len(xs), 1) * 0.7)
        ax.bar(xs, ys, color=colors, edgecolor=theme.INK, linewidth=0.5, width=width)
        _date_axis(ax, xs)
    else:
        ax.bar(xs, ys, color=colors, edgecolor=theme.INK, linewidth=0.6, width=0.65)
        if len(xs) > 6:
            ax.tick_params(axis="x", rotation=30)

    _format_axis(ax, ys)
    ax.set_xlabel(spec.x_label or _pretty(spec.x))
    ax.set_ylabel(spec.y_labels.get(column, _pretty(column)))
    ax.grid(axis="x", visible=False)

    if flagged:
        from matplotlib.patches import Patch
        ax.legend(handles=[
            Patch(facecolor=theme.COPPER, edgecolor=theme.INK,
                  label=spec.y_labels.get(column, _pretty(column))),
            Patch(facecolor=theme.VERMILION, edgecolor=theme.INK,
                  label="Mốc biến động bất thường"),
        ], loc="best")


def _draw_histogram(ax, spec: ChartSpec, rows: list[dict], markers=None) -> None:
    values = [v for v in _column(rows, spec.x) if v is not None]
    sns.histplot(values, ax=ax, color=theme.MOSS, edgecolor=theme.PAPER, bins="auto")
    ax.set_xlabel(spec.x_label or _pretty(spec.x))
    ax.set_ylabel("count")
    ax.grid(axis="x", visible=False)


def _draw_scatter(ax, spec: ChartSpec, rows: list[dict], markers=None) -> None:
    xs, ys = _pairs(rows, spec.x, spec.ys[0])
    ax.scatter(xs, ys, color=theme.INDIGO, alpha=0.75, s=34, edgecolor=theme.PAPER)
    _format_axis(ax, ys)
    ax.set_xlabel(spec.x_label or _pretty(spec.x))
    ax.set_ylabel(spec.y_labels.get(spec.ys[0], _pretty(spec.ys[0])))


_DRAWERS = {
    ChartType.LINE: _draw_line,
    ChartType.DUAL_AXIS_LINE: _draw_dual_axis_line,
    ChartType.BAR: _draw_bar,
    ChartType.HISTOGRAM: _draw_histogram,
    ChartType.SCATTER: _draw_scatter,
}
