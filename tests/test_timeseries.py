"""Trend, period comparison and anomalies -- the numbers the insight text quotes."""

from __future__ import annotations

import datetime as dt

import pytest

from src.timeseries import analyse

BASE = dt.date(2026, 6, 1)


def rows(values: list[float], field: str = "value") -> list[dict]:
    return [{"date": BASE + dt.timedelta(days=i), field: v} for i, v in enumerate(values)]


def test_trend_is_first_to_last_not_min_to_max():
    result = analyse(rows([100.0, 130.0, 90.0, 110.0] + [110.0] * 20))
    assert result.first_value == 100.0 and result.last_value == 110.0
    assert result.change == pytest.approx(10.0)
    assert result.direction == "tăng"


def test_a_flat_series_is_not_called_a_trend():
    assert analyse(rows([50.0] * 30)).direction == "gần như đi ngang"


def test_month_on_month_appears_once_there_are_two_months():
    short = analyse(rows([100.0 + i for i in range(20)]))
    assert not any("Tháng" in p.label for p in short.periods)

    long = analyse(rows([100.0 + i for i in range(95)]))
    assert any("Tháng" in p.label for p in long.periods)


def test_a_short_range_still_gets_an_honest_comparison():
    """No month fits, so the range is split in half rather than left blank."""
    result = analyse(rows([100.0] * 5 + [110.0] * 5))
    assert len(result.periods) == 1
    assert "Nửa" in result.periods[0].label


def test_one_violent_day_is_flagged_by_both_rules():
    values = [100.0 + 0.1 * i for i in range(40)]
    values[20] *= 1.25
    found = analyse(rows(values)).anomalies
    assert found
    assert found[0].date == BASE + dt.timedelta(days=20)
    assert found[0].direction == "tăng"
    assert found[0].flagged_by_both


def test_a_quiet_series_has_no_anomalies():
    assert analyse(rows([100.0 + 0.1 * i for i in range(40)])).anomalies == []


def test_carried_forward_days_do_not_turn_ordinary_moves_into_anomalies():
    """A bank quotes nothing at the weekend, so the series repeats its last
    value. Those zero steps are the publishing calendar, not a still market:
    counting them when setting the threshold shrinks it until every real move
    looks extreme."""
    values, current = [], 100.0
    for day in range(70):
        if day % 7 in (5, 6):          # weekend: carried forward
            values.append(current)
            continue
        current *= 1.001               # a steady, unremarkable weekday move
        values.append(current)

    found = analyse(rows(values)).anomalies
    assert len(found) <= 2, f"{len(found)} of {len(values)} days flagged as unusual"


def test_two_points_are_enough_to_describe_but_not_to_flag():
    result = analyse(rows([100.0, 110.0]))
    assert result.change == pytest.approx(10.0)
    assert result.anomalies == []


def test_a_single_point_is_an_error_not_a_flat_line():
    with pytest.raises(ValueError):
        analyse(rows([100.0]))


def test_rows_are_sorted_before_anything_is_computed():
    unordered = list(reversed(rows([100.0, 105.0, 110.0] + [110.0] * 12)))
    result = analyse(unordered)
    assert result.first_value == 100.0 and result.last_value == 110.0


# --- what the series measures decides how its movement is expressed --------

def yearly(values: list[float], field: str = "value") -> list[dict]:
    return [{"date": dt.date(2005 + i, 1, 1), field: v} for i, v in enumerate(values)]


def test_a_rate_moves_in_percentage_points_not_percent():
    """Inflation going from 0.63% to 2.67% is a rise of two points. Calling it
    a rise of 322% is arithmetically true and tells the reader nothing."""
    result = analyse(yearly([0.63, 2.67] + [2.67] * 18), unit="%")
    assert result.is_rate
    assert result.unit_label == "điểm phần trăm"
    assert result.change == pytest.approx(2.04)


def test_a_price_still_moves_in_percent():
    result = analyse(rows([100.0] + [110.0] * 20))
    assert result.is_rate is False
    assert result.unit_label == "%"
    assert result.change == pytest.approx(10.0)


def test_the_anomaly_on_a_rate_is_measured_in_points_too():
    values = [3.0] * 20
    values[10] = 23.0
    found = analyse(yearly(values), unit="%").anomalies
    assert found
    assert found[0].unit_label == "điểm phần trăm"
    assert found[0].change == pytest.approx(20.0)


def test_a_rate_whose_base_is_near_zero_does_not_explode():
    """The relative rule divides by the previous value, so a year at 0.05%
    turns any move into thousands of percent. Points do not have that
    failure mode, which is the other half of why rates use them."""
    found = analyse(yearly([0.05, 1.0] + [1.0] * 18), unit="%").anomalies
    assert all(abs(a.change) < 5 for a in found)


def test_cadence_is_read_off_the_dates_not_assumed():
    assert analyse(rows([100.0 + i for i in range(30)])).cadence == "ngày"
    assert analyse(yearly([3.0 + i * 0.1 for i in range(20)]), unit="%").cadence == "năm"


def test_period_comparison_uses_the_same_unit_as_the_headline():
    result = analyse(yearly([8.0] * 10 + [3.0] * 10), unit="%")
    assert result.periods
    assert result.periods[0].unit_label == "điểm phần trăm"
