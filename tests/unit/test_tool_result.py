"""Tests for the new ToolStatus / ToolResult schema."""

from __future__ import annotations

import pytest

from paperforge.schemas.tool_result import ToolResult, ToolStatus


class TestToolStatus:
    def test_succeeded_ok(self) -> None:
        r = ToolResult(tool="t", status=ToolStatus.SUCCEEDED)
        assert r.ok is True
        assert r.status == ToolStatus.SUCCEEDED

    def test_failed_not_ok(self) -> None:
        r = ToolResult(tool="t", status=ToolStatus.FAILED, error="boom", retryable=True)
        assert r.ok is False
        assert r.retryable is True

    def test_blocked_not_ok(self) -> None:
        r = ToolResult(
            tool="plan_product",
            status=ToolStatus.BLOCKED,
            data={"questions": ["q1"]},
            summary="Need more input",
            stop_loop=True,
        )
        assert r.ok is False
        assert r.stop_loop is True
        assert r.data["questions"] == ["q1"]

    def test_cancelled_not_ok(self) -> None:
        r = ToolResult(tool="t", status=ToolStatus.CANCELLED)
        assert r.ok is False

    def test_backwards_compat_ok_true(self) -> None:
        r = ToolResult(tool="t", ok=True)
        assert r.ok is True
        assert r.status == ToolStatus.SUCCEEDED

    def test_backwards_compat_ok_false(self) -> None:
        r = ToolResult(tool="t", ok=False)
        assert r.ok is False
        assert r.status == ToolStatus.FAILED

    def test_model_dump_json_roundtrip(self) -> None:
        r = ToolResult(tool="t", status=ToolStatus.SUCCEEDED, summary="ok")
        as_json = r.model_dump_json()
        assert '"status":"succeeded"' in as_json.replace(" ", "")
