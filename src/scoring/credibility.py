"""
Whether a source's numbers get used, decided by rules only.

Three components, and each answers a different question:

- **Provenance** (0-50) -- who is accountable for this number? A lookup in
  `domains.py`, but only for a domain that has actually handed over data at
  least once. A publisher nobody has ever successfully scraped scores zero,
  however impressive its suffix: see `health.py` for why the tier table used
  to pay 50 points for a site that had never been fetched.
- **Corroboration** (+10 per other source that reports the same values, capped
  at +30) -- does anyone independent say the same thing? Two sources agreeing
  is the strongest evidence a scraper can obtain without trusting either one.
- **Structure** (+10) -- did the source hand over dated numbers, or did we
  reconstruct them from prose? A published table is a claim; a number lifted
  out of a sentence is an interpretation.

A source at or above the threshold is used. One below it is reported to the
customer with its score and dropped -- not quietly down-weighted, because a
weighted average of a trustworthy and an untrustworthy source is a number
nobody can defend.

**The threshold only applies once it means something.** 60 was chosen as the
point where one authoritative publisher passes alone. Until such a publisher
has actually been verified on this machine, no source can reach it on
provenance, so enforcing the number would reject everything for a reason that
is about this project's coverage rather than about the data. While that is the
case the threshold is suspended, every source that returned data is used, and
the result says so plainly instead of pretending to a rigour it does not have.

**Why corroboration is capped and why agreement is fractional.** Ten
aggregators copying one another is one source wearing ten coats, so the cap
stops a crowd of copies outvoting a bank. And two sources are only counted as
agreeing when most of their *overlapping* days match: a pair that lines up on
three days out of ninety agrees about nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.scoring.domains import DomainVerdict, Tier, classify
from src.scoring.health import HealthRecord

# Confirmed with the project owner. Changing these changes which numbers reach
# the customer, so they live in one place with the reasoning attached.
DEFAULT_THRESHOLD = 60
CONSENSUS_POINTS_EACH = 10
CONSENSUS_POINTS_MAX = 30
STRUCTURE_POINTS = 10

# Two readings of the same quantity taken from different places are never
# identical -- a bank's board and a market feed differ by the spread. 2% is
# wide enough to survive that and narrow enough that a different quantity
# (a central rate, a gold price in a different unit) fails to match.
VALUE_TOLERANCE = 0.02

# Below this share of overlapping keys agreeing, the two sources are not
# talking about the same series.
MIN_AGREEMENT_RATIO = 0.6

# Fewer overlapping days than this and agreement is a coincidence.
MIN_OVERLAP = 5


@dataclass
class SourceEvidence:
    """What one source handed back, before anyone decided to trust it."""

    name: str
    url: str
    rows: list[dict]
    key_field: str = "date"
    value_field: str = "value"
    # True when the numbers arrived as published data -- a table, an official
    # feed -- rather than being read out of prose.
    structured: bool = True
    label: str = ""

    def series(self) -> dict:
        return {
            row[self.key_field]: row[self.value_field]
            for row in self.rows
            if row.get(self.key_field) is not None
            and isinstance(row.get(self.value_field), (int, float))
        }


@dataclass
class ScoreLine:
    """One component of a score, in words the customer can read."""

    label: str
    points: int


@dataclass
class CredibilityScore:
    source: str
    url: str
    domain: str
    tier: Tier
    total: int
    threshold: int
    accepted: bool
    lines: list[ScoreLine] = field(default_factory=list)
    agrees_with: list[str] = field(default_factory=list)
    rows: int = 0
    # False when this domain has never handed over usable rows, in which case
    # its tier is worth nothing yet.
    verified: bool = True
    # False while no authoritative publisher has been verified at all.
    threshold_enforced: bool = True

    @property
    def verdict(self) -> str:
        if not self.threshold_enforced:
            return "Đã dùng (chưa áp ngưỡng lọc)"
        return "Đủ tin cậy để dùng" if self.accepted else "Chưa đủ tin cậy, đã loại"


def _agree(left: dict, right: dict, tolerance: float) -> tuple[bool, int, int]:
    """Do two series report the same quantity? (agree, matched, overlapped)"""
    shared = set(left) & set(right)
    if len(shared) < MIN_OVERLAP:
        return False, 0, len(shared)

    matched = 0
    for key in shared:
        a, b = float(left[key]), float(right[key])
        scale = max(abs(a), abs(b))
        if scale == 0:
            matched += a == b
        elif abs(a - b) / scale <= tolerance:
            matched += 1

    return matched / len(shared) >= MIN_AGREEMENT_RATIO, matched, len(shared)


def score(evidences: list[SourceEvidence], threshold: int = DEFAULT_THRESHOLD,
          tolerance: float = VALUE_TOLERANCE,
          health: HealthRecord | None = None) -> list[CredibilityScore]:
    """Score every source against every other. Order of input does not matter.

    `health` decides which domains have earned their tier. Passing None means
    "nothing has been verified", which withholds points rather than inventing
    them -- the safe reading when a caller has not said otherwise.
    """
    record = health if health is not None else HealthRecord()
    enforced = record.threshold_active()
    serieses = {e.name: e.series() for e in evidences}
    results: list[CredibilityScore] = []

    for evidence in evidences:
        verdict: DomainVerdict = classify(evidence.url)
        verified = record.is_verified(evidence.url)
        if verified:
            lines = [ScoreLine(verdict.reason, verdict.points)]
            total = verdict.points
        else:
            lines = [ScoreLine(
                f"Chưa lấy được số liệu thật từ nguồn này lần nào ({verdict.domain})", 0)]
            total = 0

        agreeing: list[str] = []
        for other in evidences:
            if other.name == evidence.name:
                continue
            ok, matched, overlap = _agree(serieses[evidence.name], serieses[other.name],
                                          tolerance)
            if ok:
                agreeing.append(other.label or other.name)

        if agreeing:
            awarded = min(CONSENSUS_POINTS_EACH * len(agreeing), CONSENSUS_POINTS_MAX)
            names = ", ".join(agreeing)
            lines.append(ScoreLine(f"Số liệu trùng khớp với {names}", awarded))
            total += awarded

        if evidence.structured:
            lines.append(ScoreLine("Dữ liệu công bố sẵn theo ngày, không phải suy ra từ văn bản",
                                   STRUCTURE_POINTS))
            total += STRUCTURE_POINTS

        results.append(CredibilityScore(
            source=evidence.label or evidence.name,
            url=evidence.url,
            domain=verdict.domain,
            tier=verdict.tier,
            total=total,
            threshold=threshold,
            # With the threshold suspended, returning usable rows is the only
            # bar there is -- and saying that out loud beats applying a number
            # that currently rejects everything.
            accepted=(total >= threshold) if enforced else bool(evidence.rows),
            lines=lines,
            agrees_with=agreeing,
            rows=len(evidence.rows),
            verified=verified,
            threshold_enforced=enforced,
        ))

    return sorted(results, key=lambda s: s.total, reverse=True)


def accepted_names(scores: list[CredibilityScore]) -> set[str]:
    return {s.source for s in scores if s.accepted}
