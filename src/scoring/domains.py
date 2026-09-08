"""
How much a domain is worth before anyone looks at its numbers.

The tiers are about *provenance*, not accuracy: a statistics office can publish
a wrong figure and an aggregator can copy a right one. What the tier encodes is
who is accountable for the number and who merely repeated it -- which is the
only thing a rule can judge without reading the data.

Scored by suffix first, then by an explicit seed list, because a suffix is a
weak signal that generalises and a seed list is a strong signal that does not.
`vietcombank.com.vn` is a `.com.vn` like any shop; only the seed list knows it
is a bank.

Deliberately not here: any judgement by a model. An LLM asked "is this source
credible?" produces a fluent number with nothing behind it, and the number
moves between runs on identical input. Provenance is a lookup, so it is one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class Tier(str, Enum):
    GOVERNMENT = "government"       # a state body or a central bank
    ACADEMIC = "academic"           # universities, international organisations
    BANK = "bank"                   # a commercial bank publishing its own board
    PRESS = "press"                 # established news organisations
    AGGREGATOR = "aggregator"       # re-publishers, open datasets, unknowns


# The points each tier carries. Confirmed with the project owner rather than
# invented here, because the threshold is meaningless without them.
TIER_POINTS: dict[Tier, int] = {
    Tier.GOVERNMENT: 50,
    Tier.ACADEMIC: 45,
    Tier.BANK: 40,
    Tier.PRESS: 30,
    Tier.AGGREGATOR: 15,
}

# Plain language, for the customer-facing UI. No jargon, no scores explained.
TIER_LABEL: dict[Tier, str] = {
    Tier.GOVERNMENT: "Cơ quan nhà nước / ngân hàng trung ương",
    Tier.ACADEMIC: "Trường đại học / tổ chức quốc tế",
    Tier.BANK: "Ngân hàng công bố số liệu của chính mình",
    Tier.PRESS: "Cơ quan báo chí lớn",
    Tier.AGGREGATOR: "Trang tổng hợp lại từ nơi khác",
}

# Checked in order; the first suffix that matches wins.
SUFFIX_TIERS: list[tuple[str, Tier]] = [
    (".gov.vn", Tier.GOVERNMENT),
    (".gov.uk", Tier.GOVERNMENT),
    (".gov", Tier.GOVERNMENT),
    (".gouv.fr", Tier.GOVERNMENT),
    (".edu.vn", Tier.ACADEMIC),
    (".edu", Tier.ACADEMIC),
    (".ac.uk", Tier.ACADEMIC),
]

# Domains a suffix cannot classify. Seeded for Vietnamese finance because that
# is the area the first topics cover; the tier machinery itself is not
# finance-specific, and adding a health or education seed is one line each.
SEED_DOMAINS: dict[str, Tier] = {
    # Central bank and statistics
    "sbv.gov.vn": Tier.GOVERNMENT,
    "gso.gov.vn": Tier.GOVERNMENT,
    "mof.gov.vn": Tier.GOVERNMENT,
    "customs.gov.vn": Tier.GOVERNMENT,
    "moit.gov.vn": Tier.GOVERNMENT,
    # International organisations
    "worldbank.org": Tier.ACADEMIC,
    "data.worldbank.org": Tier.ACADEMIC,
    "imf.org": Tier.ACADEMIC,
    "who.int": Tier.ACADEMIC,
    "oecd.org": Tier.ACADEMIC,
    # Commercial banks publishing their own rate boards
    "vietcombank.com.vn": Tier.BANK,
    "bidv.com.vn": Tier.BANK,
    "vietinbank.vn": Tier.BANK,
    "agribank.com.vn": Tier.BANK,
    "techcombank.com.vn": Tier.BANK,
    "acb.com.vn": Tier.BANK,
    "sacombank.com.vn": Tier.BANK,
    "mbbank.com.vn": Tier.BANK,
    # Press
    "vnexpress.net": Tier.PRESS,
    "tuoitre.vn": Tier.PRESS,
    "thanhnien.vn": Tier.PRESS,
    "vietnamnet.vn": Tier.PRESS,
    "reuters.com": Tier.PRESS,
    "bloomberg.com": Tier.PRESS,
}


@dataclass(frozen=True)
class DomainVerdict:
    domain: str
    tier: Tier
    points: int
    # Why this tier, in words a customer can read.
    reason: str


def domain_of(url: str) -> str:
    host = urlparse(url if "//" in url else "//" + url).hostname or ""
    return host.lower().removeprefix("www.")


def classify(url: str) -> DomainVerdict:
    """Tier for a URL. Never raises, never returns None: an unknown host is an
    aggregator, which is the assumption that costs the least when wrong."""
    domain = domain_of(url)

    if domain in SEED_DOMAINS:
        tier = SEED_DOMAINS[domain]
        return DomainVerdict(domain, tier, TIER_POINTS[tier],
                             f"{TIER_LABEL[tier]} ({domain})")

    # A seeded domain also vouches for its own subdomains.
    for seed, tier in SEED_DOMAINS.items():
        if domain.endswith("." + seed):
            return DomainVerdict(domain, tier, TIER_POINTS[tier],
                                 f"{TIER_LABEL[tier]} ({seed})")

    for suffix, tier in SUFFIX_TIERS:
        if domain.endswith(suffix):
            return DomainVerdict(domain, tier, TIER_POINTS[tier],
                                 f"{TIER_LABEL[tier]} (tên miền {suffix})")

    return DomainVerdict(domain, Tier.AGGREGATOR, TIER_POINTS[Tier.AGGREGATOR],
                         f"{TIER_LABEL[Tier.AGGREGATOR]} ({domain or 'không rõ'})")
