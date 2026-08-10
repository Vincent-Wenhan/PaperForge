"""Browser smoke runner tests (doc 40.6, 40.7 + existing not_applicable case)."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from paperforge.agents.browser_smoke import run_browser_smoke


@pytest.mark.asyncio
async def test_browser_smoke_without_acceptance_criteria_is_not_applicable(tmp_path):
    result = await run_browser_smoke("http://127.0.0.1:1/", None, tmp_path)

    assert result["status"] == "not_applicable"
    assert result["checks"] == []


class _PreviewHandler(BaseHTTPRequestHandler):
    requested_urls: list[str] = []

    def do_GET(self) -> None:  # noqa: N802
        type(self).requested_urls.append(self.path)
        if self.path.startswith("/settings"):
            body = b'<div data-testid="settings">settings</div>'
        else:
            body = b'<input data-testid="search" />'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # noqa: D401 - silence request logging
        pass


def _make_preview(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), _PreviewHandler)
    _PreviewHandler.requested_urls = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"
    out_dir = tmp_path / "out"
    return url, out_dir, lambda: list(_PreviewHandler.requested_urls), server


def _stop_server(server) -> None:
    server.shutdown()
    server.server_close()


@pytest.mark.asyncio
async def test_route_criterion_uses_route_not_selector(tmp_path):
    """doc 40.6 — a route criterion navigates to the route and passes."""
    url, out_dir, requested, server = _make_preview(tmp_path)
    try:
        prd = {
            "acceptance_criteria": [
                {
                    "id": "ac_route",
                    "feature_id": "f1",
                    "priority": "must",
                    "description": "Settings route loads",
                    "test_kind": "route",
                    "route": "/settings",
                    "selector": "[data-testid='settings']",
                    "action": "none",
                    "expected": None,
                }
            ]
        }
        result = await run_browser_smoke(url, prd, out_dir)
        assert result["checks"][0]["status"] == "passed"
        assert "/settings" in requested()
    finally:
        _stop_server(server)


@pytest.mark.asyncio
async def test_interaction_fill_uses_input_value(tmp_path):
    """doc 40.7 — an interaction/fill criterion types input_value and passes."""
    url, out_dir, _, server = _make_preview(tmp_path)
    try:
        prd = {
            "acceptance_criteria": [
                {
                    "id": "ac_fill",
                    "feature_id": "f1",
                    "priority": "must",
                    "description": "Search input works",
                    "test_kind": "interaction",
                    "route": "/",
                    "selector": "[data-testid='search']",
                    "action": "fill",
                    "input_value": "paper",
                    "expected": "paper",
                }
            ]
        }
        result = await run_browser_smoke(url, prd, out_dir)
        assert result["checks"][0]["status"] == "passed"
    finally:
        _stop_server(server)
