from __future__ import annotations
import datetime as dt
import pytest
from modes.research import bank_rates, rate_query
from modes.research.rate_query import RateQuery
from modes.research.snapshots import RateQuote, RateSnapshot
from src.timeseries import compare_windows, preset_windows

BOARD = "counter"


def _snapshot(day: dt.date, rates: dict[str, dict[int, float]]) -> RateSnapshot:
    return RateSnapshot(
        captured_at=f"{day.isoformat()}T09:00:00",
        source="test",
        quotes=[RateQuote(bank=bank, tenor_months=tenor, rate_pct=rate, board=BOARD)
                for bank, by_tenor in rates.items()
                for tenor, rate in by_tenor.items()],
    )


@pytest.fixture
def history():
    return [
        _snapshot(dt.date(2026, 7, 15),
                  {"MB": {6: 4.00, 12: 5.00}, "BIDV": {6: 3.50, 12: 4.80}}),
        _snapshot(dt.date(2026, 8, 15),
                  {"MB": {6: 4.20, 12: 5.20}, "BIDV": {6: 3.50, 12: 4.80}}),
        _snapshot(dt.date(2026, 9, 3),
                  {"MB": {6: 4.60, 12: 5.60}, "BIDV": {6: 3.40, 12: 4.90}}),
    ]


@pytest.mark.parametrize("preset,expected", [
    ("week", ((dt.date(2026, 9, 7), dt.date(2026, 9, 10)),
              (dt.date(2026, 8, 31), dt.date(2026, 9, 6)))),
    ("month", ((dt.date(2026, 9, 1), dt.date(2026, 9, 10)),
               (dt.date(2026, 8, 1), dt.date(2026, 8, 31)))),
    ("year", ((dt.date(2026, 1, 1), dt.date(2026, 9, 10)),
              (dt.date(2025, 1, 1), dt.date(2025, 12, 31)))),
])
def test_a_preset_means_the_calendar_period_not_a_rolling_window(preset, expected):
    assert preset_windows(preset, dt.date(2026, 9, 10)) == expected


def test_the_two_windows_never_overlap():
    for preset in ("week", "month", "year"):
        (current_start, _), (_, previous_end) = preset_windows(
            preset, dt.date(2026, 9, 10))
        assert previous_end < current_start


def test_an_unknown_preset_is_not_guessed_at():
    assert preset_windows("fortnight", dt.date(2026, 9, 10)) is None


def test_a_custom_range_is_used_exactly_as_given():
    query = RateQuery(banks=("MB",), tenors=(12,), mode="time",
                      preset=rate_query.CUSTOM,
                      current=(dt.date(2026, 9, 1), dt.date(2026, 9, 3)),
                      previous=(dt.date(2026, 8, 1), dt.date(2026, 8, 20)))
    assert query.windows() == ((dt.date(2026, 9, 1), dt.date(2026, 9, 3)),
                               (dt.date(2026, 8, 1), dt.date(2026, 8, 20)))


def test_a_custom_range_missing_half_its_dates_compares_nothing():
    query = RateQuery(banks=("MB",), tenors=(12,), mode="time",
                      preset=rate_query.CUSTOM,
                      current=(dt.date(2026, 9, 1), dt.date(2026, 9, 3)))
    assert query.windows() is None


def test_a_window_a_person_picked_includes_the_day_they_picked():
    rows = [{"date": dt.date(2026, 9, 3), "rate_pct": 5.6},
            {"date": dt.date(2026, 8, 15), "rate_pct": 5.2}]
    verdict = compare_windows(rows,
                              (dt.date(2026, 9, 1), dt.date(2026, 9, 3)),
                              (dt.date(2026, 8, 1), dt.date(2026, 8, 15)),
                              value_field="rate_pct", unit="%")
    assert verdict is not None
    assert verdict.current_mean == 5.6 and verdict.previous_mean == 5.2


def test_a_rate_is_compared_in_percentage_points_not_percent():
    rows = [{"date": dt.date(2026, 9, 3), "rate_pct": 5.6},
            {"date": dt.date(2026, 8, 15), "rate_pct": 5.2}]
    verdict = compare_windows(rows,
                              (dt.date(2026, 9, 1), dt.date(2026, 9, 3)),
                              (dt.date(2026, 8, 1), dt.date(2026, 8, 15)),
                              value_field="rate_pct", unit="%")
    assert verdict.unit_label == "điểm phần trăm"
    assert verdict.change == pytest.approx(0.4)

def test_the_bank_diff_reads_the_same_snapshot_the_table_does(history):
    gaps = bank_rates.gaps_at(history[-1], 12, ["MB", "BIDV"], BOARD)
    assert len(gaps) == 1
    assert gaps[0].higher == "MB" and gaps[0].lower == "BIDV"
    assert gaps[0].gap == pytest.approx(0.7)


def test_gaps_come_back_widest_first(history):
    board = _snapshot(dt.date(2026, 9, 3),
                      {"A": {12: 6.0}, "B": {12: 5.0}, "C": {12: 4.0}})
    gaps = bank_rates.gaps_at(board, 12, ["A", "B", "C"], BOARD)
    assert [g.gap for g in gaps] == sorted([g.gap for g in gaps], reverse=True)
    assert (gaps[0].higher, gaps[0].lower) == ("A", "C")


def test_a_bank_that_does_not_offer_a_tenor_is_left_out_rather_than_zeroed(history):
    board = _snapshot(dt.date(2026, 9, 3), {"A": {12: 6.0}, "B": {6: 5.0}})
    assert bank_rates.gaps_at(board, 12, ["A", "B"], BOARD) == []


def test_the_gap_sentence_is_a_template_not_a_paraphrase(history):
    gap = bank_rates.gaps_at(history[-1], 12, ["MB", "BIDV"], BOARD)[0]
    assert bank_rates.gap_sentence(gap) == (
        "MB trả cao hơn BIDV 0,70 điểm phần trăm ở kỳ hạn 12 tháng.")


def test_two_banks_paying_the_same_are_not_described_as_one_beating_the_other():
    board = _snapshot(dt.date(2026, 9, 3), {"A": {12: 5.9}, "B": {12: 5.9}})
    gap = bank_rates.gaps_at(board, 12, ["A", "B"], BOARD)[0]
    assert "bằng nhau" in bank_rates.gap_sentence(gap)


def test_a_period_with_no_capture_is_reported_as_missing_not_as_no_change(history):
    changes = bank_rates.rate_changes(
        history, ["MB"], [12],
        current=(dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
        previous=(dt.date(2026, 6, 1), dt.date(2026, 6, 30)), board=BOARD)
    assert changes[0].change is None
    assert "Chưa có lần cập nhật" in changes[0].note
    assert "0,00" not in bank_rates.change_sentence(changes[0], "tháng trước")


def test_a_measured_move_is_stated_with_its_direction(history):
    changes = bank_rates.rate_changes(
        history, ["MB"], [12],
        current=(dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
        previous=(dt.date(2026, 8, 1), dt.date(2026, 8, 31)), board=BOARD)
    assert changes[0].change == pytest.approx(0.4)
    assert bank_rates.change_sentence(changes[0], "tháng trước") == (
        "MB hiện tăng 0,40 điểm phần trăm so với tháng trước ở kỳ hạn 12 tháng.")

def _answer(history, tmp_path, **kwargs):
    query = RateQuery(banks=("MB", "BIDV"), tenors=(6, 12), **kwargs)
    return rate_query.answer(query, history, output_dir=tmp_path,
                             today=dt.date(2026, 9, 10))


def test_between_banks_shows_a_snapshot_and_a_trend_and_no_deltas(history, tmp_path):
    answer = _answer(history, tmp_path, mode="banks")
    assert answer.ok
    assert set(answer.snapshot_charts) == {6, 12}
    assert set(answer.trend_charts) == {6, 12}
    assert all(cell.change is None for row in answer.rows for cell in row.cells.values())
    assert all("trả cao hơn" in line or "bằng nhau" in line for line in answer.insights)


def test_over_time_fills_the_deltas_and_names_both_windows(history, tmp_path):
    answer = _answer(history, tmp_path, mode="time", preset="month")
    assert answer.ok
    assert answer.period_label == "Tháng này so với tháng trước"
    assert answer.period_current == "01/09/2026 – 10/09/2026"
    assert answer.period_previous == "01/08/2026 – 31/08/2026"
    assert answer.rows[0].cells[12].change is not None
    assert answer.snapshot_charts == {}


def test_both_shows_the_two_comparisons_in_one_table(history, tmp_path):
    answer = _answer(history, tmp_path, mode="both", preset="month")
    assert answer.ok
    assert answer.rows[0].cells[12].rate is not None
    assert answer.rows[0].cells[12].change is not None
    assert set(answer.snapshot_charts) == {6, 12}
    assert set(answer.trend_charts) == {6, 12}
    assert any("trả cao hơn" in line or "bằng nhau" in line for line in answer.insights)
    assert any("hiện tăng" in line or "hiện giảm" in line or "không đổi" in line
               for line in answer.insights)


def test_the_table_leads_with_whoever_pays_most(history, tmp_path):
    answer = _answer(history, tmp_path, mode="banks")
    assert [row.bank for row in answer.rows] == ["MB", "BIDV"]


def test_empty_periods_are_one_caveat_rather_than_one_sentence_each(history, tmp_path):
    answer = _answer(history, tmp_path, mode="both", preset="year")
    assert not any("Chưa có lần cập nhật" in line for line in answer.insights)
    assert any("Không so sánh được" in line for line in answer.caveats)


def test_a_query_naming_a_bank_the_board_never_carried_is_refused(history, tmp_path):
    query = RateQuery(banks=("Ngân hàng Không Có Thật",), tenors=(12,), mode="banks")
    answer = rate_query.answer(query, history, output_dir=tmp_path)
    assert not answer.ok and "chọn lại" in answer.message


def test_no_captures_at_all_asks_for_one_rather_than_drawing_nothing(tmp_path):
    answer = rate_query.answer(RateQuery(banks=("MB",), tenors=(12,)), [],
                               output_dir=tmp_path)
    assert not answer.ok and "Cập nhật" in answer.message


def test_the_form_is_offered_only_what_the_captures_contain(history):
    options = rate_query.available(history, BOARD)
    assert options["banks"] == ["BIDV", "MB"]
    assert options["tenors"] == [6, 12]
    assert options["updates"] == 3


def test_charts_are_capped_but_the_table_is_not(history, tmp_path):
    wide = RateQuery(banks=("MB", "BIDV"), tenors=(6, 12), mode="both")
    answer = rate_query.answer(wide, history, output_dir=tmp_path,
                               today=dt.date(2026, 9, 10))
    assert len(answer.tenors) == 2

    rate_query.MAX_CHART_TENORS  
    capped = rate_query.answer(
        RateQuery(banks=("MB",), tenors=(6, 12), mode="banks"), history,
        output_dir=tmp_path, today=dt.date(2026, 9, 10))
    assert len(capped.snapshot_charts) <= rate_query.MAX_CHART_TENORS


def test_the_same_question_twice_does_not_redraw_the_charts(history, tmp_path):
    first = _answer(history, tmp_path, mode="banks")
    stamps = {t: p.stat().st_mtime_ns for t, p in first.snapshot_charts.items()}
    second = _answer(history, tmp_path, mode="banks")
    assert {t: p.stat().st_mtime_ns for t, p in second.snapshot_charts.items()} == stamps


def test_a_different_bank_set_gets_a_different_chart(history, tmp_path):
    two = rate_query.answer(RateQuery(banks=("MB", "BIDV"), tenors=(12,), mode="banks"),
                            history, output_dir=tmp_path)
    one = rate_query.answer(RateQuery(banks=("MB",), tenors=(12,), mode="banks"),
                            history, output_dir=tmp_path)
    assert two.snapshot_charts.get(12) != one.snapshot_charts.get(12)


def test_a_tenor_where_every_bank_pays_the_same_is_not_coloured(history, tmp_path):
    tied = [_snapshot(dt.date(2026, 9, 3), {"MB": {12: 5.9}, "BIDV": {12: 5.9}})]
    answer = rate_query.answer(
        RateQuery(banks=("MB", "BIDV"), tenors=(12,), mode="banks"),
        tied, output_dir=tmp_path)
    assert answer.ok
    assert 12 not in answer.highest and 12 not in answer.lowest


def test_a_tenor_where_banks_differ_is_still_coloured(history, tmp_path):
    answer = rate_query.answer(
        RateQuery(banks=("MB", "BIDV"), tenors=(12,), mode="banks"),
        history, output_dir=tmp_path)
    assert answer.highest[12] == "MB" and answer.lowest[12] == "BIDV"
