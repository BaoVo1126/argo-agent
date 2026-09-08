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
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "")
    ollama_timeout_s: int = int(os.environ.get("OLLAMA_TIMEOUT_S", "300"))

    headless: bool = os.environ.get("HEADLESS", "true").strip().lower() in ("1", "true", "yes")
    action_timeout_ms: int = int(os.environ.get("ACTION_TIMEOUT_MS", "8000"))
    max_steps: int = int(os.environ.get("MAX_STEPS", "20"))

    max_repeats: int = int(os.environ.get("MAX_REPEATS", "3"))

    max_elements: int = int(os.environ.get("MAX_ELEMENTS", "60"))

    @property
    def configured(self) -> bool:
        """Nothing to configure: the model is local and discovered."""
        return True


SETTINGS = Settings()
