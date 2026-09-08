from __future__ import annotations
import datetime as dt
import pytest
from src.chart_engine import ChartType, choose, profile
from src.chart_engine.rules import Kind


def _series(days: int = 10, **columns) -> list[dict]:
    start = dt.date(2026, 6, 1)
    return [
        {"date": start + dt.timedelta(days=i), **{k: v(i) for k, v in columns.items()}}
        for i in range(days)
    ]


def test_profile_names_each_column_kind():
    kinds = profile([{"date": dt.date(2026, 6, 1), "price": 1.0, "shop": "SJC"}])
    assert kinds == {"date": Kind.TEMPORAL, "price": Kind.NUMERIC, "shop": Kind.CATEGORICAL}


def test_date_plus_numeric_is_a_line():
    spec = choose(_series(price=lambda i: 100.0 + i))
    assert spec.chart_type is ChartType.LINE
    assert spec.x == "date"


def test_two_series_of_similar_size_share_one_axis():
    spec = choose(_series(a=lambda i: 100.0 + i, b=lambda i: 120.0 + i))
    assert spec.chart_type is ChartType.LINE
    assert spec.secondary_y is None


def test_two_series_of_different_magnitude_get_an_axis_each():
    spec = choose(_series(gold=lambda i: 150e6 + i, rate=lambda i: 26000.0 + i))
    assert spec.chart_type is ChartType.DUAL_AXIS_LINE
    assert spec.secondary_y == "rate"


def test_category_plus_number_is_a_bar():
    rows = [{"shop": name, "price": float(i)} for i, name in enumerate("abcd")]
    assert choose(rows).chart_type is ChartType.BAR


def test_too_many_categories_falls_back_to_a_distribution_and_says_so():
    rows = [{"shop": f"s{i}", "price": float(i)} for i in range(40)]
    spec = choose(rows)
    assert spec.chart_type is ChartType.HISTOGRAM
    assert "declined" in spec.reason and "40 groups" in spec.reason


def test_one_numeric_column_is_a_distribution():
    assert choose([{"price": float(i)} for i in range(20)]).chart_type is ChartType.HISTOGRAM


def test_two_numerics_without_a_date_is_a_relationship():
    rows = [{"a": float(i), "b": float(i * 2)} for i in range(20)]
    assert choose(rows).chart_type is ChartType.SCATTER


def test_no_rows_is_an_error_not_an_empty_chart():
    with pytest.raises(ValueError):
        choose([])


def test_choice_is_deterministic():
    rows = _series(gold=lambda i: 150e6 + i, rate=lambda i: 26000.0 + i)
    assert choose(rows).chart_type is choose(rows).chart_type
