"""RPA task mode: run a goal, then assert the final page state."""

from modes.rpa_task.runner import Check, TaskOutcome, TaskSpec, run_task

__all__ = ["Check", "TaskOutcome", "TaskSpec", "run_task"]
