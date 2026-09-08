from __future__ import annotations


def get_planner(model: str | None = None):
    from src.llm.ollama import OllamaPlanner

    return OllamaPlanner(model=model)
