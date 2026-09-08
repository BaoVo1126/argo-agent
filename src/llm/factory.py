"""Build the planner. There is one backend now, and it runs on this machine.

Kept as a factory rather than inlined because `agent/loop.py` is written
against an interface, not a class -- a second backend, if one is ever needed,
is added here and nowhere else.
"""

from __future__ import annotations


def get_planner(model: str | None = None):
    from src.llm.ollama import OllamaPlanner

    return OllamaPlanner(model=model)
