"""
RPA task mode -- FRAMEWORK ONLY, not yet exercised end to end.

An RPA task is an agent run plus a verdict: the agent says it filed the form,
and something that is not the agent decides whether the form was filed. That
separation is the whole point. An agent asked to grade itself grades its own
narration, and the failure mode is a confident "done" over an unchanged page.

The checks here read the live page after the run, which is the same principle
`evaluation/checkers/` already applies to the eval suite -- the difference is
only that a task ships its checks with it instead of naming a Python module.

Usage once the TODOs are closed:

    spec = TaskSpec(
        name="daily_login",
        goal="log in as standard_user",
        start_url="https://www.saucedemo.com/",
        checks=[Check.url_contains("inventory.html"),
                Check.text_contains("Products")],
    )
    outcome = run_task(page, spec)
    print(outcome.verdict())
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agent.loop import BrowserAgent, RunResult


@dataclass
class Check:
    """One assertion about the page the run left behind."""

    kind: str            # "url_contains" | "text_contains" | "selector_visible"
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
        # An empty check list is not a pass. A task nobody wrote a check for
        # has not been verified, and reporting it green is the exact failure
        # this mode exists to prevent.
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
    """Drive the goal with the shared agent loop, then check the page."""
    outcome = TaskOutcome(task=spec.name, run=None)
    try:
        page.goto(spec.start_url, wait_until="domcontentloaded")
        agent = BrowserAgent(page, planner=planner, max_steps=spec.max_steps)
        outcome.run = agent.run(spec.goal, verbose=verbose)
    except Exception as exc:
        outcome.error = f"{type(exc).__name__}: {exc}"
        return outcome

    # The checks run whether or not the agent claimed success: an agent that
    # gives up having already done the work should still pass, and one that
    # claims success having done nothing should still fail.
    for check in spec.checks:
        passed, observed = check.evaluate(page)
        outcome.checks.append(CheckResult(check.label or check.kind, passed, observed))
    return outcome


# --- What is missing, and why it is not guessed at -------------------------
#
# TODO(recovery): a real RPA job that fails at step 9 of 12 should retry that
# step, not the whole task. That needs a checkpoint notion the agent loop does
# not have -- and inventing one before a task exists that needs it would fix
# the design around a guess.
#
# TODO(scheduling): "run this every morning" is the usual reason to want RPA.
# Out of scope here; the runner is meant to be callable from cron or a CI job
# rather than to grow a scheduler of its own.
#
# TODO(secrets): credentials currently arrive inside `goal` as plain text,
# which puts them in the prompt and in every log line. They belong in the
# environment, referenced by name, and injected by the `type` action.
#
# TODO(task files): TaskSpec should load from YAML, the way
# evaluation/tasks/*.yaml already does, so tasks are data rather than code.
