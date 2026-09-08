"""Settings, from the environment with usable defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(name: str = ".env") -> None:
    path = ROOT / name
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:  # real env vars win, so CI can override
            os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    # --- Local model (Ollama) ---
    #
    # Empty means "ask Ollama": llm/discover.py lists what is installed, keeps
    # the ones reporting tool support, and takes the smallest. Set a name here
    # to pin one -- a pinned name is used even if its capability list looks
    # wrong, because the operator may know something the list does not.
    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "")
    # A 7B model on CPU can take a minute on a long element list; the default
    # urllib timeout would cut it off mid-generation and look like a failure.
    ollama_timeout_s: int = int(os.environ.get("OLLAMA_TIMEOUT_S", "300"))

    headless: bool = os.environ.get("HEADLESS", "true").strip().lower() in ("1", "true", "yes")
    # Wall-clock ceiling for a single Playwright operation.
    action_timeout_ms: int = int(os.environ.get("ACTION_TIMEOUT_MS", "8000"))

    # Hard ceiling on the perceive->reason->act loop. Without it a model that
    # keeps choosing the same wrong action burns the whole rate-limit budget.
    max_steps: int = int(os.environ.get("MAX_STEPS", "20"))
    # How many identical (action, target) pairs in a row before the run is
    # abandoned. Two is a retry; three is a loop.
    max_repeats: int = int(os.environ.get("MAX_REPEATS", "3"))

    # Elements sent to the model per step. The list is the prompt's bulk, and
    # a long page can otherwise push a step past a useful context size.
    max_elements: int = int(os.environ.get("MAX_ELEMENTS", "60"))

    @property
    def configured(self) -> bool:
        """Nothing to configure: the model is local and discovered."""
        return True


SETTINGS = Settings()
