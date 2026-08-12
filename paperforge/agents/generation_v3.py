"""Generation V3: plan-only call, then bounded per-kind batches."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from paperforge.config import get_config
from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.workspace_plan import FileSpec, WorkspacePlan
from paperforge.schemas.workspace_policy import SafeWorkspacePolicy
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)

GENERATION_ORDER = ["type", "fixture", "adapter", "hook", "component", "route", "api"]

IMPORT_RE = re.compile(r"""from\s+['"]([^'"]+)['"]""")
TS_IMPORT_RE = re.compile(r"""import(?:[\s\S]*?)from\s+['"]([^'"]+)['"]""")


class GeneratedFile(BaseModel):
    path: str
    content: str


class GeneratedBatch(BaseModel):
    summary: str = ""
    files: list[GeneratedFile] = Field(min_length=1, max_length=32)


def parse_local_imports(source: str) -> set[str]:
    """Collect local imports that start with the ``@/`` alias."""
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
    """One plan-only call that returns a WorkspacePlan."""
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
    """Surface only the files this batch depends on (dependency-aware)."""
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
) -> GeneratedBatch:
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
    raw = json.loads(response.content or "{}")
    batch = GeneratedBatch.model_validate(raw)
    validate_batch_contract(specs=specs, batch=batch)
    return batch


def validate_batch_contract(
    *,
    specs: list[FileSpec],
    batch: GeneratedBatch,
) -> None:
    """The WorkspacePlan is the codegen contract: a batch must produce exactly
    the planned paths — no more, no fewer, no duplicates."""
    expected = {spec.path for spec in specs}
    actual = {file.path for file in batch.files}

    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(f"Generation batch omitted planned files: " + ", ".join(sorted(missing)))
    if unexpected:
        raise ValueError(f"Generation batch returned unplanned files: " + ", ".join(sorted(unexpected)))
    if len(actual) != len(batch.files):
        raise ValueError("Generation batch contains duplicate paths")


def write_batch_files(
    *,
    workspace: Path,
    batch: GeneratedBatch,
    policy: SafeWorkspacePolicy | None = None,
) -> list[str]:
    """Write a batch's files to the workspace under the SafeWorkspacePolicy,
    returning the changed paths."""
    policy = policy or SafeWorkspacePolicy()

    total_bytes = sum(len(file.content.encode("utf-8")) for file in batch.files)
    if total_bytes > policy.MAX_PATCH_BYTES:
        raise ValueError("Generated batch exceeds size limit")

    root_resolved = workspace.resolve()
    changed: list[str] = []
    for file in batch.files:
        relative = policy.normalize(file.path)
        if relative in policy.PROTECTED_FILES:
            raise ValueError(f"Protected file: {relative}")
        policy.validate_content(file.content)

        target = (workspace / relative).resolve()
        target.relative_to(root_resolved)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.content, encoding="utf-8")
        changed.append(relative)
    return changed


def _merge_dependencies(workspace: Path, dependencies: dict[str, str]) -> None:
    """Merge plan-declared deps into package.json, pinning scripts to SAFE_SCRIPTS."""
    from paperforge.agents.nextjs_generator import SAFE_SCRIPTS
    from paperforge.schemas.app_manifest import ALLOWED_DEPENDENCIES

    pkg_path = workspace / "package.json"
    pkg = (
        json.loads(pkg_path.read_text(encoding="utf-8"))
        if pkg_path.exists()
        else {}
    )
    blocked = {
        name: version
        for name, version in dependencies.items()
        if name not in ALLOWED_DEPENDENCIES
    }
    if blocked:
        raise ValueError(f"Refusing to declare non-allowlist dependencies: {sorted(blocked)}")
    pkg["scripts"] = SAFE_SCRIPTS
    pkg["dependencies"] = {**(pkg.get("dependencies") or {}), **dependencies}
    pkg_path.write_text(json.dumps(pkg, indent=2), encoding="utf-8")


async def generate_nextjs_app_v3(
    *,
    prd_id: str,
    output_dir: str | Path,
    llm: LLMClient,
    storage: Storage,
    progress=None,
) -> dict[str, Any]:
    """High-level Generation V3 entry: plan-only call, then bounded per-kind
    batches with dependency-aware context.

    Reuses the template scaffold + atomic promotion from nextjs_generator so
    V3 keeps the same safe workspace policy without re-deriving it.
    """
    from paperforge.agents.nextjs_generator import TEMPLATE_DIR
    from paperforge.storage.db import Storage

    artifact = storage.get_artifact(prd_id)
    if not artifact:
        raise ValueError(f"PRD not found: {prd_id}")
    prd = artifact.get("data") or {}

    final_dir = Path(output_dir).resolve()
    apps_root = storage.apps_dir.resolve()
    try:
        final_dir.relative_to(apps_root)
    except ValueError as exc:
        raise ValueError(f"output_dir must be inside {apps_root}, got {final_dir}") from exc
    if final_dir == apps_root:
        raise ValueError("output_dir must name a child app directory")

    if not TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Template directory not found: {TEMPLATE_DIR}")

    app_id = f"app_{uuid.uuid4().hex[:8]}"
    generated_files: list[str] = []

    with tempfile.TemporaryDirectory(prefix="paperforge-v3-", dir=str(apps_root)) as tmp:
        temp_dir = Path(tmp)
        shutil.copytree(src=TEMPLATE_DIR, dst=temp_dir, dirs_exist_ok=True)

        plan = await plan_workspace(prd=prd, llm=llm)
        if not plan.app_name or plan.app_name == "generated-app":
            plan.app_name = app_id

        try:
            for kind, specs in group_plan_files(plan):
                step_id = None
                if progress is not None:
                    step_id = await progress.start(
                        kind="codegen",
                        title=f"Generating {kind} ({len(specs)} files)",
                    )
                batch = await generate_batch(
                    prd=prd,
                    plan=plan,
                    specs=specs,
                    workspace=temp_dir,
                    llm=llm,
                )
                changed = write_batch_files(workspace=temp_dir, batch=batch)
                generated_files.extend(changed)
                if progress is not None and step_id is not None:
                    await progress.complete(
                        step_id,
                        summary=f"{len(changed)} files generated",
                    )
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        _merge_dependencies(temp_dir, plan.dependencies)

        # Atomic promote temp_dir → final_dir (never partially overwrite).
        backup: Path | None = None
        try:
            if final_dir.exists():
                backup = final_dir.with_name(final_dir.name + ".previous")
                if backup.exists():
                    shutil.rmtree(backup)
                os.replace(final_dir, backup)

            os.replace(temp_dir, final_dir)
        except Exception:
            # Restore the previous app if promotion to the new path failed.
            if backup is not None and backup.exists() and not final_dir.exists():
                os.replace(backup, final_dir)
            raise

    plan.dependencies = plan.dependencies  # keep plan deps for the manifest

    return {
        "app_id": app_id,
        "prd_id": prd_id,
        "plan": plan.model_dump(),
        "files": generated_files,
        "dependencies": plan.dependencies,
        "output_dir": str(final_dir),
    }
