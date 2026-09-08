from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from src.config import SETTINGS

TOOLS = "tools"

_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


class NoUsableModel(RuntimeError):

@dataclass(frozen=True)
class ModelInfo:
    name: str
    parameters: float        
    capabilities: tuple[str, ...]
    family: str = ""

    @property
    def supports_tools(self) -> bool:
        return TOOLS in self.capabilities

    @property
    def size_label(self) -> str:
        if self.parameters >= 1e9:
            return f"{self.parameters / 1e9:.1f}B"
        if self.parameters >= 1e6:
            return f"{self.parameters / 1e6:.0f}M"
        return str(int(self.parameters))


def _post(path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    host = SETTINGS.ollama_host.rstrip("/")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{host}{path}", data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parameter_count(show: dict) -> float:
    info = show.get("model_info") or {}
    for key, value in info.items():
        if key.endswith("parameter_count") and isinstance(value, (int, float)):
            return float(value)

    label = str((show.get("details") or {}).get("parameter_size") or "").strip().lower()
    if label and label[-1] in _SUFFIX:
        try:
            return float(label[:-1]) * _SUFFIX[label[-1]]
        except ValueError:
            pass
    return float("inf")


def installed_models() -> list[ModelInfo]:
    try:
        tags = _post("/api/tags")
    except urllib.error.URLError as exc:
        raise NoUsableModel(
            f"Không kết nối được Ollama tại {SETTINGS.ollama_host}. "
            f"Chạy `ollama serve` rồi thử lại. ({exc})"
        ) from exc

    models: list[ModelInfo] = []
    for entry in tags.get("models") or []:
        name = entry.get("name") or entry.get("model")
        if not name:
            continue
        try:
            show = _post("/api/show", {"model": name})
        except Exception:
            continue 
        models.append(ModelInfo(
            name=name,
            parameters=_parameter_count(show),
            capabilities=tuple(show.get("capabilities") or ()),
            family=str((show.get("details") or {}).get("family") or ""),
        ))

    return sorted(models, key=lambda m: (m.parameters, m.name))


def tool_capable(models: list[ModelInfo] | None = None) -> list[ModelInfo]:
    return [m for m in (models if models is not None else installed_models())
            if m.supports_tools]


def choose(explicit: str | None = None) -> ModelInfo:
    models = installed_models()
    name = (explicit or SETTINGS.ollama_model or "").strip()

    if name:
        for model in models:
            if model.name == name or model.name.split(":")[0] == name:
                return model
        raise NoUsableModel(
            f"Model {name!r} chưa được tải về. Đã có: "
            + ", ".join(m.name for m in models)
        )

    usable = tool_capable(models)
    if not usable:
        raise NoUsableModel(
            "Không model nào đang cài đặt hỗ trợ tool calling. Đã kiểm tra: "
            + "; ".join(f"{m.name} ({', '.join(m.capabilities) or 'không rõ'})"
                        for m in models)
            + ". Hãy `ollama pull` một model có tools (ví dụ qwen2.5) rồi chạy lại."
        )
    return usable[0]


def probe(model: ModelInfo, timeout: int = 180) -> tuple[bool, str]:
    payload = {
        "model": model.name,
        "messages": [
            {"role": "system",
             "content": "Trả về đúng một đối tượng JSON, không thêm chữ nào khác."},
            {"role": "user",
             "content": 'Chủ đề: "tỷ giá USD/VND". Trả về JSON có đúng hai khoá: '
                        '"metric_label" (chuỗi tiếng Việt) và "frequency" '
                        '(một trong: daily, monthly, yearly).'},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 4096},
    }
    try:
        data = _post("/api/chat", payload, timeout=timeout)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    text = ((data.get("message") or {}).get("content") or "").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False, f"không trả về JSON hợp lệ: {text[:120]}"
    if not isinstance(parsed, dict) or "metric_label" not in parsed:
        return False, f"thiếu khoá bắt buộc: {text[:120]}"
    return True, str(parsed.get("metric_label"))[:80]
