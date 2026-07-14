"""Small, bounded browser smoke runner for generated app previews."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


def _criteria_list(prd: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not prd:
        return []
    criteria = prd.get("acceptance_criteria") or []
    return [item for item in criteria if isinstance(item, dict)]


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
            "status": "passed",
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
    checks: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = await context.new_page()
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.method} {request.url}: {request.failure}"
            ),
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
                    target = urljoin(base_url.rstrip("/") + "/", selector or "/")
                    response = await context.request.get(target, timeout=timeout_ms)
                    result["status_code"] = response.status
                    if response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status} for {target}")
                    if isinstance(expected, str) and expected not in await response.text():
                        raise RuntimeError(f"Expected text not found in {target}")
                elif kind == "text":
                    if not selector:
                        raise RuntimeError("Text criterion requires a selector")
                    locator = page.locator(selector).first
                    await locator.wait_for(state="visible", timeout=timeout_ms)
                    text = await locator.inner_text()
                    result["text"] = text
                    if isinstance(expected, str) and expected not in text:
                        raise RuntimeError("Expected text not found")
                elif kind == "visual":
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                else:
                    if selector:
                        await page.locator(selector).first.click(timeout=timeout_ms)
                    if isinstance(expected, str):
                        await page.get_by_text(expected, exact=False).first.wait_for(
                            state="visible", timeout=timeout_ms
                        )
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
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "trace_path": str(trace_path) if trace_path.exists() else None,
    }
