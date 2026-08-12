"""Small, bounded browser smoke runner for generated app previews."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin

# Dev-server noise that must not pollute product acceptance.
IGNORED_REQUEST_PATTERNS = [
    re.compile(r"/favicon\.ico$"),
    re.compile(r"/_next/webpack-hmr"),
]

# Controlled, in-memory upload fixtures. The LLM/PRD may only pick a named
# fixture — never an arbitrary local filesystem path.
FIXTURES: dict[str, dict[str, Any]] = {
    "text": {
        "name": "fixture.txt",
        "mimeType": "text/plain",
        "buffer": b"PaperForge fixture",
    },
    "csv": {
        "name": "fixture.csv",
        "mimeType": "text/csv",
        "buffer": b"name,value\nsample,1\n",
    },
}


def classify_request_failure(url: str, error: str) -> Literal["ignore", "warning", "error"]:
    if any(pattern.search(url) for pattern in IGNORED_REQUEST_PATTERNS):
        return "ignore"
    if "ERR_ABORTED" in error:
        return "warning"
    return "error"


def _criteria_list(prd: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not prd:
        return []
    criteria = prd.get("acceptance_criteria") or []
    return [item for item in criteria if isinstance(item, dict)]


def _resolve_route(criterion: dict[str, Any]) -> str:
    """Route for a criterion. PRD V2 carries ``route``; fall back to ``/``."""
    return criterion.get("route") or "/"


async def _verify_expected(page, locator: Any, expected: Any) -> None:
    if expected is None:
        return
    if expected is True:
        if locator is None:
            raise RuntimeError("Expected visible element but selector is absent.")
        if not await locator.is_visible():
            raise RuntimeError("Expected element to be visible.")
        return
    if expected is False:
        if locator is not None and await locator.is_visible():
            raise RuntimeError("Expected element not to be visible.")
        return
    if isinstance(expected, str):
        if locator is not None:
            tag = await locator.evaluate("(el) => el.tagName")
            if tag == "INPUT" or (await locator.evaluate("(el) => el.getAttribute('contenteditable')")) is not None:
                actual = await locator.input_value()
            else:
                actual = await locator.inner_text()
            if expected not in actual:
                raise RuntimeError(f"Expected {expected!r} not found in element.")
        else:
            html = await page.content()
            if expected not in html:
                raise RuntimeError(f"Expected {expected!r} not found on page.")


async def _execute_interaction(page, criterion: dict[str, Any], timeout_ms: int) -> None:
    selector = criterion.get("selector")
    if not selector:
        raise RuntimeError("Interaction criterion requires a selector.")
    locator = page.locator(selector).first
    await locator.wait_for(state="visible", timeout=timeout_ms)

    action = criterion.get("action") or "none"
    input_value = criterion.get("input_value")
    if action == "none":
        pass
    elif action == "click":
        await locator.click(timeout=timeout_ms)
    elif action == "fill":
        if input_value is None:
            raise RuntimeError("fill action requires input_value.")
        await locator.fill(str(input_value))
    elif action == "select":
        if input_value is None:
            raise RuntimeError("select action requires input_value.")
        await locator.select_option(str(input_value))
    elif action == "upload":
        # Only allow controllable in-memory fixtures — never an arbitrary
        # local filesystem path chosen by the LLM/PRD.
        fixture_name = str(input_value) if input_value else "text"
        fixture = FIXTURES.get(fixture_name)
        if fixture is None:
            raise RuntimeError(f"Unknown browser test fixture: {fixture_name}")
        await locator.set_input_files(fixture)
    else:
        raise RuntimeError(f"Unsupported action: {action}")

    await _verify_expected(page, locator, criterion.get("expected"))


async def run_browser_smoke(
    base_url: str,
    prd: dict[str, Any] | None,
    output_dir: str | Path,
    *,
    timeout_ms: int = 30_000,
) -> dict[str, Any]:
    """Run executable PRD checks against a live preview.

    Playwright is an optional verifier dependency. If it is unavailable, the
    result is explicitly ``skipped`` so a missing local browser cannot be
    confused with a passing product check.
    """
    criteria = _criteria_list(prd)
    if not criteria:
        return {
            "status": "not_applicable",
            "checks": [],
            "console_errors": [],
            "failed_requests": [],
            "reason": "No executable acceptance criteria were supplied.",
        }

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "status": "skipped",
            "checks": [],
            "console_errors": [],
            "failed_requests": [],
            "reason": "Playwright is not installed; install the verifier dev extra to enable browser checks.",
        }

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    screenshot_path = output_path / f"browser-smoke-{stamp}.png"
    trace_path = output_path / f"browser-smoke-{stamp}.zip"
    console_errors: list[str] = []
    failed_requests: list[str] = []
    failed_request_noise: list[str] = []
    checks: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = await context.new_page()

        def on_request_failed(request: Any) -> None:
            text = f"{request.method} {request.url}: {request.failure}"
            level = classify_request_failure(request.url, str(request.failure))
            if level == "error":
                failed_requests.append(text)
            elif level == "warning":
                failed_request_noise.append(text)

        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            on_request_failed,
        )

        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as exc:
            checks.append({"id": "root", "status": "failed", "error": str(exc)})

        for index, criterion in enumerate(criteria):
            criterion_id = criterion.get("id") or f"criterion-{index + 1}"
            kind = criterion.get("test_kind") or "interaction"
            selector = criterion.get("selector")
            expected = criterion.get("expected")
            result: dict[str, Any] = {
                "id": criterion_id,
                "status": "passed",
                "kind": kind,
            }
            try:
                if kind in {"route", "api"}:
                    route = _resolve_route(criterion)
                    target = urljoin(base_url.rstrip("/") + "/", route.lstrip("/"))
                    await page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
                    if kind == "api":
                        response = await context.request.get(target, timeout=timeout_ms)
                        result["status_code"] = response.status
                        if response.status >= 400:
                            raise RuntimeError(f"HTTP {response.status} for {target}")
                        if isinstance(expected, str) and expected not in await response.text():
                            raise RuntimeError(f"Expected text not found in {target}")
                    else:
                        result["route"] = route
                elif kind == "text":
                    if not selector:
                        raise RuntimeError("Text criterion requires a selector")
                    locator = page.locator(selector).first
                    await locator.wait_for(state="visible", timeout=timeout_ms)
                    text = await locator.inner_text()
                    result["text"] = text
                    await _verify_expected(page, locator, expected)
                elif kind == "visual":
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                else:
                    result["route"] = _resolve_route(criterion)
                    route = _resolve_route(criterion)
                    await page.goto(urljoin(base_url.rstrip("/") + "/", route.lstrip("/")), wait_until="domcontentloaded", timeout=timeout_ms)
                    await _execute_interaction(page, criterion, timeout_ms)
            except Exception as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
            checks.append(result)

        try:
            await page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            screenshot_path = None
        await context.tracing.stop(path=str(trace_path))
        await browser.close()

    failed = any(item.get("status") == "failed" for item in checks)
    return {
        "status": "failed" if failed or console_errors or failed_requests else "passed",
        "checks": checks,
        "console_errors": console_errors,
        "failed_requests": failed_requests,
        "failed_request_noise": failed_request_noise,
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "trace_path": str(trace_path) if trace_path.exists() else None,
    }
