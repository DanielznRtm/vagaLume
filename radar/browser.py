"""A real (headless) browser, for sites that only work with JavaScript.

Most sources use plain HTTP (radar/http.py), which is faster and simpler.
Only a few sites, like Meta's careers page, build everything in the browser
and refuse plain requests. For those we open the page in headless Chromium
with Playwright and either read the visible text or catch the JSON that the
page downloads for itself.

Setup (done by the GitHub workflow):
    pip install playwright
    python -m playwright install --with-deps chromium

If Playwright is not installed, the sources that need it fail with a clear
message and every other source keeps working.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .http import USER_AGENT

PAGE_TIMEOUT_MS = 60_000
SETTLE_MS = 3_000  # extra wait after loading, for late requests

# Decides which network responses to keep: gets (url, post_data), returns True to keep.
ResponseFilter = Callable[[str, str], bool]


@dataclass
class RenderedPage:
    text: str  # what a person would see on the page
    html: str = ""  # the page's HTML after JavaScript ran
    captured: list[Any] = field(default_factory=list)  # JSON bodies of the kept responses


def _launch_options() -> dict[str, Any]:
    options: dict[str, Any] = {}
    # Only needed when running behind a proxy (not on GitHub Actions).
    if os.environ.get("HTTPS_PROXY"):
        options["proxy"] = {"server": os.environ["HTTPS_PROXY"]}
    if os.environ.get("RADAR_CHROMIUM_ARGS"):
        options["args"] = os.environ["RADAR_CHROMIUM_ARGS"].split()
    return options


def render(url: str, keep: ResponseFilter | None = None) -> RenderedPage:
    """Open `url` in headless Chromium and return its text (+ captured JSON)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("Playwright is not installed (pip install playwright)") from error

    page_result = RenderedPage(text="")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_launch_options())
        try:
            page = browser.new_page(user_agent=USER_AGENT)

            def on_response(response: Any) -> None:
                if keep is None or not keep(response.url, response.request.post_data or ""):
                    return
                try:
                    page_result.captured.append(json.loads(response.text()))
                except Exception:  # noqa: BLE001 - not JSON, or the body is gone
                    pass

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            try:
                page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS / 2)
            except Exception:  # noqa: BLE001 - some pages never go fully idle; that's fine
                pass
            page.wait_for_timeout(SETTLE_MS)
            page_result.text = page.inner_text("body")
            page_result.html = page.content()
        finally:
            browser.close()
    return page_result


def render_many(urls: list[str]) -> Iterator[tuple[str, str]]:
    """Open several pages, one after the other, in one browser: yields (url, visible text).
    A page that fails yields "" and the others go on."""
    if not urls:
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_launch_options())
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                    try:
                        page.wait_for_load_state("networkidle", timeout=PAGE_TIMEOUT_MS / 4)
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(SETTLE_MS)
                    yield url, page.inner_text("body")
                except Exception:  # noqa: BLE001 - one page failing doesn't stop the rest
                    yield url, ""
        finally:
            browser.close()
