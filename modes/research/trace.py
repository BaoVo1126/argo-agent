"""
What the agent is doing, while it is doing it.

The pipeline already emitted progress lines, and the web app already turned
the unindented ones into a phase caption. That was enough to prove the run was
alive and nothing more: by the time anything reached the customer, the
searching was over and what they saw was a finished table of scores. The part
that is actually interesting -- this domain was tried, it answered, it scored
this much, it was kept or dropped and why -- happened invisibly.

So progress is now two things at once. `log(line)` stays exactly as it was,
because the operator's stdout and the phase caption both depend on it. On top
of it sits a stream of `TraceEvent`s, which are the same run described in
fields rather than prose: a kind, the domain it concerns, a score when there
is one. A caption cannot be styled, counted, or filtered; a typed event can.

**Why a sink rather than a return value.** The whole point is that these
arrive during the run, not after it. `pipeline.run` takes minutes and returns
once; a caller that only saw the events at the end would be back to a static
report with extra steps. The web app's sink pushes each event onto the queues
its open SSE connections are draining, so an event reaches the browser in the
same second the browser could have watched it happen.

**Why the text is written for a customer.** There is no second, friendlier
rendering downstream. If a kind needs explaining it is explained here, in
Vietnamese, in the sentence a person reads.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

# The kinds an event can be. Kept small and named for what happened rather
# than how it should look, so the UI decides the styling and this file does
# not have to know there is a UI.
KINDS = (
    "phase",     # a stage of the run began
    "detail",    # a line under the current stage
    "probe",     # a vetted domain is being tried right now
    "hit",       # that domain published a usable table
    "miss",      # it did not, after every address was tried
    "keep",      # a source cleared the bar to go forward, with its score
    "drop",      # a source cannot reach the threshold and was let go
    "skip",      # a domain was passed over -- suspended, or the run had enough
    "suspend",   # a domain failed once too often and is resting
    "summary",   # how many sources were confirmed out of how many tried
)


@dataclass
class TraceEvent:
    kind: str
    text: str
    domain: str = ""
    score: int | None = None
    threshold: int | None = None
    # Seconds since the trace was opened. The browser shows elapsed time
    # without needing a clock of its own or a timezone to agree on.
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
    """A run's events, delivered as they happen and kept in order.

    Constructed without a sink it is a recorder: the events pile up in
    `events` and nobody is told. That is the shape the CLI and the tests want,
    and it means `pipeline.run` never has to check whether anyone is watching.
    """

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
            # A broken listener must not end a scrape. The events are a
            # description of the run, not part of it.
            try:
                self.sink(entry)
            except Exception:
                pass
        return entry

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [e.as_dict() for e in self.events]
