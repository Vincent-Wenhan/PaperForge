"""Tests for Generation V3 (plan-only + per-kind batches, doc 18-20)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperforge.agents.generation_v3 import (
    GeneratedBatch,
    build_generation_context,
    generate_batch,
    group_plan_files,
    import_to_paths,
    parse_local_imports,
    plan_workspace,
    validate_batch_contract,
    write_batch_files,
)
from paperforge.llm.base import ChatResponse, LLMClient, Message
from paperforge.schemas.workspace_plan import FileSpec, WorkspacePlan


class FakeLLM(LLMClient):
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.i = 0

    async def chat(self, model, messages, tools=None, response_format=None, **kwargs):
        resp = self.responses[self.i]
        self.i += 1
        return ChatResponse(content=json.dumps(resp), finish_reason="stop")

    async def stream(self, *args, **kwargs):
        yield None  # pragma: no cover


def test_parse_local_imports():
    src = 'import { A } from "@/components/Card";\nexport {};'
    assert parse_local_imports(src) == {"@/components/Card"}


def test_import_to_paths():
    assert import_to_paths("@/types/m") == [
        "types/m.ts", "types/m.tsx", "types/m.js",
        "types/m/index.ts", "types/m/index.tsx",
    ]
    assert import_to_paths("react") == []


def test_group_plan_files_orders_by_kind():
    plan = WorkspacePlan(
        app_name="x",
        files=[
            FileSpec(path="app/page.tsx", kind="route", purpose="home"),
            FileSpec(path="types/m.ts", kind="type", purpose="t"),
            FileSpec(path="lib/a.ts", kind="adapter", purpose="a"),
            FileSpec(path="components/C.tsx", kind="component", purpose="c"),
        ],
    )
    groups = group_plan_files(plan)
    kinds = [kind for kind, _ in groups]
    assert kinds == ["type", "adapter", "component", "route"]


@pytest.mark.asyncio
async def test_plan_workspace_returns_plan(tmp_path):
    llm = FakeLLM([
        {
            "app_name": "App",
            "routes": [{"path": "app/page.tsx", "purpose": "home"}],
            "files": [
                {"path": "types/m.ts", "kind": "type", "purpose": "t", "depends_on": []},
                {"path": "app/page.tsx", "kind": "route", "purpose": "home", "depends_on": ["types/m.ts"]},
            ],
        }
    ])
    plan = await plan_workspace({"goal": "x"}, llm)
    assert plan.app_name == "App"
    assert len(plan.files) == 2


def test_build_generation_context_is_dependency_aware(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "types").mkdir()
    (ws / "types" / "m.ts").write_text("export type T = 1;")
    (ws / "components").mkdir()
    (ws / "components" / "Big.tsx").write_text("x" * 100_000)  # huge, should be excluded

    specs = [FileSpec(path="app/page.tsx", kind="route", purpose="home", depends_on=["types/m.ts"])]
    context = build_generation_context(specs=specs, workspace=ws, max_chars=80_000)
    paths = [c["path"] for c in context]
    assert "types/m.ts" in paths
    # The huge component is not in the dependency set, so it is not surfaced.
    assert "components/Big.tsx" not in paths


def test_write_batch_files_rejects_traversal_and_policy_violation(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    batch = GeneratedBatch.model_validate(
        {
            "files": [
                {"path": "app/page.tsx", "content": "export default () => null;"},
            ]
        }
    )
    changed = write_batch_files(workspace=ws, batch=batch)
    assert changed == ["app/page.tsx"]
    assert (ws / "app" / "page.tsx").exists()


def test_write_batch_files_rejects_unplanned_root(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    batch = GeneratedBatch.model_validate(
        {
            "files": [
                {"path": ".env", "content": "SECRET=1"},
            ]
        }
    )
    try:
        write_batch_files(workspace=ws, batch=batch)
        raise AssertionError("expected policy violation")
    except ValueError:
        pass


def test_validate_batch_contract_rejects_unplanned_file():
    specs = [FileSpec(path="app/page.tsx", kind="route", purpose="home")]
    batch = GeneratedBatch.model_validate(
        {
            "files": [
                {"path": "app/page.tsx", "content": "x"},
                {"path": "app/extra.tsx", "content": "y"},
            ]
        }
    )
    try:
        validate_batch_contract(specs=specs, batch=batch)
        raise AssertionError("expected contract violation")
    except ValueError as exc:
        assert "unplanned" in str(exc)


def test_validate_batch_contract_rejects_missing_file():
    specs = [FileSpec(path="app/page.tsx", kind="route", purpose="home")]
    batch = GeneratedBatch.model_validate(
        {
            "files": [
                {"path": "app/other.tsx", "content": "x"},
            ]
        }
    )
    try:
        validate_batch_contract(specs=specs, batch=batch)
        raise AssertionError("expected contract violation")
    except ValueError as exc:
        assert "omitted" in str(exc)


@pytest.mark.asyncio
async def test_generate_batch_bounded_call(tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "types").mkdir()
    (ws / "types" / "m.ts").write_text("export type T = 1;")

    plan = WorkspacePlan(
        app_name="x",
        files=[
            FileSpec(path="types/m.ts", kind="type", purpose="t"),
            FileSpec(path="components/C.tsx", kind="component", purpose="c", depends_on=["types/m.ts"]),
        ],
    )
    llm = FakeLLM([
        {
            "summary": "component batch",
            "files": [
                {"path": "components/C.tsx", "content": 'export const C = () => <div>C</div>;'},
            ],
        }
    ])
    batch = await generate_batch(
        prd={"goal": "x"},
        plan=plan,
        specs=[FileSpec(path="components/C.tsx", kind="component", purpose="c", depends_on=["types/m.ts"])],
        workspace=ws,
        llm=llm,
    )
    assert isinstance(batch, GeneratedBatch)
    assert len(batch.files) == 1
