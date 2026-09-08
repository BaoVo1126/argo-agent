"""
The schema a scrape is validated against, and the report that comes out of it.

Two things a research run has to be honest about, and both live here:

**What fraction of each field actually came back.** A scraper that returns 90
rows with the price missing on 30 of them is not a 90-row success. The report
counts hits per field, so the run can print "gold_price_vnd 100%,
usd_vnd_rate 96%" instead of a single row count that hides the hole.

**What was thrown away and why.** Unparseable values, rows missing a required
field, and duplicate keys are counted separately, because they mean different
things: the first is a broken extractor, the second is a gap in the source,
the third is normal (a site that lists a price twice a day).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

_NUMBER = re.compile(r"-?\d[\d.,\s]*")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


def parse_number(value) -> float | None:
    """Parse a price the way sites write them, or return None.

    Handles '26,100.00' (comma thousands) and '158.500.000' (dot thousands)
    by looking at which separator comes last: the last one is the decimal
    point only if it is followed by one or two digits.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value))
    if not match:
        return None
    text = match.group(0).strip().replace(" ", "")
    if "," in text and "." in text:
        # Whichever separator is rightmost is the decimal one.
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        text = text.replace(",", ".") if re.search(r",\d{1,2}$", text) else text.replace(",", "")
    elif "." in text:
        if not re.search(r"\.\d{1,2}$", text):
            text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):  # epoch milliseconds, as charts emit
        seconds = value / 1000 if value > 1e11 else value
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc).date()
    text = str(value).strip()[:10]
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_PARSERS = {"date": parse_date, "number": parse_number, "text": lambda v: v or None}


@dataclass(frozen=True)
class Field:
    name: str
    kind: str          # "date" | "number" | "text"
    required: bool = True
    unit: str = ""


@dataclass
class Schema:
    name: str
    fields: list[Field]
    # Fields that identify a record. Two rows with the same key are the same
    # observation, and the later one wins.
    key: tuple[str, ...] = ()

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]


@dataclass
class ValidationReport:
    schema: str
    raw_records: int = 0
    valid_records: int = 0
    unparseable: dict[str, int] = field(default_factory=dict)
    field_hits: dict[str, int] = field(default_factory=dict)
    dropped_missing_required: int = 0
    duplicates_merged: int = 0

    def coverage(self, name: str) -> float:
        """Percent of raw records where this field came back with a value."""
        if not self.raw_records:
            return 0.0
        return 100.0 * self.field_hits.get(name, 0) / self.raw_records

    def lines(self) -> list[str]:
        out = [
            f"schema           : {self.schema}",
            f"raw records      : {self.raw_records}",
            f"valid records    : {self.valid_records}",
            f"dropped (missing): {self.dropped_missing_required}",
            f"duplicates merged: {self.duplicates_merged}",
            "field coverage   :",
        ]
        for name in self.field_hits:
            bad = self.unparseable.get(name, 0)
            note = f"   ({bad} unparseable)" if bad else ""
            out.append(f"  - {name:<18} {self.coverage(name):6.1f}%{note}")
        return out


def validate(rows: list[dict], schema: Schema) -> tuple[list[dict], ValidationReport]:
    """Coerce, count, drop and de-duplicate. Never invents a value."""
    report = ValidationReport(schema=schema.name, raw_records=len(rows))
    report.field_hits = {f.name: 0 for f in schema.fields}

    coerced: list[dict] = []
    for row in rows:
        clean: dict = {}
        missing_required = False
        for spec in schema.fields:
            raw = row.get(spec.name)
            value = _PARSERS[spec.kind](raw) if raw is not None else None
            if value is None and raw not in (None, ""):
                report.unparseable[spec.name] = report.unparseable.get(spec.name, 0) + 1
            if value is not None:
                report.field_hits[spec.name] += 1
            elif spec.required:
                missing_required = True
            clean[spec.name] = value
        if missing_required:
            report.dropped_missing_required += 1
            continue
        coerced.append(clean)

    key = schema.key or tuple(f.name for f in schema.fields if f.required)[:1]
    if key:
        seen: dict[tuple, dict] = {}
        for row in coerced:
            seen_key = tuple(row.get(k) for k in key)
            if seen_key in seen:
                report.duplicates_merged += 1
            seen[seen_key] = row  # last observation of a day wins
        coerced = [seen[k] for k in sorted(seen, key=lambda t: tuple(str(v) for v in t))]

    report.valid_records = len(coerced)
    return coerced, report
