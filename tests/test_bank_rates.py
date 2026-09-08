"""
The savings-rate board: parsing it, storing it, and comparing banks.

None of these need a browser. The scraping is one `page.evaluate` whose output
shape is fixed here as literal tables, which is the part that actually breaks
when a site is redesigned.
"""

from __future__ import annotations

import datetime as dt

import pytest

from modes.research import bank_rates, snapshots
from modes.research.snapshots import RateQuote, RateSnapshot

HEADER = ["Không Kỳ Hạn", "01 tháng", "03 tháng", "06 tháng", "09 tháng",
          "12 tháng", "13 tháng", "18 tháng", "24 tháng", "36 tháng"]

COUNTER = "Lãi suất tiền gửi VND dành cho khách hàng cá nhân gửi tại Quầy"
ONLINE = "Lãi suất tiền gửi VND dành cho khách hàng cá nhân gửi Trực tuyến (Online)"


def board(heading: str, *rows: list) -> dict:
    return {"heading": heading,
            "rows": [["Ngân hàng", "Kỳ hạn gửi tiết kiệm (tháng)"], HEADER, *rows]}


BIDV_ROW = ["BIDV", "0,10", "2,10", "2,40", "3,50", "3,50",
            "5,90", "5,90", "5,90", "6,00", "6,00"]
VPBANK_ROW = ["VPBank", "-", "4,75", "-", "6,20", "-", "6,20", "-", "-", "6,00", "-"]


# --- parsing --------------------------------------------------------------

def test_the_wanted_banks_are_read_with_their_tenors():
    quotes = bank_rates.parse_board([board(COUNTER, BIDV_ROW)])
    rates = {q.tenor_months: q.rate_pct for q in quotes}
    assert rates == {1: 2.10, 3: 2.40, 6: 3.50, 9: 3.50, 12: 5.90, 24: 6.00, 36: 6.00}
    assert all(q.bank == "BIDV" and q.board == "counter" for q in quotes)


def test_promotional_tenors_are_dropped():
    """13 and 18 months are on the board and are not choices anyone compares."""
    quotes = bank_rates.parse_board([board(COUNTER, BIDV_ROW)])
    assert {q.tenor_months for q in quotes} == set(bank_rates.TENORS)


def test_a_dash_means_not_offered_rather_than_zero():
    quotes = bank_rates.parse_board([board(COUNTER, VPBANK_ROW)])
    offered = {q.tenor_months for q in quotes}
    assert 3 not in offered and 9 not in offered and 36 not in offered
    assert offered == {1, 6, 12, 24}


def test_banks_outside_the_watch_list_are_ignored():
    other = ["Bắc Á", "0,50", "4,75", "4,75", "7,05", "7,05",
             "7,10", "6,95", "6,95", "6,95", "6,95"]
    assert bank_rates.parse_board([board(COUNTER, other)]) == []


def test_the_two_boards_are_kept_apart():
    """A bank quoting nothing at the counter may pay more online; merging the
    two would report it as offering nothing."""
    counter = ["TPBank", "-", "4,20", "4,20", "5,50", "-", "-", "-", "5,90", "-", "6,00"]
    online = ["TPBank", "-", "4,75", "4,75", "6,00", "-", "6,20", "-", "6,20", "6,30", "6,30"]
    quotes = bank_rates.parse_board([board(COUNTER, counter), board(ONLINE, online)])

    at_counter = {q.tenor_months: q.rate_pct for q in quotes if q.board == "counter"}
    on_app = {q.tenor_months: q.rate_pct for q in quotes if q.board == "online"}
    assert 12 not in at_counter
    assert on_app[12] == 6.20


def test_a_table_that_is_not_a_rate_board_is_skipped():
    """The page also carries gold, fuel and exchange-rate tables."""
    fuel = {"heading": "Giá xăng dầu", "rows": [["Sản phẩm", "Vùng 1", "Vùng 2"]]}
    assert bank_rates.parse_board([fuel]) == []


def test_a_rate_board_with_no_recognisable_heading_is_skipped():
    """Reading an unlabelled table would mean guessing which product it is."""
    assert bank_rates.parse_board([board("Bảng nào đó", BIDV_ROW)]) == []


def test_bidv_own_board_is_read_from_its_endpoint():
    payload = {"hcm": {"data": [
        {"title_vi": "Không kỳ hạn", "VND": "0.1"},
        {"title_vi": "1 Tháng", "VND": "2.1"},
        {"title_vi": "12 Tháng", "VND": "5.9"},
        {"title_vi": "13 Tháng", "VND": "5.9"},
        {"title_vi": "36 Tháng", "VND": ""},
    ]}}
    assert bank_rates.parse_bidv(payload) == {1: 2.1, 12: 5.9}


def test_an_impossible_rate_is_a_parse_error_not_an_offer():
    assert bank_rates._rate("87,50") is None      # outside any savings range
    assert bank_rates._rate("6,20") == 6.20
    assert bank_rates._rate("—") is None


# --- comparing ------------------------------------------------------------

def snapshot(day: str, rates: dict[str, dict[int, float]]) -> RateSnapshot:
    quotes = [RateQuote(bank, tenor, value, "counter")
              for bank, per_tenor in rates.items()
              for tenor, value in per_tenor.items()]
    return RateSnapshot(captured_at=f"{day}T09:00:00", source="test", quotes=quotes)


def test_best_and_worst_are_found_per_tenor_across_banks():
    """A rate comparison answers "who pays most for this term", which is a
    question about a column, not about one bank's own spread of terms."""
    latest = snapshot("2026-09-01", {
        "VPBank": {12: 6.20, 24: 6.00},
        "MB": {12: 4.85, 24: 5.70},
        "BIDV": {12: 5.90, 24: 6.00},
    })
    result = bank_rates.compare([latest])
    assert result.highest[12] == "VPBank"
    assert result.lowest[12] == "MB"
    assert result.lowest[24] == "MB"


def test_rows_come_back_ordered_by_the_headline_tenor():
    result = bank_rates.compare([snapshot("2026-09-01", {
        "MB": {12: 4.85}, "VPBank": {12: 6.20}, "BIDV": {12: 5.90},
    })])
    assert [row.bank for row in result.rows] == ["VPBank", "BIDV", "MB"]


def test_the_headline_numbers_are_the_top_rate_and_the_average():
    result = bank_rates.compare([snapshot("2026-09-01", {
        "VPBank": {12: 6.20}, "MB": {12: 4.80},
    })])
    assert result.top_bank == "VPBank"
    assert result.top_rate == 6.20
    assert result.average == pytest.approx(5.50)


def test_one_capture_has_no_comparison_to_make():
    """A first run cannot say what changed, and saying "0.00" would claim the
    market held steady when nothing has been compared."""
    result = bank_rates.compare([snapshot("2026-09-01", {"BIDV": {12: 5.90}})])
    assert result.average_change is None
    assert result.has_history is False


def test_a_second_capture_produces_the_change_and_names_the_mover():
    history = [
        snapshot("2026-09-01", {"BIDV": {12: 5.90}, "MB": {12: 4.85}}),
        snapshot("2026-09-02", {"BIDV": {12: 6.20}, "MB": {12: 4.85}}),
    ]
    result = bank_rates.compare(history)
    assert result.has_history
    assert result.average_change == pytest.approx(0.15)
    assert result.movers[0] == ("BIDV", pytest.approx(0.30))


def test_big_four_are_marked():
    result = bank_rates.compare([snapshot("2026-09-01", {
        "BIDV": {12: 5.9}, "VPBank": {12: 6.2},
    })])
    marked = {row.bank: row.is_big_four for row in result.rows}
    assert marked == {"BIDV": True, "VPBank": False}


# --- the sentence under the chart ----------------------------------------

def test_the_insight_is_a_template_and_quotes_the_computed_numbers():
    """No model writes this. There is one fact to state and a template states
    it exactly, which removes the drift and the guards that would catch it."""
    result = bank_rates.compare([snapshot("2026-09-01", {
        "VPBank": {12: 6.20}, "MB": {12: 4.80},
    })])
    line = bank_rates.insight_line(result)
    assert "VPBank" in line
    assert "6,20%/năm" in line          # Vietnamese decimal separator
    assert "5,50%/năm" in line


def test_the_insight_reports_a_flat_market_as_flat():
    history = [snapshot("2026-09-01", {"BIDV": {12: 5.90}}),
               snapshot("2026-09-02", {"BIDV": {12: 5.90}})]
    assert "không đổi" in bank_rates.insight_line(bank_rates.compare(history))


# --- storage --------------------------------------------------------------

def test_two_captures_on_one_day_replace_rather_than_accumulate(tmp_path):
    """Running twice in an afternoon is a person checking their work. Keeping
    both would put two points on one day and make a still board look like
    movement."""
    path = tmp_path / "snap.json"
    snapshots.append(snapshot("2026-09-01", {"BIDV": {12: 5.90}}), path)
    snapshots.append(snapshot("2026-09-01", {"BIDV": {12: 6.20}}), path)
    stored = snapshots.load(path)
    assert len(stored) == 1
    assert stored[0].by_tenor(12)["BIDV"] == 6.20


def test_captures_survive_a_round_trip_with_their_boards(tmp_path):
    path = tmp_path / "snap.json"
    original = RateSnapshot(captured_at="2026-09-01T09:00:00", source="test",
                            quotes=[RateQuote("BIDV", 12, 5.9, "counter"),
                                    RateQuote("BIDV", 12, 6.1, "online")],
                            crosscheck={"agrees": True, "checked": True})
    snapshots.append(original, path)
    back = snapshots.load(path)[0]
    assert back.by_tenor(12, "counter") == {"BIDV": 5.9}
    assert back.by_tenor(12, "online") == {"BIDV": 6.1}
    assert back.crosscheck["agrees"] is True


def test_the_series_for_one_bank_is_ready_for_the_timeseries_module(tmp_path):
    history = [snapshot("2026-09-01", {"BIDV": {12: 5.90}}),
               snapshot("2026-09-02", {"BIDV": {12: 6.20}})]
    rows = snapshots.series(history, "BIDV", 12)
    assert rows == [{"date": dt.date(2026, 9, 1), "rate_pct": 5.90},
                    {"date": dt.date(2026, 9, 2), "rate_pct": 6.20}]


def test_a_corrupt_store_loses_the_history_rather_than_the_dashboard(tmp_path):
    path = tmp_path / "snap.json"
    path.write_text("{ not json", encoding="utf-8")
    assert snapshots.load(path) == []


# --- the trend chart ------------------------------------------------------

def test_one_capture_draws_no_trend(tmp_path):
    """A line through one point reads as "the rate did not move" when it means
    "we have only looked once"."""
    history = [snapshot("2026-09-01", {"BIDV": {12: 5.90}})]
    assert bank_rates.render_trend(history, ["BIDV"], tmp_path / "t.png") is None


def test_two_captures_draw_a_trend(tmp_path):
    history = [snapshot("2026-09-01", {"BIDV": {12: 5.90}}),
               snapshot("2026-09-02", {"BIDV": {12: 6.20}})]
    path = bank_rates.render_trend(history, ["BIDV"], tmp_path / "t.png")
    assert path is not None and path.exists()


def test_no_more_than_three_banks_are_plotted(tmp_path):
    """Three is the number of series colours that stay distinguishable; a
    fourth line would need a hue that does not."""
    rates = {bank: {12: 5.0 + i} for i, bank in enumerate(["A", "B", "C", "D"])}
    history = [snapshot("2026-09-01", rates), snapshot("2026-09-02", rates)]
    rows = bank_rates.trend_rows(history, ["A", "B", "C", "D"])
    assert len(rows[0]) == 5          # date + four banks, before the cap
    assert bank_rates.MAX_TREND_BANKS == 3
