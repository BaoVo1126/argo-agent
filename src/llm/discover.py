"""
Which local model to use, asked of Ollama rather than assumed.

Hard-coding a model name is a bug waiting for a machine that never pulled it.
Ollama already knows what is installed and, since it started reporting
`capabilities`, which of those can take a tool call -- so the choice is a
query, not a constant.

**Tool support is the hard filter.** A model without it can still produce
prose that looks like a function call, and parsing prose into an action is how
an agent starts clicking at random. `gemma2:2b` on this machine reports only
`completion`; it is excluded, and no amount of prompting changes that.

**Size is the tie-break, smallest first.** This is a CPU-only machine where a
7B model spends most of a minute per step, so a 3B that does the job is worth
more than a 7B that does it slightly better. Whether the smallest one *can* do
the job is a separate question that a capability flag cannot answer -- see
`probe()`, which asks it to do the actual work.

Everything here goes over Ollama's HTTP API. Shelling out to `ollama list`
would parse a table meant for humans and break the first time its columns move.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from src.config import SETTINGS

# Capability names Ollama reports. "tools" is the one that matters.
TOOLS = "tools"

_SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


class NoUsableModel(RuntimeError):
    """Ollama is reachable but has nothing that can take a tool call."""


@dataclass(frozen=True)
class ModelInfo:
    name: str
    parameters: float          # count, so 3.1B sorts below 7.6B
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
    """Parameter count, from whichever field this Ollama version fills in."""
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
    # Unknown size sorts last rather than first: an unmeasured model should
    # not win a contest decided on size.
    return float("inf")


def installed_models() -> list[ModelInfo]:
    """Every pulled model, with its capabilities, smallest first."""
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
            continue  # a model that cannot be described cannot be chosen
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
    """The model to use: the configured one, or the smallest that takes tools.

    An explicitly configured name wins even if it reports no tool support --
    the operator may know something the capability list does not, and silently
    overriding their setting is worse than letting it fail loudly.
    """
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
    """Can this model actually return the JSON the pipeline needs?

    The capability flag says the model *accepts* tools; it says nothing about
    whether a 3B can follow a schema in Vietnamese. This asks it to do the real
    job in miniature and reports what came back, so the choice is measured
    rather than inferred.
    """
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
