from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class Source:
    name: str                 
    label: str                  
    site: str                    
    url: str                   
    plan: list[tuple[str, dict]]    
    extract: Callable             
    value_field: str
    key_field: str = "date"
    unit: str = ""
    structured: bool = True
    timeout_ms: int | None = None
    note: str = ""
    meta: dict = field(default_factory=dict)

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
