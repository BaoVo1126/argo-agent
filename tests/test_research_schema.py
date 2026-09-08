from __future__ import annotations
import datetime as dt
from modes.research.pipeline import _merge
from modes.research.pipeline import SourceReport
from src.scoring import CredibilityScore
from src.scoring.domains import Tier
from modes.research.schema import Field, Schema, parse_date, parse_number, validate

SCHEMA = Schema(
    name="t",
    fields=[
        Field("date", "date", required=True),
        Field("gold_price_vnd", "number", required=True),
        Field("usd_vnd_rate", "number", required=False),
    ],
    key=("date",),
)


def test_thousands_separators_both_conventions():
    assert parse_number("26,100.00") == 26100.0   
    assert parse_number("158.500.000") == 158500000.0  
    assert parse_number("158.5") == 158.5         


def test_unparseable_is_none_never_zero():
    assert parse_number("n/a") is None
    assert parse_number(None) is None


def test_dates_from_the_formats_sites_actually_use():
    assert parse_date("2026-08-03") == dt.date(2026, 8, 3)
    assert parse_date("03/08/2026") == dt.date(2026, 8, 3)


def test_coverage_counts_the_field_not_the_row():
    rows = [
        {"date": "2026-06-01", "gold_price_vnd": "150000000", "usd_vnd_rate": "26000"},
        {"date": "2026-06-02", "gold_price_vnd": "151000000", "usd_vnd_rate": None},
    ]
    clean, report = validate(rows, SCHEMA)
    assert len(clean) == 2                  
    assert report.coverage("gold_price_vnd") == 100.0
    assert report.coverage("usd_vnd_rate") == 50.0


def test_a_row_missing_a_required_field_is_dropped_not_filled():
    rows = [{"date": "2026-06-01", "gold_price_vnd": None}]
    clean, report = validate(rows, SCHEMA)
    assert clean == []
    assert report.dropped_missing_required == 1


def test_duplicate_keys_collapse_to_the_last_observation():
    rows = [
        {"date": "2026-06-01", "gold_price_vnd": "150000000"},
        {"date": "2026-06-01", "gold_price_vnd": "151000000"},
    ]
    clean, report = validate(rows, SCHEMA)
    assert len(clean) == 1
    assert clean[0]["gold_price_vnd"] == 151000000.0
    assert report.duplicates_merged == 1


def _report(label: str, total: int) -> SourceReport:
    report = SourceReport(name=label, label=label, site=label, url="", ok=True)
    report.credibility = CredibilityScore(source=label, url="", domain=label,
                                          tier=Tier.BANK, total=total, threshold=60,
                                          accepted=True)
    return report


def test_the_higher_scoring_source_wins_a_day_rather_than_being_averaged():
    strong = _report("strong", 70)
    weak = _report("weak", 60)
    rows = _merge(
        [
            (weak, [{"date": dt.date(2026, 6, 1), "rate": 100.0},
                    {"date": dt.date(2026, 6, 2), "rate": 200.0}]),
            (strong, [{"date": dt.date(2026, 6, 1), "rate": 111.0}]),
        ],
        "rate",
    )
    assert [r["rate"] for r in rows] == [111.0, 200.0]


def test_merge_returns_days_in_order_whatever_order_the_sources_came_in():
    strong = _report("strong", 70)
    rows = _merge([(strong, [{"date": dt.date(2026, 6, 3), "rate": 3.0},
                             {"date": dt.date(2026, 6, 1), "rate": 1.0}])], "rate")
    assert [r["date"].day for r in rows] == [1, 3]
