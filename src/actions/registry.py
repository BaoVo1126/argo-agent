from __future__ import annotations
from dataclasses import dataclass, field
from src.config import SETTINGS
from src.perception.dom import Snapshot


@dataclass
class ActionResult:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)
    finished: bool = False
    success: bool = False


def _resolve(snapshot: Snapshot, element_id, kind: str):
    try:
        element_id = int(element_id)
    except (TypeError, ValueError):
        return None, ActionResult(False, f"{kind}: id must be an integer, got {element_id!r}")

    element = snapshot.by_id(element_id)
    if element is None:
        highest = len(snapshot.elements)
        return None, ActionResult(
            False, f"{kind}: no element [{element_id}] on this page (ids are 1..{highest})"
        )
    if not element.enabled:
        return None, ActionResult(False, f"{kind}: element [{element_id}] is disabled")
    return element, None


def click(page, snapshot: Snapshot, id: int) -> ActionResult:
    element, error = _resolve(snapshot, id, "click")
    if error:
        return error
    try:
        page.click(element.selector, timeout=SETTINGS.action_timeout_ms)
    except Exception as exc:
        return ActionResult(False, f"click failed on {element.selector}: {_brief(exc)}")
    return ActionResult(True, f"clicked [{id}] {element.role} {element.text!r}",
                        data={"selector": element.selector})


def type(page, snapshot: Snapshot, id: int, text: str) -> ActionResult:
    element, error = _resolve(snapshot, id, "type")
    if error:
        return error
    try:
        page.fill(element.selector, str(text), timeout=SETTINGS.action_timeout_ms)
    except Exception as exc:
        return ActionResult(False, f"type failed on {element.selector}: {_brief(exc)}")
    return ActionResult(True, f"typed {text!r} into [{id}] {element.text!r}",
                        data={"selector": element.selector, "text": str(text)})


def select(page, snapshot: Snapshot, id: int, value: str) -> ActionResult:
    element, error = _resolve(snapshot, id, "select")
    if error:
        return error
    if element.options and value not in element.options:
        return ActionResult(
            False, f"select: {value!r} is not an option of [{id}]; options are {element.options}"
        )
    try:
        page.select_option(element.selector, value, timeout=SETTINGS.action_timeout_ms)
    except Exception as exc:
        return ActionResult(False, f"select failed on {element.selector}: {_brief(exc)}")
    return ActionResult(True, f"selected {value!r} in [{id}]",
                        data={"selector": element.selector, "value": value})


def scroll(page, snapshot: Snapshot, direction: str) -> ActionResult:
    if direction not in ("up", "down"):
        return ActionResult(False, "scroll: direction must be 'up' or 'down'")
    delta = 600 if direction == "down" else -600
    try:
        page.mouse.wheel(0, delta)
        page.wait_for_timeout(200)
    except Exception as exc:
        return ActionResult(False, f"scroll failed: {_brief(exc)}")
    return ActionResult(True, f"scrolled {direction}")


def _timeout(page) -> int:
    return getattr(page, "_argo_timeout_ms", None) or SETTINGS.action_timeout_ms


def navigate(page, snapshot: Snapshot, url: str) -> ActionResult:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=_timeout(page))
    except Exception as exc:
        return ActionResult(False, f"navigate to {url} failed: {_brief(exc)}")
    return ActionResult(True, f"navigated to {page.url}")


def wait_for(page, snapshot: Snapshot, selector: str) -> ActionResult:
    try:
        page.wait_for_selector(selector, timeout=_timeout(page))
    except Exception as exc:
        return ActionResult(False, f"wait_for {selector!r} timed out: {_brief(exc)}")
    return ActionResult(True, f"{selector!r} appeared")


def extract(page, snapshot: Snapshot, selector: str) -> ActionResult:
    try:
        nodes = page.query_selector_all(selector)
    except Exception as exc:
        return ActionResult(False, f"extract {selector!r} failed: {_brief(exc)}")
    if not nodes:
        return ActionResult(False, f"extract: nothing matched {selector!r}")

    values = [" ".join((n.inner_text() or "").split()) for n in nodes[:30]]
    return ActionResult(
        True, f"extracted {len(values)} value(s) from {selector!r}", data={"values": values}
    )


def finish(page, snapshot: Snapshot, success: bool, result: str = "") -> ActionResult:
    return ActionResult(
        True,
        f"finished (success={success})" + (f": {result}" if result else ""),
        data={"result": result},
        finished=True,
        success=bool(success),
    )


ACTIONS = {
    "click": click,
    "type": type,
    "select": select,
    "scroll": scroll,
    "navigate": navigate,
    "wait_for": wait_for,
    "extract": extract,
    "finish": finish,
}


def execute(page, snapshot: Snapshot, name: str, args: dict) -> ActionResult:
    handler = ACTIONS.get(name)
    if handler is None:
        return ActionResult(False, f"unknown action {name!r}; available: {sorted(ACTIONS)}")
    try:
        return handler(page, snapshot, **args)
    except TypeError as exc:
        return ActionResult(False, f"{name}: bad arguments {args} -- {exc}")


def _brief(exc: Exception, limit: int = 160) -> str:
    """Playwright errors carry a long call log; the first line is the reason."""
    return str(exc).split("\n")[0][:limit]
