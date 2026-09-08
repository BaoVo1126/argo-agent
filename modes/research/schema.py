from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass, field

_NUMBER = re.compile(r"-?\d[\d.,\s]*")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")


def parse_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value))
    if not match:
        return None
    text = match.group(0).strip().replace(" ", "")
    if "," in text and "." in text:
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
    if isinstance(value, (int, float)):  
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
    kind: str         
    required: bool = True
    unit: str = ""


@dataclass
class Schema:
    name: str
    fields: list[Field]
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
            seen[seen_key] = row  
        coerced = [seen[k] for k in sorted(seen, key=lambda t: tuple(str(v) for v in t))]

    report.valid_records = len(coerced)
    return coerced, report
