"""
The two places a model could put something false in front of a customer.

Neither test calls a model. Both test the guard that stands between the model
and the page, because that guard is what makes the model safe to use at all.
"""

from __future__ import annotations

import datetime as dt

from src.llm import insight, planner
from src.timeseries import analyse

CATALOGUE = {"ty_gia_usd_vnd": "Tỷ giá USD/VND theo ngày"}
BASE = dt.date(2026, 6, 1)


def _analysis():
    values = [26100.0 + (i % 5) * 3 for i in range(40)]
    values[20] *= 1.03
    rows = [{"date": BASE + dt.timedelta(days=i), "rate": v} for i, v in enumerate(values)]
    return analyse(rows, value_field="rate", unit="VND/USD")


# --- planner: a plan can never contain something fetchable ---------------

def test_a_registry_key_the_catalogue_does_not_have_becomes_none():
    """The whole anti-hallucination story in one assertion: a model may name
    any source it likes and none of them run."""
    assert planner._fallback("cái gì đó lạ", CATALOGUE).registry_key is None


def test_domain_hints_are_stripped_to_bare_hostnames():
    cleaned = planner._clean_domains([
        "https://sbv.gov.vn/tygia/lich-su?x=1",   # a URL, not a hint
        "www.vietcombank.com.vn",
        "không phải tên miền",
        "sbv.gov.vn",                             # duplicate of the first
    ])
    assert cleaned == ["sbv.gov.vn", "vietcombank.com.vn"]
    assert all("/" not in d and not d.startswith("http") for d in cleaned)


def test_field_names_survive_vietnamese_input():
    assert planner._slug("Tỷ giá USD/VND") == "ty_gia_usd_vnd"
    assert planner._slug("Giá vàng SJC (đồng)") == "gia_vang_sjc_dong"
    assert planner._slug("") == "value"


def test_the_fallback_plan_works_with_no_model_at_all():
    plan = planner._fallback("tỷ giá USD/VND", CATALOGUE)
    assert plan.from_model is False
    assert plan.search_queries == ["tỷ giá USD/VND"]
    assert plan.domain_hints == []


# --- insight: every number in the sentence was supplied ------------------

def test_a_number_that_was_never_supplied_is_caught():
    allowed = insight.allowed_values(_analysis())
    assert insight.check_numbers("Tỷ giá giảm 47,3% trong kỳ.", allowed)
    assert insight.check_numbers("Chạm đáy 19.500 VND/USD.", allowed)


def test_the_real_numbers_pass_including_sensible_rounding():
    analysis = _analysis()
    allowed = insight.allowed_values(analysis)
    exact = f"Thay đổi {analysis.change:.2f}% trong kỳ."
    rounded = f"Thay đổi {analysis.change:.1f}% trong kỳ."
    assert insight.check_numbers(exact, allowed) == []
    assert insight.check_numbers(rounded, allowed) == []


def test_counts_and_years_are_not_treated_as_claims():
    allowed = insight.allowed_values(_analysis())
    assert insight.check_numbers("Có 3 phiên như vậy trong năm 2026.", allowed) == []


def test_the_template_is_always_available_and_quotes_only_real_numbers():
    analysis = _analysis()
    text = insight.template(analysis, "Tỷ giá USD/VND")
    assert insight.check_numbers(text, insight.allowed_values(analysis)) == []
    assert len(text) > 60


def test_no_usable_model_still_produces_a_correct_paragraph():
    """The model is the optional layer. Naming one that is not installed has
    to degrade to the template, not to an exception on the customer's page."""
    analysis = _analysis()
    result = insight.write(analysis, "Tỷ giá USD/VND", model="khong-co-model-nay:0b")
    assert result.origin == "template"
    assert insight.check_numbers(result.text, insight.allowed_values(analysis)) == []


# --- the direction guard: a right number sent the wrong way ---------------

def _rate_analysis():
    """A rate series that rises hard and comes back down in two smaller steps.

    The rise and the falls have to differ in size. A symmetric spike gives a
    +20 and a -20, and "giảm 20" is then a true statement about the second
    move -- which the guard correctly allows, and which would make this test
    assert the opposite of what it means to."""
    values = [3.0] * 8 + [23.0, 13.0] + [3.0] * 10
    rows = [{"date": dt.date(2005 + i, 1, 1), "rate": v} for i, v in enumerate(values)]
    return analyse(rows, value_field="rate", unit="%")


def test_a_rise_reported_as_a_fall_is_caught():
    """The failure this guard was written for: asked about a year when the
    rate rose, a model wrote "mức giảm" in front of the right figure. Every
    number checked out, and the claim was backwards."""
    analysis = _rate_analysis()
    rise = next(a for a in analysis.anomalies if a.direction == "tăng")
    wrong = f"Chỉ số giảm {abs(rise.change):.2f} điểm phần trăm trong kỳ đó."
    right = f"Chỉ số tăng {abs(rise.change):.2f} điểm phần trăm trong kỳ đó."

    assert insight.check_numbers(wrong, insight.allowed_values(analysis)) == []
    assert insight.check_directions(wrong, analysis)
    assert insight.check_directions(right, analysis) == []


def test_the_overall_trend_direction_is_checked_too():
    analysis = _rate_analysis()
    stated_backwards = f"Cả kỳ chỉ số {'tăng' if analysis.change < 0 else 'giảm'} " \
                       f"{abs(analysis.change):.2f} điểm phần trăm."
    assert insight.check_directions(stated_backwards, analysis)


def test_a_figure_with_no_direction_attached_is_left_alone():
    """Minimums and maximums do not move, so a sentence quoting one is the
    number guard's business, not this one's."""
    analysis = _rate_analysis()
    assert insight.check_directions(
        f"Mức cao nhất trong kỳ là {analysis.maximum:.2f}%.", analysis) == []


def test_a_backwards_paragraph_falls_back_to_the_template():
    analysis = _rate_analysis()
    result = insight.write(analysis, "Chỉ số thử", model="khong-co-model-nay:0b")
    assert result.origin == "template"
    assert insight.check_directions(result.text, analysis) == []
