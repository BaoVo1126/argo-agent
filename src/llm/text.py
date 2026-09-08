"""
One JSON completion from the local model.

The agent loop talks to a model through `decide()` and gets an action back.
Planning and insight-writing need something different -- a small JSON object --
and bending the action interface to carry them would put two unrelated
contracts in one place.

The schema is described in the prompt and enforced in Python. A model that
returns a well-typed object full of invented content passes any schema check,
so the callers in `planner.py` and `insight.py` do their own checking on top;
that is where the real guard lives, and it has to exist regardless.
"""

from __future__ import annotations

import json
import re
import urllib.request

from src.config import SETTINGS

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMUnavailable(RuntimeError):
    """No model could be reached, or it returned nothing usable."""


def _extract_json(text: str) -> dict:
    """Pull an object out of a reply, tolerating code fences and preamble."""
    text = (text or "").strip()
    if not text:
        raise LLMUnavailable("model returned an empty reply")

    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMUnavailable(f"model did not return JSON: {text[:160]}")
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"model returned malformed JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMUnavailable("model returned JSON that is not an object")
    return parsed


def complete_json(system: str, prompt: str, model: str | None = None,
                  temperature: float = 0.0) -> dict:
    """Ask for one JSON object. Raises LLMUnavailable rather than guessing."""
    from src.llm.discover import NoUsableModel, choose

    try:
        chosen = choose(model).name
    except NoUsableModel as exc:
        raise LLMUnavailable(str(exc)) from exc

    payload = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        # Ollama's JSON mode. It constrains the shape, not the content -- the
        # content is what the callers check.
        "format": "json",
        "options": {"temperature": temperature, "num_ctx": 8192},
    }
    request = urllib.request.Request(
        f"{SETTINGS.ollama_host.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=SETTINGS.ollama_timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise LLMUnavailable(
            f"không gọi được Ollama tại {SETTINGS.ollama_host}: {exc}"
        ) from exc

    return _extract_json((data.get("message") or {}).get("content") or "")
