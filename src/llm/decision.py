from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Decision:
    action: str
    args: dict
    raw_text: str = ""
