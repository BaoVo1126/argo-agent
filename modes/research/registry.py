"""
The catalogue of dated-series topics Argo knows how to gather.

This is the secondary flow. The product is the savings-rate comparison in
`bank_rates.py`, which is a bank-by-tenor board rather than one dated series
and has its own pipeline. What stays here are the macro and market series that
share a shape: one number per date, from sources that are all trying to
measure the same thing.

That shared shape is why `src/scoring` works on these and not on rates. Two
bodies publishing Vietnam's inflation are two readings of one truth, so their
agreement is evidence. Two banks publishing their own deposit rates are two
different decisions, and their disagreement is the whole point.

`category` records which kind a topic is, so a caller never has to infer it
from the topic's name.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Callable

from modes.research.sources import Source, imf_source, open_fx_source, vcb_rate_source, worldbank_source

# A daily source that fetches one request per day cannot be pointed at ten
# years: that is 3,650 requests at a site that never asked for them. Windows
# wider than this are clipped, and the customer is told.
DAILY_MAX_SPAN_DAYS = 400

# What kind of quantity a topic is about.
#   market_price     -- a price set by a market, quoted continuously
#   macro_aggregate  -- an estimate of an economy, published periodically
# The savings-rate board is neither, and lives in `bank_rates.py`.
CATEGORIES = ("market_price", "macro_aggregate")

# What makes a typed topic belong to a category, when no catalogue entry
# matched it. This is the gate on `modes/research/pool.py`: a topic that lands
# in a category may be looked for among that category's vetted domains, and a
# topic that lands nowhere ends the run with "chưa hỗ trợ lĩnh vực này".
#
# Deliberately a lookup rather than a model, for the same reason
# `match_keywords` is. Asked to classify "lạm phát Việt Nam" a 3B model will
# answer fluently and sometimes wrongly, and here a wrong answer does not
# produce a bad chart -- it produces a scrape of the wrong seventeen sites.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "market_price": (
        "gia vang", "gia vàng", "giá vàng", "vang mieng", "vàng miếng",
        "ty gia", "tỷ giá", "ngoai te", "ngoại tệ", "usd", "eur", "jpy",
        "do la", "đô la", "dollar", "lai suat", "lãi suất", "tiet kiem",
        "tiết kiệm", "xang", "xăng", "dau", "dầu", "gia xang", "giá xăng",
        "chung khoan", "chứng khoán", "co phieu", "cổ phiếu", "vn-index",
        "vnindex", "chi so gia", "gia ban le", "giá bán lẻ", "niem yet", "niêm yết",
    ),
    "macro_aggregate": (
        "lam phat", "lạm phát", "cpi", "gdp", "gnp", "that nghiep", "thất nghiệp",
        "viec lam", "việc làm", "lao dong", "lao động", "dan so", "dân số",
        "xuat khau", "xuất khẩu", "nhap khau", "nhập khẩu", "kim ngach",
        "kim ngạch", "fdi", "dau tu nuoc ngoai", "đầu tư nước ngoài",
        "ngan sach", "ngân sách", "no cong", "nợ công", "tang truong",
        "tăng trưởng", "thu nhap binh quan", "thu nhập bình quân",
        "nang suat", "năng suất", "tuoi tho", "tuổi thọ", "ty le ngheo",
        "tỷ lệ nghèo", "vi mo", "vĩ mô", "thong ke", "thống kê",
    ),
}


@dataclass(frozen=True)
class TopicEntry:
    key: str
    # Shown to the planner so it can match a typed sentence to this entry.
    description: str
    metric_label: str
    value_field: str
    unit: str
    build: Callable[[list[dt.date]], list[Source]]
    category: str = "market_price"
    frequency: str = "daily"            # daily | yearly
    max_span_days: int | None = None
    # Words that make this entry the obvious match without a model.
    keywords: tuple[str, ...] = ()


def _fx_sources(dates: list[dt.date]) -> list[Source]:
    return [
        vcb_rate_source(dates, "usd_vnd_rate", code="USD"),
        open_fx_source(dates, "usd_vnd_rate", base="usd", quote="vnd"),
    ]


def _inflation_sources(_dates: list[dt.date]) -> list[Source]:
    return [
        worldbank_source("FP.CPI.TOTL.ZG", "inflation_pct",
                         "Lạm phát giá tiêu dùng", "%"),
        imf_source("PCPIPCH", "inflation_pct", "Lạm phát giá tiêu dùng", "%"),
    ]


def _gdp_per_capita_sources(_dates: list[dt.date]) -> list[Source]:
    return [
        worldbank_source("NY.GDP.PCAP.CD", "gdp_per_capita_usd",
                         "GDP bình quân đầu người", "USD"),
        imf_source("NGDPDPC", "gdp_per_capita_usd",
                   "GDP bình quân đầu người", "USD"),
    ]


CATALOGUE: dict[str, TopicEntry] = {
    "ty_gia_usd_vnd": TopicEntry(
        key="ty_gia_usd_vnd",
        description="Tỷ giá USD/VND theo ngày (ngân hàng thương mại và bộ dữ liệu mở)",
        metric_label="Tỷ giá USD/VND",
        value_field="usd_vnd_rate",
        unit="VND/USD",
        build=_fx_sources,
        category="market_price",
        frequency="daily",
        max_span_days=DAILY_MAX_SPAN_DAYS,
        keywords=("tỷ giá", "ty gia", "usd", "đô la", "do la", "dollar", "ngoại tệ"),
    ),
    "lam_phat_vietnam": TopicEntry(
        key="lam_phat_vietnam",
        description="Lạm phát giá tiêu dùng của Việt Nam theo năm (World Bank và IMF)",
        metric_label="Lạm phát Việt Nam",
        value_field="inflation_pct",
        unit="%",
        build=_inflation_sources,
        category="macro_aggregate",
        frequency="yearly",
        keywords=("lạm phát", "lam phat", "cpi", "giá tiêu dùng", "inflation"),
    ),
    "gdp_binh_quan_vietnam": TopicEntry(
        key="gdp_binh_quan_vietnam",
        description="GDP bình quân đầu người của Việt Nam theo năm (World Bank và IMF)",
        metric_label="GDP bình quân đầu người",
        value_field="gdp_per_capita_usd",
        unit="USD",
        build=_gdp_per_capita_sources,
        category="macro_aggregate",
        frequency="yearly",
        keywords=("gdp", "thu nhập bình quân", "binh quan dau nguoi", "gdp đầu người"),
    ),
}


def planner_catalogue() -> dict[str, str]:
    """Keys and descriptions, as the planner prompt needs them."""
    return {key: entry.description for key, entry in CATALOGUE.items()}


def _best_match(topic: str, vocabularies: dict[str, tuple[str, ...]]) -> str | None:
    """Whichever key's words the topic contains most of, or None for none.

    Weighted by phrase length: "lạm phát" appearing is far stronger evidence
    than "gdp" appearing, and counting both as one hit lets a short incidental
    word outvote a specific one.
    """
    lowered = " " + topic.lower().strip() + " "
    best, best_score = None, 0
    for key, words in vocabularies.items():
        score = sum(len(word) for word in words if word in lowered)
        if score > best_score:
            best, best_score = key, score
    return best


def match_keywords(topic: str) -> str | None:
    """Best catalogue entry for a typed topic, without asking a model.

    The customer's own words decide which entry runs; the model only gets a say
    when they match nothing. A 3B model asked about "lạm phát Việt Nam" once
    returned the key for GDP per capita, and matching a handful of entries
    against typed words is a job a lookup does better.
    """
    return _best_match(topic, {key: entry.keywords for key, entry in CATALOGUE.items()})


def match_category(topic: str) -> str | None:
    """Which kind of quantity a typed topic is about, or None if unrecognised.

    Only consulted once `match_keywords` has come up empty, and its answer
    decides which pool of vetted domains the run is allowed to open. None is a
    real answer here rather than a failure to decide: it means the topic is
    outside every field this project has vetted sources for, and the run says
    so instead of widening its search until something turns up.
    """
    return _best_match(topic, CATEGORY_KEYWORDS)
