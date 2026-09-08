from __future__ import annotations

import json
import urllib.error
import urllib.request

from src.config import SETTINGS
from src.llm.actions_spec import SYSTEM_PROMPT, action_names, to_openai_tools
from src.llm.decision import Decision


class OllamaPlanner:
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        from src.llm.discover import choose

        self.info = choose(model)
        self.model = self.info.name
        self.host = (host or SETTINGS.ollama_host).rstrip("/")
        self.tools = to_openai_tools()
        self.valid = action_names()
        self.calls = 0
        self.tokens = 0

    def decide(self, goal: str, observation: str, history: list[str]) -> Decision:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _prompt(goal, observation, history)},
            ],
            "tools": self.tools,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192},
        }

        try:
            data = self._post("/api/chat", payload)
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach Ollama at {self.host}. Is `ollama serve` running? "
                f"({exc})"
            ) from exc

        self.calls += 1
        self.tokens += (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0)

        message = data.get("message") or {}
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name", "")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            if name in self.valid:
                return Decision(action=name, args=dict(arguments or {}))
            return Decision(
                "finish",
                {"success": False, "result": f"model invented an action: {name!r}"},
            )

        text = (message.get("content") or "").strip()
        return Decision(
            "finish",
            {"success": False, "result": f"model replied with text, not an action: {text[:160]}"},
            raw_text=text,
        )

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=SETTINGS.ollama_timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))


def _prompt(goal: str, observation: str, history: list[str]) -> str:
    parts = [f"GOAL: {goal}", ""]
    if history:
        parts += ["WHAT YOU HAVE DONE SO FAR:"] + history[-8:] + [""]
    parts += ["CURRENT PAGE:", observation, "", "Choose ONE action."]
    return "\n".join(parts)
