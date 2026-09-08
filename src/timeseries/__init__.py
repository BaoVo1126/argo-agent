"""Trend, period comparison and anomaly detection, in plain Python."""

from src.timeseries.analysis import (
    CALENDAR_PRESETS,
    PRESET_LABELS,
    Anomaly,
    PeriodComparison,
    SeriesAnalysis,
    analyse,
    compare_windows,
    preset_windows,
)

__all__ = ["Anomaly", "PeriodComparison", "SeriesAnalysis", "analyse",
           "CALENDAR_PRESETS", "PRESET_LABELS", "compare_windows", "preset_windows"]
