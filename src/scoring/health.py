"""
Which domains have ever actually returned data, on this machine.

The tier table used to pay 50 points to `sbv.gov.vn` for being a central bank.
Nothing in the catalogue ever fetched a byte from it -- its rate page never
finishes loading and its front page answers with a firewall rejection -- so
those 50 points were a claim about a source that had never been tested. The
whole threshold rested on that claim, because 60 was set exactly where one
official source passes alone.

So provenance is now a *conditional* score. A domain earns its tier the first
time it hands over usable rows, and until then it is `unverified` and worth
zero, however impressive its suffix. The record is on disk, so a source proven
last week counts today, and a source that has never worked never counts.

Verification is deliberately one-way. A domain that worked once keeps it
through a later outage: a bank being down for an afternoon is not evidence
that it was never a bank. What that half of the record answers is "has this
ever been real?", not "is it up right now".

The second half is the opposite question, and it exists because of the domain
pool in `modes/research/pool.py`. A pool is a list of addresses to try, and
some of them will rot -- a ministry reorganises its navigation, a search page
starts refusing robots. Trying a dead address on every run costs a page load
and tells the customer nothing, so a domain that fails repeatedly is
*suspended*: passed over for a while, said so in the trace, and never removed.
Removal would be a permanent verdict on evidence that is usually temporary,
and a suspension that expires on its own gets the site back the moment it
starts answering again.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

from src.scoring.domains import Tier, domain_of

# Kept out of outputs/, which holds things a person looks at, and out of the
# package, which holds code.
DEFAULT_PATH = Path("data") / "source_health.json"

# Tiers that count as an authoritative publisher. The threshold was calibrated
# on one of these passing alone, so until one is verified the calibration is
# untested -- see `threshold_active`.
HIGH_TIERS = (Tier.GOVERNMENT, Tier.ACADEMIC)

# How many consecutive failures before a domain is rested, and for how long.
# Three because one failure is usually the network and two is usually the
# site having a bad afternoon; seven days because that is long enough to stop
# wasting page loads on a dead address and short enough that a fixed site is
# back in the pool within a week without anyone editing a file.
SUSPEND_AFTER_FAILURES = 3
SUSPENSION_DAYS = 7

_LOCK = threading.Lock()


@dataclass
class DomainHealth:
    domain: str
    tier: str
    first_success: str = ""
    last_success: str = ""
    successes: int = 0
    rows_last: int = 0
    # Failures since the last success, not since the beginning: a domain that
    # works most of the time should never accumulate its way to a suspension.
    failures: int = 0
    last_failure: str = ""
    last_error: str = ""
    # ISO date-time this domain may be tried again. Empty means "now".
    suspended_until: str = ""

    @property
    def verified(self) -> bool:
        return self.successes > 0


@dataclass
class HealthRecord:
    path: Path = DEFAULT_PATH
    domains: dict[str, DomainHealth] = field(default_factory=dict)

    # --- persistence ---------------------------------------------------

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PATH) -> "HealthRecord":
        path = Path(path)
        record = cls(path=path)
        if not path.is_file():
            return record
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt record means "nothing is verified", which is the safe
            # reading: it withholds points rather than inventing them.
            return record
        fields = set(DomainHealth.__annotations__)
        for domain, entry in (raw.get("domains") or {}).items():
            if not isinstance(entry, dict):
                continue
            # The saved entry already carries its own `domain`, so the key is
            # only used to index. Passing both is how this raised TypeError on
            # the first reload of a saved record.
            known = {k: v for k, v in entry.items() if k in fields}
            known["domain"] = domain
            record.domains[domain] = DomainHealth(**known)
        return record

    def save(self) -> None:
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "domains": {d: vars(h) for d, h in sorted(self.domains.items())},
            }, ensure_ascii=False, indent=2), encoding="utf-8")

    # --- queries -------------------------------------------------------

    def is_verified(self, url_or_domain: str) -> bool:
        entry = self.domains.get(domain_of(url_or_domain) or url_or_domain)
        return bool(entry and entry.verified)

    def _entry(self, url_or_domain: str):
        return self.domains.get(domain_of(url_or_domain) or url_or_domain)

    def is_suspended(self, url_or_domain: str) -> bool:
        """Is this domain resting? Expires on its own, without a cleanup pass.

        Read as a comparison against the clock rather than a stored flag, so a
        suspension that has run out is simply over -- nothing has to notice it
        expired and write the record back.
        """
        entry = self._entry(url_or_domain)
        if entry is None or not entry.suspended_until:
            return False
        try:
            return dt.datetime.fromisoformat(entry.suspended_until) > dt.datetime.now()
        except ValueError:
            # An unparseable stamp is treated as no suspension: withholding a
            # source because its own bookkeeping is corrupt would be the wrong
            # way round.
            return False

    def suspension_note(self, url_or_domain: str) -> str:
        """One sentence for the customer, or empty when nothing is resting."""
        entry = self._entry(url_or_domain)
        if entry is None or not self.is_suspended(url_or_domain):
            return ""
        until = dt.datetime.fromisoformat(entry.suspended_until)
        return (f"Tạm ngưng đến {until:%d/%m/%Y} sau {entry.failures} lần liên tiếp "
                f"không lấy được số liệu")

    def suspended_domains(self) -> list[str]:
        return sorted(d for d in self.domains if self.is_suspended(d))

    def verified_tiers(self) -> set[str]:
        return {h.tier for h in self.domains.values() if h.verified}

    def threshold_active(self) -> bool:
        """Is the 60-point threshold safe to enforce yet?

        Only once some authoritative publisher has actually been scraped. With
        none verified, no source can reach 60 on provenance alone, so applying
        the threshold would reject everything for a reason that is about this
        project's coverage rather than about the data.
        """
        return bool(self.verified_tiers() & {t.value for t in HIGH_TIERS})

    def verified_high_tier(self) -> list[str]:
        return sorted(h.domain for h in self.domains.values()
                      if h.verified and h.tier in {t.value for t in HIGH_TIERS})

    # --- updates -------------------------------------------------------

    def record_success(self, url: str, tier: Tier, rows: int) -> None:
        """A source handed over usable rows. From now on its tier counts."""
        domain = domain_of(url)
        if not domain or rows <= 0:
            return
        now = dt.datetime.now().isoformat(timespec="seconds")
        entry = self.domains.get(domain)
        if entry is None:
            entry = DomainHealth(domain=domain, tier=tier.value, first_success=now)
            self.domains[domain] = entry
        entry.tier = tier.value
        entry.last_success = now
        entry.successes += 1
        entry.rows_last = rows
        # Working once clears the slate outright. A domain that just handed
        # over rows is not three failures away from being rested, whatever it
        # did last week.
        entry.failures = 0
        entry.last_error = ""
        entry.suspended_until = ""

    def record_failure(self, url: str, tier: Tier, error: str = "") -> bool:
        """A source was tried and gave nothing back. True if that rested it.

        Failure is counted per domain rather than per address: a pool entry
        lists several paths on one site, and the site failing is one fact, not
        three. Callers report every address they tried and then call this once.
        """
        domain = domain_of(url)
        if not domain:
            return False
        now = dt.datetime.now()
        entry = self.domains.get(domain)
        if entry is None:
            entry = DomainHealth(domain=domain, tier=tier.value)
            self.domains[domain] = entry
        entry.tier = tier.value
        entry.last_failure = now.isoformat(timespec="seconds")
        entry.last_error = str(error)[:160]
        entry.failures += 1
        if entry.failures >= SUSPEND_AFTER_FAILURES and not entry.suspended_until:
            entry.suspended_until = (
                now + dt.timedelta(days=SUSPENSION_DAYS)).isoformat(timespec="seconds")
            return True
        return False
