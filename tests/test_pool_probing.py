from __future__ import annotations
import datetime as dt
import pathlib
import unicodedata
from urllib.parse import urlparse
import pytest
from modes.research import discovery, pool
from modes.research.registry import CATEGORIES, match_category, match_keywords
from modes.research.trace import Trace
from src.scoring.credibility import CONSENSUS_POINTS_MAX, STRUCTURE_POINTS
from src.scoring.domains import TIER_POINTS, Tier, classify
from src.scoring.health import SUSPEND_AFTER_FAILURES, HealthRecord

def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in stripped
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


START = dt.date(2026, 1, 1)
END = dt.date(2026, 12, 31)


def test_every_category_has_a_pool_of_the_agreed_size():
    for category in CATEGORIES:
        entries = pool.for_category(category)
        assert 15 <= len(entries) <= 20, f"{category} has {len(entries)} domains"


def test_an_unknown_category_opens_no_pool_at_all():
    assert pool.for_category("bong_da") == ()
    assert pool.for_category("") == ()


def test_domains_are_unique_within_a_pool():
    for category in CATEGORIES:
        domains = [entry.domain for entry in pool.for_category(category)]
        assert len(domains) == len(set(domains)), f"{category} repeats a domain"


@pytest.mark.parametrize("category", CATEGORIES)
def test_no_address_in_a_pool_leaves_its_own_domain(category):
    for entry in pool.for_category(category):
        for url in entry.urls("lam phat viet nam"):
            host = (urlparse(url).hostname or "").removeprefix("www.")
            assert url.startswith("https://"), f"{entry.domain}: {url} is not https"
            assert host == entry.domain or host.endswith("." + entry.domain), (
                f"{entry.domain} would fetch {host}")


def test_a_domain_with_no_paths_still_has_somewhere_to_go():
    entry = pool.PoolDomain("example.gov.vn", "Ví dụ")
    assert entry.urls("bất kỳ") == ["https://example.gov.vn/"]


def test_the_search_template_is_only_used_when_there_is_a_query():
    entry = pool.PoolDomain("gso.gov.vn", "TCTK", paths=("/a",),
                            search="https://gso.gov.vn/?s={q}")
    assert entry.urls("   ") == ["https://gso.gov.vn/a"]
    assert entry.urls("lạm phát")[-1] == "https://gso.gov.vn/?s=l%E1%BA%A1m+ph%C3%A1t"


@pytest.mark.parametrize("topic,expected", [
    ("giá vàng SJC hôm nay", "market_price"),
    ("giá xăng RON95", "market_price"),
    ("tỷ lệ thất nghiệp Việt Nam", "macro_aggregate"),
    ("kim ngạch xuất khẩu", "macro_aggregate"),
])
def test_a_topic_without_an_adapter_still_finds_its_category(topic, expected):
    assert match_keywords(topic) is None, "this topic is supposed to have no adapter"
    assert match_category(topic) == expected


@pytest.mark.parametrize("topic", [
    "đội hình Manchester United mùa này",
    "công thức nấu phở bò",
    "lịch chiếu phim cuối tuần",
])
def test_a_topic_outside_every_category_is_not_placed_anywhere(topic):
    assert match_category(topic) is None

def test_a_domain_rests_only_after_repeated_failures(tmp_path):
    record = HealthRecord(path=tmp_path / "health.json")
    url = "https://molisa.gov.vn/"

    for _ in range(SUSPEND_AFTER_FAILURES - 1):
        assert record.record_failure(url, Tier.GOVERNMENT, "timeout") is False
        assert not record.is_suspended(url)

    assert record.record_failure(url, Tier.GOVERNMENT, "timeout") is True
    assert record.is_suspended(url)
    assert "molisa.gov.vn" in record.suspended_domains()
    assert "Tạm ngưng" in record.suspension_note(url)


def test_a_suspension_is_never_a_removal(tmp_path):
    record = HealthRecord(path=tmp_path / "health.json")
    for _ in range(SUSPEND_AFTER_FAILURES):
        record.record_failure("https://gso.gov.vn/", Tier.GOVERNMENT)
    assert record.is_suspended("gso.gov.vn")
    assert "gso.gov.vn" in {e.domain for e in pool.for_category("macro_aggregate")}


def test_working_once_clears_the_slate(tmp_path):
    record = HealthRecord(path=tmp_path / "health.json")
    for _ in range(SUSPEND_AFTER_FAILURES):
        record.record_failure("https://gso.gov.vn/", Tier.GOVERNMENT)
    assert record.is_suspended("gso.gov.vn")

    record.record_success("https://gso.gov.vn/so-lieu/", Tier.GOVERNMENT, rows=40)
    assert not record.is_suspended("gso.gov.vn")
    assert record.is_verified("gso.gov.vn")
    assert record.domains["gso.gov.vn"].failures == 0


def test_suspension_survives_a_save_and_reload(tmp_path):
    path = tmp_path / "health.json"
    record = HealthRecord(path=path)
    for _ in range(SUSPEND_AFTER_FAILURES):
        record.record_failure("https://adb.org/", Tier.ACADEMIC, "HTTP 403")
    record.save()

    assert HealthRecord.load(path).is_suspended("adb.org")

def _table(rows: list[list[str]]) -> list[dict]:
    return [{"rows": rows}]


def _dated_rows(n: int = 8, value: float = 100.0) -> list[list[str]]:
    return [["Ngày", "Giá trị"]] + [
        [f"{day:02d}/03/2026", f"{value + day:.2f}"] for day in range(1, n + 1)
    ]


class FakePage:
    def __init__(self, tables_by_url: dict[str, list[dict]],
                 broken: set[str] | None = None):
        self.tables_by_url = tables_by_url
        self.broken = broken or set()
        self.visited: list[str] = []
        self.current = ""

    def goto(self, url, **_kwargs):
        self.visited.append(url)
        if url in self.broken:
            raise TimeoutError("navigation timed out")
        self.current = url

    def title(self):
        return "Bảng số liệu"

    def evaluate(self, _script):
        return self.tables_by_url.get(self.current, [])


def _probe(page, category, health, threshold=60, hints=None):
    trace = Trace()
    sources = discovery.probe_pool(
        page, category, "lạm phát", "value_x", START, END,
        threshold=threshold, health=health, trace=trace, hints=hints)
    return sources, trace


def test_a_domain_that_publishes_a_table_becomes_a_source(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    hit = "https://gso.gov.vn/so-lieu-thong-ke/"
    sources, trace = _probe(FakePage({hit: _table(_dated_rows())}),
                            "macro_aggregate", health)

    assert [s.site for s in sources] == ["gso.gov.vn"]
    assert sources[0].url == hit
    assert sources[0].plan == []
    assert len(sources[0].extract(None)) == 8

    kinds = [e.kind for e in trace.events]
    assert "probe" in kinds and "hit" in kinds and "keep" in kinds
    assert kinds[-1] == "summary"


def test_a_source_that_could_never_pass_is_dropped_while_the_customer_watches(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    ceiling = TIER_POINTS[Tier.AGGREGATOR] + STRUCTURE_POINTS + CONSENSUS_POINTS_MAX
    assert ceiling < 60, "the point of this test is that an aggregator cannot reach 60"

    hit = "https://btmc.vn/bang-gia-vang/"
    assert classify(hit).tier is Tier.AGGREGATOR
    sources, trace = _probe(FakePage({hit: _table(_dated_rows())}),
                            "market_price", health)

    assert sources == []
    dropped = [e for e in trace.events if e.kind == "drop"]
    assert dropped and dropped[0].domain == "btmc.vn"
    assert dropped[0].score == TIER_POINTS[Tier.AGGREGATOR] + STRUCTURE_POINTS


def test_a_domain_that_answers_nothing_is_counted_against_and_then_rested(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    for _ in range(SUSPEND_AFTER_FAILURES - 1):
        health.record_failure("https://gso.gov.vn/", Tier.GOVERNMENT)

    page = FakePage({})       
    _, trace = _probe(page, "macro_aggregate", health)

    assert health.is_suspended("gso.gov.vn")
    assert any(e.kind == "suspend" and e.domain == "gso.gov.vn" for e in trace.events)
    assert any(e.kind == "miss" for e in trace.events)


def test_a_rested_domain_is_passed_over_without_a_page_load(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    for _ in range(SUSPEND_AFTER_FAILURES):
        health.record_failure("https://gso.gov.vn/", Tier.GOVERNMENT)

    page = FakePage({})
    _, trace = _probe(page, "macro_aggregate", health)

    assert not any("gso.gov.vn" in url for url in page.visited)
    skipped = [e for e in trace.events if e.kind == "skip" and e.domain == "gso.gov.vn"]
    assert skipped and "Tạm ngưng" in skipped[0].text


def test_probing_stops_once_enough_sources_are_in_hand(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    everything = {entry.urls("lạm phát")[0]: _table(_dated_rows())
                  for entry in pool.for_category("macro_aggregate")}
    sources, trace = _probe(FakePage(everything), "macro_aggregate", health)

    assert len(sources) == pool.MAX_ACCEPTED
    assert any(e.kind == "skip" and "Đã đủ" in e.text for e in trace.events)


def test_a_planner_hint_reorders_the_pool_and_nothing_more(tmp_path):
    ordered = discovery._ordered(pool.for_category("macro_aggregate"), ["imf.org"])
    assert ordered[0].domain == "imf.org"
    unchanged = discovery._ordered(pool.for_category("macro_aggregate"),
                                   ["khong-ton-tai.example"])
    assert [d.domain for d in unchanged] == \
           [d.domain for d in pool.for_category("macro_aggregate")]


def test_a_page_with_no_dated_table_is_not_guessed_at(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    prose = _table([["Chỉ tiêu", "Nhận xét"]] * 8)
    hit = "https://gso.gov.vn/so-lieu-thong-ke/"
    sources, _ = _probe(FakePage({hit: prose}), "macro_aggregate", health)
    assert sources == []


def test_a_navigation_failure_moves_on_to_the_next_address(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    entry = pool.for_category("macro_aggregate")[0]
    first, second = entry.urls("lạm phát")[0], entry.urls("lạm phát")[1]
    page = FakePage({second: _table(_dated_rows())}, broken={first})

    sources, _ = _probe(page, "macro_aggregate", health)
    assert [s.url for s in sources] == [second]


def test_events_arrive_at_the_sink_as_they_are_made():
    seen = []
    trace = Trace(sink=seen.append)
    trace.event("probe", "Đang kiểm tra gso.gov.vn…", domain="gso.gov.vn")
    trace.event("keep", "Đạt ngưỡng 60/100", domain="gso.gov.vn", score=60)

    assert [e.kind for e in seen] == ["probe", "keep"]
    assert trace.snapshot()[1]["score"] == 60


def test_a_broken_listener_cannot_end_a_run():
    def explode(_event):
        raise RuntimeError("the browser hung up")

    trace = Trace(sink=explode)
    trace.event("phase", "Đang thu thập…")
    assert len(trace.events) == 1

def _plan(topic: str):
    from src.llm.planner import ResearchPlan
    return ResearchPlan(topic=topic, metric_label=topic, value_field="value_x",
                        unit="", frequency="daily", registry_key=None,
                        search_queries=[topic], domain_hints=[], from_model=False)


def test_a_topic_outside_every_field_is_refused_before_a_browser_is_touched(tmp_path):
    from modes.research import pipeline

    class Exploding:
        def __getattr__(self, name):
            raise AssertionError(f"the browser was used ({name}) for a refused topic")

    sources, entry, category, refusal = pipeline._resolve_sources(
        Exploding(), _plan("doi hinh Manchester United mua nay"), START, END,
        lambda _line: None, Trace(), HealthRecord(path=tmp_path / "h.json"), 60)

    assert sources == [] and entry is None and category == ""
    assert "chua ho tro linh vuc nay" in _fold(refusal)


def test_an_unknown_category_probes_nothing(tmp_path):
    page = FakePage({})
    sources, _ = _probe(page, "khong_co_that", HealthRecord(path=tmp_path / "h.json"))
    assert sources == [] and page.visited == []


def test_the_open_web_search_is_gone_for_good():
    source = pathlib.Path(discovery.__file__).read_text(encoding="utf-8")
    for engine in ("duckduckgo", "google.com/search", "bing.com/search"):
        assert engine not in source.lower(), f"{engine} is back in discovery.py"
    assert not hasattr(discovery, "search")


def test_a_site_that_never_answered_is_not_reported_as_having_no_table(tmp_path):
    health = HealthRecord(path=tmp_path / "health.json")
    entry = pool.for_category("macro_aggregate")[0]

    unreachable = FakePage({}, broken=set(entry.urls("lạm phát")))
    _, trace = _probe(unreachable, "macro_aggregate", health)
    missed = next(e for e in trace.events if e.kind == "miss")
    assert "không truy cập được" in missed.text

    silent = FakePage({})            
    _, trace = _probe(silent, "macro_aggregate", HealthRecord(path=tmp_path / "b.json"))
    missed = next(e for e in trace.events if e.kind == "miss")
    assert "không có bảng số liệu" in missed.text
