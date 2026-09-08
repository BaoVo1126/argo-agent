"""Rule-based chart selection and local matplotlib/seaborn rendering."""

from src.chart_engine.rules import ChartSpec, ChartType, Kind, choose, profile
from src.chart_engine.render import render

__all__ = ["ChartSpec", "ChartType", "Kind", "choose", "profile", "render"]
