"""Tests for sub-agents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from paperforge.agents.composer import compose
from paperforge.agents.nextjs_generator import generate_nextjs_app
from paperforge.agents.paper_parser import parse_paper
from paperforge.agents.product_planner import plan_product
from paperforge.agents.verifier import verify_app
from paperforge.llm.base import ChatResponse, LLMClient, Message
from paperforge.llm.mock_provider import MockLLMClient
from paperforge.storage.db import Storage


class FakeLLM(LLMClient):
    def __init__(self, response_content: str):
        self.response_content = response_content
        self.calls = 0

    async def chat(self, model, messages, tools=None, response_format=None,
                   temperature=0.7, max_tokens=None) -> ChatResponse:
        self.calls += 1
        return ChatResponse(content=self.response_content, finish_reason="stop")

    async def stream(self, *args, **kwargs):
        yield None  # type: ignore


@pytest.mark.asyncio
async def test_compose_combines_cards(storage: Storage):
    """Compose should load cards and return a composition."""
    # Save a paper with a capability card
    card_data = {"paper_id": "p1", "title": "Paper 1", "method": "method 1"}
    card_path = storage.library_dir / "p1_card.json"
    card_path.write_text(json.dumps(card_data))

    paper = storage.upsert_paper(
        paper_id="p1",
        title="Paper 1",
        pdf_path="/tmp/p1.pdf",
        card_path=str(card_path),
        status="parsed",
    )

    llm = FakeLLM('{"composition_id": "comp_test", "concepts": []}')
    composition = await compose(card_ids=["p1"], llm=llm, storage=storage)
    # compose() generates its own composition_id
    assert "composition_id" in composition


class MockStorage:
    """Mock storage for verifier tests (verifier doesn't really use storage)."""
    def get_artifact(self, artifact_id):
        return None


@pytest.mark.asyncio
async def test_verifier_detects_missing_files(tmp_path: Path):
    app_path = tmp_path / "empty_app"
    app_path.mkdir()

    storage = MockStorage()
    report = await verify_app(app_path=str(app_path), prd_id=None, llm=MockLLMClient(), storage=storage)
    assert report["build_succeeded"] is False
    assert "Missing package.json" in report["build_errors"]


@pytest.mark.asyncio
async def test_verifier_detects_secrets(tmp_path: Path):
    app_path = tmp_path / "secret_app"
    app_path.mkdir()
    (app_path / "package.json").write_text("{}")
    (app_path / "app").mkdir()
    (app_path / "app" / "page.tsx").write_text("export default function Page() { return null; }")
    (app_path / "lib").mkdir()
    (app_path / "lib" / "secret.ts").write_text('export const KEY = "sk-12345678901234567890";')

    storage = MockStorage()
    report = await verify_app(app_path=str(app_path), prd_id=None, llm=MockLLMClient(), storage=storage)
    assert any("secret" in issue.lower() for issue in report["security_issues"])
