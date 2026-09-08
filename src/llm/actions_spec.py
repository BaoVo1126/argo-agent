"""
The action space, described once, in plain data.

Ollama wants OpenAI-style tool dicts, and `actions/registry.py` implements the
same eight actions in Python. Writing them out twice would create two
descriptions of one contract, and the second copy drifts the first time an
argument changes -- silently, because the adapter keeps working on its own
terms.

So the specs live here as plain dicts and the adapter is generated from them.
A new action is added in exactly one place, and `test_action_parity` checks
that the specs, the generated tools and the implementations still agree.
"""

from __future__ import annotations

# type: "string" | "integer" | "boolean"
ACTION_SPECS: list[dict] = [
    {
        "name": "click",
        "description": "Click an element from the ELEMENTS list.",
        "parameters": {
            "id": ("integer", "The [n] id shown in the ELEMENTS list.", True),
        },
    },
    {
        "name": "type",
        "description": "Type text into a textbox. Replaces whatever is already there.",
        "parameters": {
            "id": ("integer", "The [n] id of the textbox.", True),
            "text": ("string", "Text to enter.", True),
        },
    },
    {
        "name": "select",
        "description": "Choose an option in a combobox. Use one of the values listed in options=.",
        "parameters": {
            "id": ("integer", "The [n] id of the combobox.", True),
            "value": ("string", "The option value.", True),
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the page when the element you need is not in the list yet.",
        "parameters": {
            "direction": ("string", "'up' or 'down'.", True),
        },
    },
    {
        "name": "navigate",
        "description": "Go to a URL directly.",
        "parameters": {"url": ("string", "Absolute URL.", True)},
    },
    {
        "name": "wait_for",
        "description": "Wait until a CSS selector appears, after an action that loads content.",
        "parameters": {"selector": ("string", "CSS selector.", True)},
    },
    {
        "name": "extract",
        "description": (
            "Read text from the page with a CSS selector. Returns every match, so use "
            "it to read a list before answering a question about it."
        ),
        "parameters": {"selector": ("string", "CSS selector.", True)},
    },
    {
        "name": "finish",
        "description": (
            "End the task. Call this as soon as the goal is met, and also when the "
            "goal cannot be met -- with success=false and a reason."
        ),
        "parameters": {
            "success": ("boolean", "Was the goal achieved?", True),
            "result": (
                "string",
                "The answer, if the task asked for one; otherwise a short note.",
                False,
            ),
        },
    },
]

SYSTEM_PROMPT = """You drive a web browser to accomplish a goal, one action at a time.

Each turn you are given the current page: its URL, some page text, and a
numbered list of the elements you can act on. Choose exactly ONE action.

Rules:
- Refer to elements only by the [n] ids in the list you were just given. The
  list is rebuilt after every action, so ids from earlier turns are stale.
- Read PAGE TEXT before deciding. An error message there means the previous
  action did not do what you expected, and repeating it will not help.
- If an action failed, the failure is in the history. Choose a different
  approach rather than retrying the same thing.
- Call finish(success=true, result=...) the moment the goal is met. If the
  goal is impossible -- a locked account, a missing product -- call
  finish(success=false) with the reason instead of continuing.
- When the goal asks for a value, put that value in `result`."""


def to_openai_tools() -> list[dict]:
    """OpenAI-style function schemas, which Ollama's /api/chat accepts."""
    tools = []
    for spec in ACTION_SPECS:
        properties = {}
        required = []
        for name, (json_type, description, is_required) in spec["parameters"].items():
            properties[name] = {"type": json_type, "description": description}
            if is_required:
                required.append(name)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return tools


def action_names() -> set[str]:
    return {spec["name"] for spec in ACTION_SPECS}
