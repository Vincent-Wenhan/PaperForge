"""Generation V3: plan-only call, then bounded per-kind batches (doc 18-20).

Rather than one giant JSON with the whole app, V3:
1. ``plan_workspace`` — a single plan-only LLM call returning a WorkspacePlan.
2. ``group_plan_files`` — order the plan's files by GENERATION_ORDER.
3. ``generate_batch`` — one bounded LLM call per batch, with dependency-aware
   context (only already-written dependency files), so a failing batch can be
   retried without regenerating the whole app.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from paperforge.config import get_config
from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.workspace_plan import FileSpec, WorkspacePlan

logger = logging.getLogger(__name__)

GENERATION_ORDER = ["type", "fixture", "adapter", "hook", "component", "route", "api"]

IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
TS_IMPORT_RE = re.compile(r"""import(?:[\s\S]*?)from\s+['"]([^'"]+)['"]""")


def parse_local_imports(source: str) -> set[str]:
    """Collect local imports that start with the ``@/`` alias (doc 20.1)."""
    return {
        m.group(1)
        for m in TS_IMPORT_RE.finditer(source) or IMPORT_RE.finditer(source)
        if m.group(1).startswith("@/")
    }


def import_to_paths(module: str) -> list[str]:
    """Resolve an ``@/x`` alias to candidate on-disk paths."""
    if not module.startswith("@/"):
        return []
    base = module[2:]
    return [
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}.js",
        f"{base}/index.ts",
        f"{base}/index.tsx",
    ]


def group_plan_files(plan: WorkspacePlan) -> list[tuple[str, list[FileSpec]]]:
    """Group a plan's files into batches ordered by dependency-safe kind."""
    by_kind: dict[str, list[FileSpec]] = defaultdict(list)
    for file in plan.files:
        by_kind[file.kind].append(file)
    return [
        (kind, by_kind[kind])
        for kind in GENERATION_ORDER
        if by_kind.get(kind)
    ]


async def plan_workspace(prd: dict, llm: LLMClient) -> WorkspacePlan:
    """One plan-only call that returns a WorkspacePlan (doc 19.1)."""
    response = await llm.chat(
        model=get_config().GENERATOR_MODEL,
        messages=[
            Message(role="system", content=load_prompt("workspace_planner")),
            Message(role="user", content=json.dumps(prd, ensure_ascii=False, indent=2)),
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(response.content or "{}")
    return WorkspacePlan.model_validate(data)


def _existing_files(workspace: Path) -> set[str]:
    blocked = {"node_modules", ".next", ".git", "dist", "build", ".cache"}
    files: set[str] = set()
    if not workspace.exists():
        return files
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).parts
        if any(part in blocked for part in rel):
            continue
        files.add("/".join(rel))
    return files


def build_generation_context(
    *,
    specs: list[FileSpec],
    workspace: Path,
    max_chars: int = 80_000,
) -> list[dict[str, str]]:
    """Surface only the files this batch depends on (dependency-aware, doc 20)."""
    required = set()
    for spec in specs:
        required.update(spec.depends_on)
    # Shared contracts are always relevant short context.
    required.update(["types/", "lib/"])
    existing = _existing_files(workspace)

    selected: list[str] = []
    for spec in required:
        if spec.endswith("/"):
            prefix = spec
            selected.extend(p for p in existing if p.startswith(prefix))
            continue
        for candidate in import_to_paths(spec):
            if candidate in existing:
                selected.append(candidate)
                break
        else:
            if spec in existing:
                selected.append(spec)

    # Dedup, deterministic order.
    selected = sorted(set(selected))

    result: list[dict[str, str]] = []
    used = 0
    for path in selected:
        try:
            content = (workspace / path).read_text(encoding="utf-8")
        except OSError:
            continue
        lump = f"// {path}\n{content}"
        if used + len(lump) > max_chars:
            break
        used += len(lump)
        result.append({"path": path, "content": lump})
    return result


async def generate_batch(
    *,
    prd: dict,
    plan: WorkspacePlan,
    specs: list[FileSpec],
    workspace: Path,
    llm: LLMClient,
) -> dict[str, Any]:
    """One bounded LLM call that produces the files for a single batch."""
    context = build_generation_context(specs=specs, workspace=workspace)
    response = await llm.chat(
        model=get_config().GENERATOR_MODEL,
        messages=[
            Message(role="system", content=load_prompt("workspace_batch_generator")),
            Message(
                role="user",
                content=json.dumps(
                    {
                        "prd": prd,
                        "plan": plan.model_dump(),
                        "files_to_generate": [spec.model_dump() for spec in specs],
                        "context": context,
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        response_format={"type": "json_object"},
    )
    data = json.loads(response.content or "{}")
    return {
        "summary": data.get("summary", ""),
        "files": data.get("files", []),
        "_kind": specs[0].kind if specs else "unknown",
    }


def write_batch_files(workspace: Path, batch: dict[str, Any]) -> list[str]:
    """Write a batch's files to the workspace, returning the changed paths."""
    changed: list[str] = []
    for f in batch.get("files", []):
        path = f.get("path")
        content = f.get("content")
        if not path or content is None:
            continue
        target = (workspace / path).resolve()
        if workspace.resolve() not in target.parents and target != workspace.resolve():
            logger.warning("Refusing to write outside workspace: %s", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        changed.append(path)
    return changed
