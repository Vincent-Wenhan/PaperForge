"""Tests for the unified streaming build/test runner (doc 26)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from paperforge.agents.verifier import run_command_stream


@pytest.mark.asyncio
async def test_run_command_stream_captures_output(tmp_path: Path):
    results: list[str] = []

    async def on_line(text: str) -> None:
        results.append(text)

    result = await run_command_stream(
        [sys.executable, "-c", "import sys; print('hello'); print('world', file=sys.stderr)"],
        tmp_path,
        timeout_s=30,
        on_line=on_line,
    )

    assert result.returncode == 0
    assert "hello" in result.stdout
    # stderr is merged into stdout via STDOUT.
    assert "world" in result.stdout
    assert not result.timed_out
    # on_line received the streamed lines.
    assert any("hello" in line for line in results)


@pytest.mark.asyncio
async def test_run_command_stream_times_out_hung_process(tmp_path: Path):
    result = await run_command_stream(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        tmp_path,
        timeout_s=0.5,
    )

    assert result.timed_out
    assert result.returncode != 0


@pytest.mark.asyncio
async def test_run_command_stream_missing_command(tmp_path: Path):
    result = await run_command_stream(
        ["definitely-not-a-real-command-xyz"],
        tmp_path,
        timeout_s=5,
    )
    assert result.returncode == -1
    assert "not found" in result.stderr.lower()
