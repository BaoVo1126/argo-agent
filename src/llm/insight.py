from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from src.llm.text import LLMUnavailable, complete_json
from src.timeseries.analysis import SeriesAnalysis

SYSTEM = """Bạn viết nhận định ngắn về số liệu cho người đọc phổ thông.

Quy tắc tuyệt đối:
- CHỈ dùng những con số đã được cung cấp. Không tự tính thêm, không làm tròn
  thành con số khác, không thêm bất kỳ số nào không có trong danh sách.
- Không dùng thuật ngữ kỹ thuật (z-score, IQR, độ lệch chuẩn, outlier...).
- Không nhắc đến mô hình, dữ liệu thô, hay cách hệ thống hoạt động.
- Viết 2 đến 3 câu, giọng chuyên nghiệp, trung tính, dễ hiểu.

Trả về đúng một đối tượng JSON: {"insight": "..."}"""


@dataclass
class Insight:
    text: str
    origin: str
    rejected_numbers: list[str]

_NUMBER = re.compile(r"-?\d[\d.,]*")

_ALWAYS_ALLOWED = set(range(0, 32)) | set(range(1900, 2200))


def _parse(token: str) -> float | None:
    text = token.strip().rstrip("%").strip()
    if not text or not any(c.isdigit() for c in text):
        return None
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(decimal, ".")
    elif "," in text:
        text = text.replace(",", ".") if re.search(r",\d{1,2}$", text) else text.replace(",", "")
    elif "." in text and not re.search(r"\.\d{1,2}$", text):
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def _close(value: float, allowed: set[float]) -> bool:
    for known in allowed:
        if known == value:
            return True
        scale = max(abs(known), abs(value), 1e-9)
        if abs(known - value) / scale <= 0.006:
            return True
        for digits in (0, 1, 2):
            if round(known, digits) == round(value, digits):
                return True
    return False


def check_numbers(text: str, allowed: set[float]) -> list[str]:
    bad = []
    for match in _NUMBER.finditer(text):
        value = _parse(match.group(0))
        if value is None:
            continue
        if value in _ALWAYS_ALLOWED and float(value).is_integer():
            continue
        if not _close(value, allowed):
            bad.append(match.group(0))
    return bad

_DIRECTED = re.compile(r"\b(tăng|giảm)\b([^.;:]{0,40}?)(-?\d[\d.,]*)", re.IGNORECASE)


def directed_values(analysis: SeriesAnalysis) -> list[tuple[float, str]]:
    pairs: list[tuple[float, str]] = [(abs(analysis.change), analysis.direction)]
    for period in analysis.periods:
        pairs.append((abs(period.change), "tăng" if period.change >= 0 else "giảm"))
    for anomaly in analysis.anomalies:
        pairs.append((abs(anomaly.change), anomaly.direction))
    return pairs


def check_directions(text: str, analysis: SeriesAnalysis) -> list[str]:
    known = directed_values(analysis)
    wrong: list[str] = []

    for match in _DIRECTED.finditer(text):
        stated = match.group(1).lower()
        value = _parse(match.group(3))
        if value is None:
            continue

        same = [d for v, d in known if _close(value, {v}) and d == stated]
        opposite = [d for v, d in known if _close(value, {v}) and d != stated
                    and d in ("tăng", "giảm")]
        if opposite and not same:
            wrong.append(f"{stated} {match.group(3)}")

    return wrong

def _money(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".") if abs(value) >= 1000 else f"{value:,.2f}"


def allowed_values(analysis: SeriesAnalysis) -> set[float]:
    values = {
        analysis.first_value, analysis.last_value, analysis.change,
        analysis.minimum, analysis.maximum, analysis.mean,
        analysis.volatility, float(analysis.points), float(analysis.span_days),
        float(len(analysis.anomalies)),
    }
    for period in analysis.periods:
        values |= {period.change, period.current_mean, period.previous_mean}
    for anomaly in analysis.anomalies:
        values |= {anomaly.value, anomaly.change}
    return {abs(v) for v in values} | values


def facts_block(analysis: SeriesAnalysis, metric: str) -> str:
    unit = f" {analysis.unit}" if analysis.unit else ""
    lines = [
        f"Đại lượng: {metric}",
        f"Kỳ quan sát: {analysis.first_date:%d/%m/%Y} đến {analysis.last_date:%d/%m/%Y}"
        f" ({analysis.points} mốc dữ liệu)",
        f"Đầu kỳ: {_money(analysis.first_value)}{unit}",
        f"Cuối kỳ: {_money(analysis.last_value)}{unit}",
        f"Thay đổi cả kỳ: {analysis.change:+.2f} {analysis.unit_label}",
        f"Thấp nhất: {_money(analysis.minimum)}{unit}; cao nhất: {_money(analysis.maximum)}{unit}",
    ]
    for period in analysis.periods:
        lines.append(f"{period.label}: {period.change:+.2f} {period.unit_label}")
    if analysis.anomalies:
        lines.append(f"Số mốc biến động khác thường: {len(analysis.anomalies)} "
                     f"(mỗi mốc là một {analysis.cadence})")
        for anomaly in analysis.anomalies[:3]:
            lines.append(f"  - {anomaly.date:%d/%m/%Y}: {anomaly.direction} "
                         f"{abs(anomaly.change):.2f} {anomaly.unit_label} "
                         f"so với {analysis.cadence} liền trước")
    else:
        lines.append(f"Không có {analysis.cadence} nào biến động khác thường.")
    return "\n".join(lines)


def template(analysis: SeriesAnalysis, metric: str) -> str:
    """The always-correct version, assembled from the same facts."""
    unit = f" {analysis.unit}" if analysis.unit else ""
    sentences = [
        f"Từ {analysis.first_date:%d/%m/%Y} đến {analysis.last_date:%d/%m/%Y}, "
        f"{metric} {analysis.direction} {abs(analysis.change):.2f} "
        f"{analysis.unit_label}, từ {_money(analysis.first_value)}{unit} "
        f"còn {_money(analysis.last_value)}{unit}."
        if analysis.change < 0 else
        f"Từ {analysis.first_date:%d/%m/%Y} đến {analysis.last_date:%d/%m/%Y}, "
        f"{metric} {analysis.direction} {abs(analysis.change):.2f} "
        f"{analysis.unit_label}, từ {_money(analysis.first_value)}{unit} "
        f"lên {_money(analysis.last_value)}{unit}."
    ]
    if analysis.periods:
        period = analysis.periods[0]
        way = "cao hơn" if period.change >= 0 else "thấp hơn"
        sentences.append(f"{period.label} {way} {abs(period.change):.2f} "
                         f"{period.unit_label}.")
    if analysis.anomalies:
        first = analysis.anomalies[0]
        sentences.append(
            f"Có {len(analysis.anomalies)} mốc biến động khác thường so với mặt bằng "
            f"của kỳ, mạnh nhất là {first.date:%d/%m/%Y} khi giá trị {first.direction} "
            f"{abs(first.change):.2f} {first.unit_label} chỉ trong một {analysis.cadence}."
        )
    else:
        sentences.append("Không mốc nào biến động vượt hẳn khỏi mặt bằng chung của kỳ.")
    return " ".join(sentences)


def write(analysis: SeriesAnalysis, metric: str, model: str | None = None) -> Insight:
    fallback = template(analysis, metric)
    allowed = allowed_values(analysis)

    prompt = (
        "Dưới đây là các số liệu đã được tính sẵn. Hãy viết nhận định 2-3 câu.\n\n"
        + facts_block(analysis, metric)
    )

    try:
        raw = complete_json(SYSTEM, prompt, model=model, temperature=0.2)
    except Exception:
        return Insight(fallback, "template", [])

    text = " ".join(str(raw.get("insight") or "").split())
    if not text or len(text) < 30:
        return Insight(fallback, "template", [])

    invented = check_numbers(text, allowed)
    backwards = check_directions(text, analysis)
    if invented or backwards:
        return Insight(fallback, "template", invented + backwards)

    return Insight(text, "model", [])
