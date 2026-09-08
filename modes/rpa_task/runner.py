from __future__ import annotations
from dataclasses import dataclass, field
from src.agent.loop import BrowserAgent, RunResult


@dataclass
class Check:
    kind: str      
    expected: str
    label: str = ""

    @classmethod
    def url_contains(cls, fragment: str) -> "Check":
        return cls("url_contains", fragment, f"URL contains {fragment!r}")

    @classmethod
    def text_contains(cls, fragment: str) -> "Check":
        return cls("text_contains", fragment, f"page text contains {fragment!r}")

    @classmethod
    def selector_visible(cls, selector: str) -> "Check":
        return cls("selector_visible", selector, f"{selector!r} is visible")

    def evaluate(self, page) -> tuple[bool, str]:
        try:
            if self.kind == "url_contains":
                return self.expected in page.url, page.url
            if self.kind == "text_contains":
                text = " ".join((page.inner_text("body") or "").split())
                return self.expected in text, text[:160]
            if self.kind == "selector_visible":
                node = page.query_selector(self.expected)
                return bool(node and node.is_visible()), "found" if node else "not found"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return False, f"unknown check kind {self.kind!r}"


@dataclass
class TaskSpec:
    name: str
    goal: str
    start_url: str
    checks: list[Check] = field(default_factory=list)
    max_steps: int | None = None


@dataclass
class CheckResult:
    label: str
    passed: bool
    observed: str


@dataclass
class TaskOutcome:
    task: str
    run: RunResult | None
    checks: list[CheckResult] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def verdict(self) -> str:
        head = f"{self.task}: {'PASS' if self.passed else 'FAIL'}"
        if self.error:
            return f"{head}\n  error: {self.error}"
        lines = [head]
        if self.run:
            lines.append(f"  agent: {self.run.stopped_because} after {self.run.step_count} steps, "
                         f"{self.run.llm_calls} llm calls")
            if self.run.result:
                lines.append(f"  said : {self.run.result}")
        for check in self.checks:
            lines.append(f"  [{'ok ' if check.passed else 'BAD'}] {check.label} -> "
                         f"{check.observed}")
        return "\n".join(lines)


def run_task(page, spec: TaskSpec, planner=None, verbose: bool = False) -> TaskOutcome:
    outcome = TaskOutcome(task=spec.name, run=None)
    try:
        page.goto(spec.start_url, wait_until="domcontentloaded")
        agent = BrowserAgent(page, planner=planner, max_steps=spec.max_steps)
        outcome.run = agent.run(spec.goal, verbose=verbose)
    except Exception as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome

    for check in spec.checks:
        passed, observed = check.evaluate(page)
        outcome.checks.append(CheckResult(check.label or check.kind, passed, observed))
    return outcome
