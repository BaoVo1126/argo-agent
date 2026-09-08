"""
The planner: a local model, chosen by what this machine actually has.

Everything runs on Ollama. The hosted option was removed rather than kept as
an alternative, because a second backend that nobody exercises is a second
contract that quietly rots -- and the hosted free tier was 20 requests a day,
which funded about four tasks. Local costs latency instead of quota, and on a
CPU-only machine latency is a number you can plan around.

The model is not hard-coded. `llm/discover.py` asks Ollama what is installed,
keeps the ones that report tool support, and takes the smallest -- so this
works on a machine that pulled something different, and fails loudly on one
that pulled nothing suitable.

One thing this file has to handle. Ollama has no way to *force* a tool call,
so a model can answer with prose instead. Rather than parse prose into an
action -- which is how a loop starts clicking at random -- an unparseable reply
becomes `finish(success=false)` with the reason, and the run ends honestly.
"""

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

        # Resolved once, here, so the run reports the model it actually used
        # rather than the one someone assumed.
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
            # temperature 0 so the same page yields the same action; num_ctx
            # raised because the element list plus history routinely exceeds
            # Ollama's 2048-token default, and a silently truncated prompt
            # loses the very elements the model is supposed to choose from.
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
            # A hallucinated action name is reported rather than executed;
            # registry.execute would reject it anyway, but naming it here
            # makes the trace say what the model actually asked for.
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
