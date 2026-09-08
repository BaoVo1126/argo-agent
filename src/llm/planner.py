from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.llm.text import LLMUnavailable, complete_json

FREQUENCIES = ("daily", "monthly", "yearly")

SYSTEM = """Bạn là trợ lý lập kế hoạch nghiên cứu dữ liệu. Bạn KHÔNG được
đưa ra URL, đường dẫn hay tên trang web cụ thể dưới dạng địa chỉ. Bạn chỉ mô
tả loại dữ liệu cần tìm và gợi ý từ khoá tìm kiếm.

Trả về đúng một đối tượng JSON, không thêm chữ nào khác."""

_TEMPLATE = """Người dùng muốn nghiên cứu chủ đề sau, trong khoảng thời gian
từ {start} đến {end}:

    "{topic}"

Các bộ nguồn đã được lập trình sẵn trong hệ thống (chỉ được chọn trong danh
sách này, hoặc để null nếu không có cái nào phù hợp):
{catalogue}

Trả về JSON với đúng các khoá sau:
{{
  "metric_label": "tên đại lượng, tiếng Việt, ngắn gọn, ví dụ: Tỷ giá USD/VND",
  "value_field": "tên trường dữ liệu bằng tiếng Anh không dấu, kiểu snake_case",
  "unit": "đơn vị đo, ví dụ: VND/USD hoặc %",
  "frequency": "daily hoặc monthly hoặc yearly",
  "registry_key": "một khoá trong danh sách trên, hoặc null",
  "search_queries": ["2 đến 4 truy vấn tìm kiếm ngắn"],
  "domain_hints": ["tên miền gốc, ví dụ: sbv.gov.vn"],
  "notes": "một câu nói rõ đại lượng này là gì"
}}

Quy tắc bắt buộc:
- domain_hints chỉ là tên miền gốc, không kèm http, không kèm đường dẫn.
- Nếu không chắc trang nào công bố, để domain_hints là mảng rỗng. Không đoán.
- registry_key phải lấy nguyên văn từ danh sách, nếu không hợp thì để null."""


@dataclass
class ResearchPlan:
    topic: str
    metric_label: str
    value_field: str
    unit: str
    frequency: str
    registry_key: str | None
    search_queries: list[str] = field(default_factory=list)
    domain_hints: list[str] = field(default_factory=list)
    notes: str = ""
    from_model: bool = True

    @property
    def uses_registry(self) -> bool:
        return self.registry_key is not None


def _slug(text: str, fallback: str = "value") -> str:
    stripped = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", stripped).strip("_").lower()
    return slug or fallback


_BARE_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9.-]{2,80}\.[a-z]{2,12}$")


def _clean_domains(values) -> list[str]:
    out = []
    for value in values or []:
        text = str(value).strip().lower()
        text = re.sub(r"^https?://", "", text).split("/")[0].removeprefix("www.")
        if _BARE_DOMAIN.match(text) and text not in out:
            out.append(text)
    return out[:6]


def _clean_queries(values, topic: str) -> list[str]:
    out = []
    for value in values or []:
        text = " ".join(str(value).split())[:120]
        if text and text not in out:
            out.append(text)
    return out[:4] or [topic]


def _fallback(topic: str, catalogue: dict[str, str]) -> ResearchPlan:
    lowered = _slug(topic).replace("_", " ")
    best, best_hits = None, 0
    for key, description in catalogue.items():
        words = {w for w in _slug(description).split("_") if len(w) > 2}
        hits = sum(1 for w in words if w in lowered)
        if hits > best_hits:
            best, best_hits = key, hits

    return ResearchPlan(
        topic=topic,
        metric_label=topic.strip()[:80] or "Chỉ số",
        value_field=_slug(topic)[:40] or "value",
        unit="",
        frequency="daily",
        registry_key=best,
        search_queries=[topic],
        domain_hints=[],
        notes="",
        from_model=False,
    )


def plan(topic: str, start, end, catalogue: dict[str, str],
         model: str | None = None) -> ResearchPlan:
    listing = "\n".join(f"- {key}: {desc}" for key, desc in catalogue.items()) or "- (trống)"
    prompt = _TEMPLATE.format(topic=topic.strip(), start=start, end=end, catalogue=listing)

    try:
        raw = complete_json(SYSTEM, prompt, model=model)
    except (LLMUnavailable, Exception):
        return _fallback(topic, catalogue)

    key = raw.get("registry_key")
    if isinstance(key, str):
        key = key.strip()
    registry_key = key if key in catalogue else None

    frequency = str(raw.get("frequency") or "daily").strip().lower()
    if frequency not in FREQUENCIES:
        frequency = "daily"

    return ResearchPlan(
        topic=topic.strip(),
        metric_label=str(raw.get("metric_label") or topic).strip()[:80],
        value_field=_slug(raw.get("value_field"), fallback=_slug(topic))[:40],
        unit=str(raw.get("unit") or "").strip()[:24],
        frequency=frequency,
        registry_key=registry_key,
        search_queries=_clean_queries(raw.get("search_queries"), topic),
        domain_hints=_clean_domains(raw.get("domain_hints")),
        notes=str(raw.get("notes") or "").strip()[:300],
    )
