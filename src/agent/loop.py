"""
Perceive -> Reason -> Act -> Verify, with a budget.

Verification here is deliberately shallow: after acting, the loop re-perceives
and hands the model the new page plus the outcome of what it just did. The
model does the judging. What the loop owns is the part a model cannot be
trusted with -- knowing when to stop.

Three stopping conditions, and each exists because of a distinct failure:

  - `finish` was called. The normal end.
  - The step budget ran out. A model that keeps making progress-shaped moves
    without converging would otherwise run until the rate limit does.
  - The same action repeated `max_repeats` times. Clicking a button that does
    nothing is not a retry after the second attempt, it is a loop, and it is
    the most common way an agent burns a quota.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.actions.registry import ActionResult, execute
from src.config import SETTINGS
from src.llm.decision import Decision
from src.perception.dom import perceive


@dataclass
class Step:
    index: int
    action: str
    args: dict
    ok: bool
    message: str
    url: str
    # The selector the action resolved to, when it resolved one. Testing mode
    # replays this; the loop itself never reads it.
    selector: str = ""


@dataclass
class RunResult:
    goal: str
    success: bool
    result: str
    steps: list[Step] = field(default_factory=list)
    stopped_because: str = ""
    llm_calls: int = 0
    tokens: int = 0

    @property
    def step_count(self) -> int:
        return len(self.steps)


class BrowserAgent:
    def __init__(self, page, planner=None, max_steps: int | None = None):
        self.page = page
        if planner is None:
            from src.llm.factory import get_planner

            planner = get_planner()
        self.planner = planner
        self.max_steps = max_steps or SETTINGS.max_steps

    def run(self, goal: str, verbose: bool = False) -> RunResult:
        run = RunResult(goal=goal, success=False, result="")
        history: list[str] = []
        recent: list[tuple[str, str]] = []

        for index in range(1, self.max_steps + 1):
            snapshot = perceive(self.page)
            observation = snapshot.render(SETTINGS.max_elements)

            decision = self.planner.decide(goal, observation, history)
            signature = (decision.action, _signature(decision.args))

            recent.append(signature)
            if _repeated(recent, SETTINGS.max_repeats):
                run.stopped_because = (
                    f"repeated {decision.action}{decision.args} "
                    f"{SETTINGS.max_repeats} times without progress"
                )
                break

            outcome = execute(self.page, snapshot, decision.action, decision.args)
            self._settle()

            step = Step(index, decision.action, decision.args, outcome.ok, outcome.message,
                        self.page.url, outcome.data.get("selector", ""))
            run.steps.append(step)
            history.append(_describe(step, outcome))
            if verbose:
                mark = "ok " if outcome.ok else "ERR"
                print(f"  {index:>2} [{mark}] {decision.action}{decision.args} -> {outcome.message}")

            if outcome.finished:
                run.success = outcome.success
                run.result = outcome.data.get("result", "")
                run.stopped_because = "finish"
                break
        else:
            run.stopped_because = f"step budget of {self.max_steps} exhausted"

        run.llm_calls = self.planner.calls
        run.tokens = self.planner.tokens
        return run

    def _settle(self) -> None:
        """Let a click's navigation or re-render land before re-perceiving.

        Without this the next snapshot can catch the old DOM, and the model
        is asked to reason about a page that no longer exists. `networkidle`
        is skipped on purpose -- these apps keep connections open and it
        routinely times out on a page that is perfectly ready.
        """
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=SETTINGS.action_timeout_ms)
            self.page.wait_for_timeout(250)
        except Exception:
            pass  # a timeout here is not a failure; the next snapshot decides


def _signature(args: dict) -> str:
    return ",".join(f"{k}={args[k]}" for k in sorted(args))


def _repeated(recent: list[tuple[str, str]], limit: int) -> bool:
    return len(recent) >= limit and len(set(recent[-limit:])) == 1


def _describe(step: Step, outcome: ActionResult) -> str:
    line = f"step {step.index}: {step.action}({_signature(step.args)}) -> {outcome.message}"
    values = outcome.data.get("values")
    if values:
        line += f" | values={values[:10]}"
    return line
