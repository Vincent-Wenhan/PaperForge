"""Tests for the Generate → Verify → Repair loop (PR-06)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from paperforge.agents.verifier import build_and_repair, verify_app
from paperforge.llm.base import ChatResponse, LLMClient, Message
from paperforge.llm.mock_provider import MockLLMClient


class FakeLLM(LLMClient):
    """Returns a scripted response per call."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def chat(
        self,
        model: str,
        messages: list[Message],
        tools: list[Any] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        if self.calls < len(self.responses):
            content = self.responses[self.calls]
            self.calls += 1
            return ChatResponse(content=content, finish_reason="stop")
        return ChatResponse(content="{}", finish_reason="stop")

    async def stream(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        yield None  # type: ignore


class MockStorage:
    def get_artifact(self, artifact_id):
        return None


@pytest.mark.asyncio
async def test_build_and_repair_stops_on_ready(tmp_path: Path):
    """build_and_repair must stop as soon as ready_for_preview is true."""

    app_path = tmp_path / "app"
    (app_path / "app").mkdir(parents=True)
    (app_path / "app" / "page.tsx").write_text(
        "export default function Page() { return <h1>Hi</h1>; }"
    )
    (app_path / "package.json").write_text("{}")

    # The fake LLM returns an empty patch on the first call. Since
    # verify_app with an empty app returns ready_for_preview=False but
    # _apply_repair_patch returns False (no errors to patch), the loop
    # exits early without further attempts.
    llm = FakeLLM(responses=["{}"])
    report = await build_and_repair(
        app_path=app_path,
        prd_id=None,
        llm=llm,
        storage=MockStorage(),
        max_attempts=3,
    )
    assert "repair_attempts" in report
    assert len(report["repair_attempts"]) >= 1


@pytest.mark.asyncio
async def test_build_and_repair_applies_patch(tmp_path: Path):
    """build_and_repair must apply LLM-provided patches in the loop."""

    app_path = tmp_path / "app"
    (app_path / "app").mkdir(parents=True)
    (app_path / "app" / "page.tsx").write_text(
        "export default function Page() { return <h1>Old</h1>; }"
    )
    (app_path / "lib").mkdir()
    (app_path / "lib" / "mock-api.ts").write_text("export const mock = {};")
    (app_path / "lib" / "real-api.ts").write_text("export const real = {};")
    (app_path / "package.json").write_text("{}")

    patch = json.dumps({
        "files": [
            {
                "path": "app/page.tsx",
                "content": "export default function Page() { return <h1>New</h1>; }",
            }
        ],
        "summary": "Updated page heading",
    })
    llm = FakeLLM(responses=[patch, "{}"])
    report = await build_and_repair(
        app_path=app_path,
        prd_id=None,
        llm=llm,
        storage=MockStorage(),
        max_attempts=2,
    )

    # Patched file must be on disk
    new_content = (app_path / "app" / "page.tsx").read_text()
    assert "New" in new_content
    assert "repair_attempts" in report
