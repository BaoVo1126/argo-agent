from __future__ import annotations
import datetime as dt
from src.scoring import HealthRecord, SourceEvidence, Tier, classify, score
from src.scoring.credibility import DEFAULT_THRESHOLD

BASE = dt.date(2026, 6, 1)


def series(start: float, step: float = 1.0, days: int = 40) -> list[dict]:
    return [{"date": BASE + dt.timedelta(days=i), "value": start + i * step}
            for i in range(days)]


def evidence(name: str, url: str, rows: list[dict], **kw) -> SourceEvidence:
    return SourceEvidence(name=name, url=url, rows=rows, value_field="value",
                          label=kw.pop("label", name), **kw)


def health_for(*urls: str) -> HealthRecord:
    record = HealthRecord()
    for url in urls:
        record.record_success(url, classify(url).tier, rows=40)
    return record


def test_government_and_bank_are_read_off_the_url_not_the_name():
    assert classify("https://sbv.gov.vn/x").tier is Tier.GOVERNMENT
    assert classify("https://www.vietcombank.com.vn/api").tier is Tier.BANK
    assert classify("https://data.worldbank.org/i").tier is Tier.ACADEMIC
    assert classify("https://vnexpress.net/y").tier is Tier.PRESS


def test_unknown_host_is_an_aggregator_not_an_error():
    verdict = classify("https://some-blog-nobody-knows.xyz/page")
    assert verdict.tier is Tier.AGGREGATOR
    assert verdict.points == 15


def test_a_subdomain_inherits_its_parents_tier():
    assert classify("https://api.worldbank.org/v2").tier is Tier.ACADEMIC


def test_an_official_source_passes_alone_once_verified():
    url = "https://sbv.gov.vn/x"
    scores = score([evidence("sbv", url, series(24800))], health=health_for(url))
    assert scores[0].total == 60 and scores[0].accepted


def test_a_bank_needs_corroboration_to_pass():
    bank, feed = "https://www.vietcombank.com.vn/a", "https://cdn.example.org/x"
    record = health_for(bank, feed, "https://sbv.gov.vn/x")

    alone = score([evidence("vcb", bank, series(26000))], health=record)
    assert alone[0].total == 50 and not alone[0].accepted

    with_feed = score([
        evidence("vcb", bank, series(26000)),
        evidence("feed", feed, series(26100), label="feed"),
    ], health=record)
    bank = next(s for s in with_feed if s.domain == "vietcombank.com.vn")
    assert bank.total == DEFAULT_THRESHOLD and bank.accepted


def test_an_aggregator_stays_out_even_when_it_is_right():
    scores = score([
        evidence("vcb", "https://www.vietcombank.com.vn/a", series(26000)),
        evidence("agg", "https://webgia.com/x", series(26100), label="agg"),
    ], health=health_for("https://www.vietcombank.com.vn/a", "https://webgia.com/x",
                         "https://sbv.gov.vn/x"))
    aggregator = next(s for s in scores if s.domain == "webgia.com")
    assert aggregator.agrees_with == ["vcb"]
    assert aggregator.total == 35 and not aggregator.accepted


def test_a_different_quantity_is_not_corroboration():
    scores = score([
        evidence("vcb", "https://www.vietcombank.com.vn/a", series(26000)),
        evidence("other", "https://cdn.example.org/x", series(24700), label="other"),
    ], health=health_for("https://www.vietcombank.com.vn/a", "https://cdn.example.org/x",
                         "https://sbv.gov.vn/x"))
    assert all(s.agrees_with == [] for s in scores)


def test_a_crowd_of_copies_cannot_outvote_provenance():
    urls = [f"https://copy{i}.example.com/x" for i in range(5)]
    copies = [evidence(f"c{i}", url, series(26000), label=f"c{i}")
              for i, url in enumerate(urls)]
    scores = score(copies, health=health_for("https://sbv.gov.vn/x", *urls))
    assert all(s.total == 15 + 30 + 10 for s in scores)   
    assert not any(s.accepted for s in scores)


def test_numbers_read_out_of_prose_lose_the_structure_points():
    url = "https://sbv.gov.vn/x"
    scores = score([evidence("x", url, series(24800), structured=False)],
                   health=health_for(url))
    assert scores[0].total == 50 and not scores[0].accepted


def test_too_little_overlap_is_not_agreement():
    scores = score([
        evidence("a", "https://www.vietcombank.com.vn/a", series(26000, days=40)),
        evidence("b", "https://cdn.example.org/b", series(26000, days=3), label="b"),
    ], health=health_for("https://www.vietcombank.com.vn/a", "https://cdn.example.org/b",
                         "https://sbv.gov.vn/x"))
    assert all(s.agrees_with == [] for s in scores)


def test_a_domain_never_scraped_scores_nothing_for_provenance():
    scores = score([evidence("sbv", "https://sbv.gov.vn/x", series(24800))],
                   health=HealthRecord())
    assert scores[0].verified is False
    assert scores[0].total == 10          # structure points only
    assert "Chưa lấy được số liệu" in scores[0].lines[0].label


def test_one_successful_scrape_is_what_turns_the_tier_on():
    url = "https://sbv.gov.vn/x"
    before = score([evidence("sbv", url, series(24800))], health=HealthRecord())
    after = score([evidence("sbv", url, series(24800))], health=health_for(url))
    assert before[0].total == 10
    assert after[0].total == 60


def test_the_threshold_is_suspended_until_an_official_source_is_verified():
    bank = "https://www.vietcombank.com.vn/a"
    only_a_bank = health_for(bank)
    assert only_a_bank.threshold_active() is False

    scores = score([evidence("vcb", bank, series(26000))], health=only_a_bank)
    assert scores[0].threshold_enforced is False
    assert scores[0].accepted is True  
    assert scores[0].total == 50          


def test_verifying_an_official_source_switches_the_threshold_back_on():
    record = health_for("https://www.vietcombank.com.vn/a")
    assert record.threshold_active() is False
    record.record_success("https://api.worldbank.org/v2/x", Tier.ACADEMIC, rows=60)
    assert record.threshold_active() is True
    assert record.verified_high_tier() == ["api.worldbank.org"]


def test_a_source_that_returned_nothing_does_not_get_verified():
    record = HealthRecord()
    record.record_success("https://sbv.gov.vn/x", Tier.GOVERNMENT, rows=0)
    assert record.is_verified("https://sbv.gov.vn/x") is False


def test_verification_survives_a_later_outage(tmp_path):
    path = tmp_path / "health.json"
    record = HealthRecord(path=path)
    record.record_success("https://api.worldbank.org/v2/x", Tier.ACADEMIC, rows=60)
    record.save()

    reloaded = HealthRecord.load(path)
    assert reloaded.is_verified("https://api.worldbank.org/v2/x")
    assert reloaded.threshold_active()


def test_a_corrupt_record_verifies_nothing_rather_than_guessing(tmp_path):
    path = tmp_path / "health.json"
    path.write_text("{ not json", encoding="utf-8")
    record = HealthRecord.load(path)
    assert record.domains == {}
    assert record.threshold_active() is False
