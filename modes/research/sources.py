"""
Where the numbers come from: one adapter per site.

A source is declarative -- a label, the URL a browser opens, a short plan
written in the shared action space, and an extractor that runs inside the
page. The URL matters twice: it is what gets visited, and it is what
`src/scoring/domains.py` classifies. A source cannot claim a tier it did not
come from, because the tier is read off the address that was actually fetched.

**Why extraction runs as JavaScript in the page.** None of these numbers are
DOM text. The bank publishes through the JSON endpoint its own page calls, and
the open datasets are files served by a CDN or an API. Reading them from
inside the page is what the browser is for, and it is the difference between
real data and a plausible table.

The savings-rate adapters live in `bank_rates.py` instead: a rate board is a
bank-by-tenor matrix rather than one dated series, and forcing it through this
module's single-series shape would distort both.

**Why the plans are fixed rather than model-driven.** These pages are visited
the same way every run, so the navigation is written once. The steps still go
through `actions/registry.py`, so a plan can only do what the agent loop could
also have done. The model's job is upstream, in `llm/planner.py`, and it never
names a URL.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class Source:
    name: str                       # machine id, unique within a run
    label: str                      # what the customer sees
    site: str                       # domain, for display
    url: str                        # what is opened, and what the tier is read from
    plan: list[tuple[str, dict]]    # steps in the shared action space
    extract: Callable               # page -> [{key_field: ..., value_field: ...}]
    value_field: str
    key_field: str = "date"
    unit: str = ""
    # False when the numbers had to be read out of prose rather than a
    # published table or feed. Costs the structure points in scoring.
    structured: bool = True
    # How long this site is allowed to take, in milliseconds. The default
    # action timeout is sized for clicking a button on a page that is already
    # open; a JSON API on another continent legitimately needs longer, and
    # imf.org failed an otherwise good run by taking nine seconds.
    timeout_ms: int | None = None
    note: str = ""
    meta: dict = field(default_factory=dict)


# --- Vietcombank: the bank's own daily board -----------------------------
#
# One board per day at /api/exchangerates?date=YYYY-MM-DD, the endpoint the
# bank's own rates page calls. Fetching it from inside that page means
# same-origin requests carrying the site's cookies -- the traffic a visitor
# generates, rather than a scraper pretending to be one. Requests go in small
# batches: ninety serial round trips take minutes, and ninety parallel ones are
# a burst nobody asked this site to absorb.
_VCB_JS = r"""
async ([dates, code, batchSize]) => {
  const rows = [];
  for (let i = 0; i < dates.length; i += batchSize) {
    const slice = dates.slice(i, i + batchSize);
    const results = await Promise.all(slice.map(async (date) => {
      try {
        const res = await fetch('/api/exchangerates?date=' + date,
                                { headers: { 'Accept': 'application/json' } });
        if (!res.ok) return { date: date, error: 'HTTP ' + res.status };
        const body = await res.json();
        const row = (body.Data || []).find(r => r.currencyCode === code);
        if (!row) return { date: date, error: code + ' not listed' };
        return { date: date, value: row.transfer };
      } catch (e) {
        return { date: date, error: String(e) };
      }
    }));
    rows.push.apply(rows, results);
    await new Promise(r => setTimeout(r, 120));
  }
  return rows;
}
"""

# --- an open exchange-rate dataset on a CDN ------------------------------
#
# One JSON file per day, no key, permissive CORS. Included precisely because
# it is *not* authoritative: it is the corroborating voice the credibility
# scorer needs, and under the agreed tiers it never reaches the threshold on
# its own. If it stops agreeing with the bank, that disagreement is the signal.
_CDN_JS = r"""
async ([dates, base, quote, batchSize]) => {
  const rows = [];
  for (let i = 0; i < dates.length; i += batchSize) {
    const slice = dates.slice(i, i + batchSize);
    const results = await Promise.all(slice.map(async (date) => {
      const path = '/npm/@fawazahmed0/currency-api@' + date +
                   '/v1/currencies/' + base + '.json';
      try {
        const res = await fetch(path, { headers: { 'Accept': 'application/json' } });
        if (!res.ok) return { date: date, error: 'HTTP ' + res.status };
        const body = await res.json();
        const value = (body[base] || {})[quote];
        if (typeof value !== 'number') return { date: date, error: 'no ' + quote };
        return { date: date, value: value };
      } catch (e) {
        return { date: date, error: String(e) };
      }
    }));
    rows.push.apply(rows, results);
    await new Promise(r => setTimeout(r, 80));
  }
  return rows;
}
"""

def _fail(site: str, detail: str) -> None:
    raise RuntimeError(
        f"{site}: {detail}. Refusing to return empty data as if it were a result."
    )


def _daily(page, script, args, value_field: str, site: str) -> list[dict]:
    payload = page.evaluate(script, args)
    rows = [{"date": item["date"], value_field: item.get("value")}
            for item in payload if not item.get("error")]
    if not rows:
        errors = {str(i.get("error"))[:60] for i in payload if i.get("error")}
        _fail(site, "every request failed (" + "; ".join(sorted(errors))[:160] + ")")
    return rows


def vcb_rate_source(dates: list[dt.date], value_field: str,
                    code: str = "USD") -> Source:
    stamps = [d.isoformat() for d in dates]
    url = "https://www.vietcombank.com.vn/vi-VN/KHCN/Cong-cu-Tien-ich/Ty-gia"
    return Source(
        name="vcb",
        label="Vietcombank",
        site="vietcombank.com.vn",
        url=url,
        plan=[("navigate", {"url": url}), ("wait_for", {"selector": "body"})],
        extract=lambda page: _daily(page, _VCB_JS, [stamps, code, 6], value_field,
                                    "vietcombank"),
        value_field=value_field,
        unit=f"VND/{code}",
        note=f"Tỷ giá chuyển khoản {code}/VND do ngân hàng công bố theo ngày",
        meta={"days_requested": len(stamps)},
    )


def open_fx_source(dates: list[dt.date], value_field: str,
                   base: str = "usd", quote: str = "vnd") -> Source:
    stamps = [d.isoformat() for d in dates]
    # Navigating to a JSON file puts the browser on the CDN's origin, so the
    # per-day fetches below are same-origin and need no CORS negotiation.
    url = (f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest"
           f"/v1/currencies/{base}.json")
    return Source(
        name="open_fx",
        label="Bộ dữ liệu tỷ giá mở",
        site="cdn.jsdelivr.net",
        url=url,
        plan=[("navigate", {"url": url})],
        extract=lambda page: _daily(page, _CDN_JS, [stamps, base, quote, 8],
                                    value_field, "currency-api"),
        value_field=value_field,
        unit=f"VND/{base.upper()}",
        note="Bộ dữ liệu tỷ giá mở, dùng để đối chiếu với số liệu ngân hàng",
        meta={"days_requested": len(stamps)},
    )


# --- JSON APIs that publish a whole series in one document ----------------
#
# World Bank and the IMF each answer one request with an entire history, which
# is the opposite case from a bank's per-day board: one navigation, one parse,
# no batching. The browser still does the fetching -- the page is navigated to
# the endpoint and then fetches it same-origin -- so these go through the same
# path as every other source rather than becoming a quiet second way of getting
# data into the pipeline.
#
# Reading `document.body.innerText` instead would be shorter and wrong:
# Chromium renders JSON through a viewer that inserts its own markup, so the
# text on the page is not always the text the server sent.
_JSON_FETCH_JS = r"""
async (url) => {
  const res = await fetch(url, { headers: { 'Accept': 'application/json' } });
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return await res.json();
}
"""


def _fetch_json(page, url: str):
    return page.evaluate(_JSON_FETCH_JS, url)


def _year_to_date(year) -> str:
    """A yearly figure is placed on 1 January of the year it describes.

    It has to sit somewhere on a daily axis, and the start of the period is the
    choice that keeps the current year inside a range ending today -- 31
    December would drop the newest point from every window.
    """
    return f"{int(year):04d}-01-01"


def worldbank_source(indicator: str, value_field: str, label: str, unit: str,
                     country: str = "VNM") -> Source:
    url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
           f"?format=json&per_page=400")

    def extract(page) -> list[dict]:
        payload = _fetch_json(page, url)
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            _fail("worldbank", f"chỉ số {indicator} không có dữ liệu cho {country}")
        rows = [{"date": _year_to_date(entry["date"]), value_field: entry["value"]}
                for entry in payload[1]
                if entry.get("value") is not None and str(entry.get("date", "")).isdigit()]
        if not rows:
            _fail("worldbank", f"chỉ số {indicator} trả về toàn giá trị rỗng")
        return rows

    return Source(
        name="worldbank_" + indicator.replace(".", "_").lower(),
        label="World Bank",
        site="worldbank.org",
        url=url,
        plan=[("navigate", {"url": url})],
        extract=extract,
        value_field=value_field,
        unit=unit,
        timeout_ms=30000,
        note=f"{label} — số liệu World Bank công bố theo năm",
    )


def imf_source(indicator: str, value_field: str, label: str, unit: str,
               country: str = "VNM") -> Source:
    url = f"https://www.imf.org/external/datamapper/api/v1/{indicator}/{country}"

    def extract(page) -> list[dict]:
        payload = _fetch_json(page, url)
        series = (((payload or {}).get("values") or {})
                  .get(indicator, {}) or {}).get(country, {})
        if not series:
            _fail("imf", f"chỉ số {indicator} không có dữ liệu cho {country}")
        # The IMF publishes projections several years past the present. They
        # are real IMF output but they are not observations, and the pipeline
        # windows to the range the customer asked for -- which is what keeps
        # a forecast from being charted as history.
        rows = [{"date": _year_to_date(year), value_field: value}
                for year, value in series.items()
                if value is not None and str(year).isdigit()]
        if not rows:
            _fail("imf", f"chỉ số {indicator} trả về toàn giá trị rỗng")
        return rows

    return Source(
        name="imf_" + indicator.lower(),
        label="IMF",
        site="imf.org",
        url=url,
        plan=[("navigate", {"url": url})],
        extract=extract,
        value_field=value_field,
        unit=unit,
        timeout_ms=30000,
        note=f"{label} — số liệu IMF công bố theo năm",
    )
