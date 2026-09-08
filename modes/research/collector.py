"""
Run a source's plan in a real browser and hand back its raw records.

This is the research mode's Act layer: every step goes through
`src/actions/registry.py` against a fresh `perceive()` snapshot. A source that
needed an action outside the registry would be a signal that the action space
is wrong, not a reason to reach past it.

The steps are written down rather than chosen at run time, so a collection
costs zero LLM calls and repeats exactly.
"""

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

# A stated identity beats a default headless one: it is honest about what the
# traffic is, and some sites serve a stripped page to an unrecognised agent.
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
    """Chromium in its new headless mode, falling back to the old one.

    Not a preference: vietcombank.com.vn answers old-headless Chromium with
    ERR_HTTP2_PROTOCOL_ERROR and then, with HTTP/2 disabled, with nothing at
    all -- while the same request from `channel="chromium"` (the new headless
    mode, which is the real browser rather than a separate binary) loads
    normally. The fallback is for a machine where that channel is not
    installed; sites that only tolerate the new mode will fail there, and the
    error will say so.
    """
    try:
        return playwright.chromium.launch(headless=headless, channel="chromium")
    except Exception:
        return playwright.chromium.launch(headless=headless)


@contextmanager
def browser_page(headless: bool | None = None):
    """One browser, reused across sources. Closing it is the caller's job."""
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
    """Where progress goes. The terminal by default, a web job's buffer when
    one is passed -- the scrape is slow enough that a caller with no running
    commentary looks hung."""
    if log is not None:
        return log
    return print if verbose else (lambda _line: None)


def collect(page, source: Source, verbose: bool = True,
            log: Callable[[str], None] | None = None) -> SourceResult:
    """Execute one source's plan, then its extractor. Never raises."""
    emit = _sink(log, verbose)
    started = time.monotonic()
    result = SourceResult(source=source.name, site=source.site, url=source.url, ok=False)

    # Playwright's per-page default is what registry.execute falls back to for
    # navigation, so a per-source allowance is set on the page rather than
    # threaded through the shared action signatures.
    page._argo_timeout_ms = source.timeout_ms or None

    for name, args in source.plan:
        snapshot = perceive(page)
        outcome = execute(page, snapshot, name, args)
        line = f"{name}({', '.join(f'{k}={v}' for k, v in args.items())}) -> {outcome.message}"
        result.steps.append(line)
        emit(f"    [{'ok ' if outcome.ok else 'ERR'}] {line[:140]}")
        if not outcome.ok:
            # wait_for timing out is survivable -- the extractor may still find
            # what it needs -- but a failed navigate means there is no page.
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
