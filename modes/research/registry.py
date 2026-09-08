from __future__ import annotations
import datetime as dt
from dataclasses import dataclass
from typing import Callable
from modes.research.sources import Source, imf_source, open_fx_source, vcb_rate_source, worldbank_source

DAILY_MAX_SPAN_DAYS = 400

CATEGORIES = ("market_price", "macro_aggregate")

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
    description: str
    metric_label: str
    value_field: str
    unit: str
    build: Callable[[list[dt.date]], list[Source]]
    category: str = "market_price"
    frequency: str = "daily"       
    max_span_days: int | None = None
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
    return {key: entry.description for key, entry in CATALOGUE.items()}


def _best_match(topic: str, vocabularies: dict[str, tuple[str, ...]]) -> str | None:
    lowered = " " + topic.lower().strip() + " "
    best, best_score = None, 0
    for key, words in vocabularies.items():
        score = sum(len(word) for word in words if word in lowered)
        if score > best_score:
            best, best_score = key, score
    return best


def match_keywords(topic: str) -> str | None:
    return _best_match(topic, {key: entry.keywords for key, entry in CATALOGUE.items()})


def match_category(topic: str) -> str | None:
    return _best_match(topic, CATEGORY_KEYWORDS)
