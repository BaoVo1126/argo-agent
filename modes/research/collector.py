from __future__ import annotations
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable
from playwright.sync_api import sync_playwright
from src.actions.registry import execute
from src.config import SETTINGS
from src.perception.dom import perceive
from modes.research.sources import Source

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 ArgoResearchAgent/0.1"
)


@dataclass
class SourceResult:
    source: str
    site: str
    url: str
    ok: bool
    rows: list[dict] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    error: str = ""
    elapsed_s: float = 0.0
    elements_seen: int = 0

    @property
    def row_count(self) -> int:
        return len(self.rows)


def _launch(playwright, headless: bool):
    try:
        return playwright.chromium.launch(headless=headless, channel="chromium")
    except Exception:
        return playwright.chromium.launch(headless=headless)


@contextmanager
def browser_page(headless: bool | None = None):
    quiet = SETTINGS.headless if headless is None else headless
    with sync_playwright() as playwright:
        browser = _launch(playwright, quiet)
        context = browser.new_context(user_agent=USER_AGENT, locale="vi-VN",
                                      viewport={"width": 1366, "height": 900})
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()


def _sink(log: Callable[[str], None] | None, verbose: bool) -> Callable[[str], None]:
    if log is not None:
        return log
    return print if verbose else (lambda _line: None)


def collect(page, source: Source, verbose: bool = True,
            log: Callable[[str], None] | None = None) -> SourceResult:
    emit = _sink(log, verbose)
    started = time.monotonic()
    result = SourceResult(source=source.name, site=source.site, url=source.url, ok=False)

    page._argo_timeout_ms = source.timeout_ms or None

    for name, args in source.plan:
        snapshot = perceive(page)
        outcome = execute(page, snapshot, name, args)
        line = f"{name}({', '.join(f'{k}={v}' for k, v in args.items())}) -> {outcome.message}"
        result.steps.append(line)
        emit(f"    [{'ok ' if outcome.ok else 'ERR'}] {line[:140]}")
        if not outcome.ok:
            if name == "navigate":
                result.error = outcome.message
                result.elapsed_s = time.monotonic() - started
                return result

    try:
        page.wait_for_load_state("domcontentloaded", timeout=SETTINGS.action_timeout_ms)
    except Exception:
        pass

    try:
        result.elements_seen = len(perceive(page).elements)
        result.rows = source.extract(page)
        result.ok = True
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    result.elapsed_s = time.monotonic() - started
    return result


def collect_all(sources: list[Source], headless: bool | None = None,
                verbose: bool = True,
                log: Callable[[str], None] | None = None) -> list[SourceResult]:
    emit = _sink(log, verbose)
    results = []
    with browser_page(headless) as page:
        for source in sources:
            emit(f"  [{source.name}] {source.site} -- {source.note}")
            outcome = collect(page, source, verbose=verbose, log=log)
            status = f"{outcome.row_count} raw records" if outcome.ok else outcome.error
            emit(f"    {outcome.elapsed_s:5.1f}s  {status}")
            results.append(outcome)
    return results
