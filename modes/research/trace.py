from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from typing import Callable


KINDS = (
    "phase",    
    "detail",    
    "probe",    
    "hit",    
    "miss",     
    "keep",    
    "drop",     
    "skip",     
    "suspend",   
    "summary",   
)


@dataclass
class TraceEvent:
    kind: str
    text: str
    domain: str = ""
    score: int | None = None
    threshold: int | None = None
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "text": self.text,
            "domain": self.domain,
            "score": self.score,
            "threshold": self.threshold,
            "seconds": round(self.seconds, 1),
        }


@dataclass
class Trace:
    sink: Callable[[TraceEvent], None] | None = None
    events: list[TraceEvent] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def event(self, kind: str, text: str, domain: str = "",
              score: int | None = None, threshold: int | None = None) -> TraceEvent:
        entry = TraceEvent(kind=kind, text=text, domain=domain, score=score,
                           threshold=threshold,
                           seconds=time.monotonic() - self.started)
        with self._lock:
            self.events.append(entry)
        if self.sink is not None:
            try:
                self.sink(entry)
            except Exception:
                pass
        return entry

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [e.as_dict() for e in self.events]
