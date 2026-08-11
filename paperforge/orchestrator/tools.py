"""Tool definitions and dispatcher for the orchestrator.

Each sub-agent is registered as a tool. The orchestrator's main loop calls
`dispatch_tool` when the LLM returns a tool_call.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, ToolDefinition
from paperforge.orchestrator.events import EventEmitter
from paperforge.schemas.tool_result import ToolResult, ToolStatus
from paperforge.storage.db import Storage

# ===== Tool Definitions =====

TOOL_DEFINITIONS = [
    ToolDefinition(
        name="parse_paper",
        description="Parse a PDF and extract a capability card. Returns card_id and card JSON. Prefer paper_id — the backend resolves the PDF path from the library.",
        input_schema={
            "type": "object",
            "properties": {
                "paper_id": {
                    "type": "string",
                    "description": "Library paper ID (preferred). The backend resolves the PDF path; never construct server paths yourself.",
                },
                "pdf_path": {
                    "type": "string",
                    "description": "Legacy: direct path to a PDF file. Prefer paper_id.",
                },
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="compose_capabilities",
        description="Compose multiple capability cards into novel product concepts.",
        input_schema={
            "type": "object",
            "properties": {
                "card_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of capability card IDs",
                }
            },
            "required": ["card_ids"],
        },
    ),
    ToolDefinition(
        name="plan_product",
        description="Refine composition (or single capability card) into a PRD. Accepts either composition_id (multi-paper) or card_ids (single-paper). Returns PRD JSON or clarifying questions.",
        input_schema={
            "type": "object",
            "properties": {
                "composition_id": {
                    "type": "string",
                    "description": "Composition artifact ID (multi-paper flow). Either this or card_ids is required.",
                },
                "card_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Capability card IDs (single-paper flow, bypasses composition). Either this or composition_id is required.",
                },
                "user_requirement": {"type": "string"},
            },
            "required": ["user_requirement"],
        },
    ),
    ToolDefinition(
        name="generate_nextjs_app",
        description="Generate a Next.js app from a PRD. Returns app_id and app_path.",
        input_schema={
            "type": "object",
            "properties": {
                "prd_id": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["prd_id"],
        },
    ),
    ToolDefinition(
        name="verify_app",
        description="Verify a generated Next.js app builds and matches the PRD. Prefer app_artifact_id.",
        input_schema={
            "type": "object",
            "properties": {
                "app_artifact_id": {"type": "string"},
                "app_path": {"type": "string"},
                "prd_id": {"type": "string"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="build_and_repair",
        description="Verify an app and apply bounded repairs when build, type, or lint checks fail.",
        input_schema={
            "type": "object",
            "properties": {
                "app_artifact_id": {"type": "string"},
                "app_path": {"type": "string"},
                "prd_id": {"type": "string"},
                "max_attempts": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="repair_app",
        description="Repair a generated app from the latest verification report, then re-run verification.",
        input_schema={
            "type": "object",
            "properties": {
                "app_artifact_id": {"type": "string"},
                "app_path": {"type": "string"},
                "prd_id": {"type": "string"},
                "max_attempts": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="run_in_sandbox",
        description="Launch a generated app in a Docker sandbox for live preview. Prefer app_artifact_id.",
        input_schema={
            "type": "object",
            "properties": {
                "app_artifact_id": {"type": "string"},
                "app_path": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": [],
        },
    ),
    ToolDefinition(
        name="stop_sandbox",
        description="Stop a running sandbox by sandbox_id.",
        input_schema={
            "type": "object",
            "properties": {"sandbox_id": {"type": "string"}},
            "required": ["sandbox_id"],
        },
    ),
    ToolDefinition(
        name="restart_sandbox",
        description="Restart the latest sandbox for a run or a specified sandbox.",
        input_schema={
            "type": "object",
            "properties": {"sandbox_id": {"type": "string"}},
            "required": [],
        },
    ),
    ToolDefinition(
        name="inspect_workspace",
        description="Inspect the generated app workspace for a run. Returns the file tree (paths only) so you can decide what to read or patch.",
        input_schema={
            "type": "object",
            "properties": {"app_artifact_id": {"type": "string"}},
            "required": [],
        },
    ),
    ToolDefinition(
        name="read_workspace_file",
        description="Read a single file from the generated app workspace. The path is relative to the app root and must live under a writable root (app, components, hooks, lib, types, public).",
        input_schema={
            "type": "object",
            "properties": {
                "app_artifact_id": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="apply_workspace_patch",
        description="Apply a bounded safe patch to the current generated app. Each logical edit should be its own patch so revisions stay granular. Paths are relative to the app root under a writable root.",
        input_schema={
            "type": "object",
            "properties": {
                "app_artifact_id": {"type": "string"},
                "summary": {"type": "string"},
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "operation": {"enum": ["create", "replace", "delete"]},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "operation"],
                    },
                },
            },
            "required": ["summary", "files"],
        },
    ),
    ToolDefinition(
        name="run_checks",
        description="Run typecheck and lint on the generated app and report the result, without a full product re-verification.",
        input_schema={
            "type": "object",
            "properties": {"app_artifact_id": {"type": "string"}},
            "required": [],
        },
    ),
    ToolDefinition(
        name="finish",
        description="Signal that the orchestration is complete. Provide a final summary.",
        input_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    ),
]


# ===== Tool Context =====

class ToolContext:
    """Context passed to each tool handler."""

    def __init__(
        self,
        run_id: str,
        storage: Storage,
        llm: LLMClient,
        emit: EventEmitter,
        sandbox_manager: Any | None = None,
        task_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.storage = storage
        self.llm = llm
        self.emit = emit
        self.task_id = task_id
        self._sandbox_manager: Any | None = sandbox_manager

    def progress(self, task_id: str | None = None) -> "ProgressReporter":
        from paperforge.orchestrator.progress import ProgressReporter

        return ProgressReporter(
            run_id=self.run_id,
            task_id=task_id or self.task_id or "current",
            storage=self.storage,
            emit=self.emit,
        )

    def get_sandbox_manager(self) -> Any:
        """Return one manager for all sandbox operations in this run."""
        if self._sandbox_manager is None:
            from paperforge.sandbox.docker_runner import DockerSandboxManager

            self._sandbox_manager = DockerSandboxManager(storage=self.storage)
        return self._sandbox_manager


async def _finalize_verification_runtime(
    ctx: ToolContext,
    sandbox: dict[str, Any],
    *,
    runtime_ok: bool,
    runtime_error: str | None = None,
) -> dict[str, Any] | None:
    """Persist runtime and browser acceptance results on the latest report."""
    report_rows = ctx.storage.list_artifacts(
        run_id=ctx.run_id,
        artifact_type="verification_report",
    )
    if not report_rows:
        return None

    artifact = ctx.storage.get_artifact(report_rows[0]["id"])
    if not artifact:
        return None
    report = artifact.get("data") or {}
    layers = report.get("layers") or []
    runtime_layer = next((layer for layer in layers if layer.get("id") == "runtime"), None)
    if runtime_layer is None:
        runtime_layer = {"id": "runtime", "name": "Runtime readiness"}
        layers.append(runtime_layer)
    runtime_layer.update(
        {
            "status": "passed" if runtime_ok else "failed",
            "preview_url": _preview_url_for_sandbox(ctx, sandbox.get("id") or "")
            if runtime_ok and sandbox.get("id")
            else None,
            "reason": runtime_error or "Preview server responded successfully.",
        }
    )
    report["layers"] = layers
    report["runtime_status"] = "passed" if runtime_ok else "failed"

    prd: dict[str, Any] | None = None
    if report.get("prd_id"):
        prd_artifact = ctx.storage.get_artifact(report["prd_id"])
        prd = (prd_artifact or {}).get("data") or None

    smoke: dict[str, Any]
    if runtime_ok and sandbox.get("preview_port"):
        from paperforge.agents.browser_smoke import run_browser_smoke

        try:
            smoke = await run_browser_smoke(
                f"http://127.0.0.1:{sandbox['preview_port']}/",
                prd,
                ctx.storage.reports_dir / "browser_smoke" / ctx.run_id,
            )
        except Exception as exc:
            smoke = {
                "status": "failed",
                "checks": [],
                "console_errors": [],
                "failed_requests": [],
                "reason": str(exc),
            }
    else:
        smoke = {
            "status": "skipped",
            "checks": [],
            "console_errors": [],
            "failed_requests": [],
            "reason": runtime_error or "Preview was not ready.",
        }

    acceptance_layer = next(
        (layer for layer in layers if layer.get("id") == "acceptance"),
        None,
    )
    if acceptance_layer is None:
        acceptance_layer = {"id": "acceptance", "name": "Product acceptance"}
        layers.append(acceptance_layer)
    missing_features = report.get("missing_features") or []
    if missing_features:
        acceptance_status = "failed"
    elif smoke["status"] == "passed":
        acceptance_status = "passed"
    elif smoke["status"] == "failed":
        acceptance_status = "failed"
    else:
        acceptance_status = "pending"
    acceptance_layer.update(
        {
            "status": acceptance_status,
            "browser_smoke": smoke,
            "missing_features": missing_features,
        }
    )
    report["layers"] = layers
    report["acceptance_status"] = acceptance_status
    report["browser_smoke"] = smoke
    updated = ctx.storage.update_artifact(artifact["id"], data=report)
    if updated:
        await ctx.emit.artifact_updated(artifact["id"], report)
    return report


# ===== Dispatcher =====

async def dispatch_tool(
    name: str,
    args: dict[str, Any],
    ctx: ToolContext,
) -> str:
    """Dispatch a tool call to the appropriate handler. Returns the result as a JSON string."""
    handlers = {
        "parse_paper": handle_parse_paper,
        "compose_capabilities": handle_compose,
        "plan_product": handle_plan_product,
        "generate_nextjs_app": handle_generate,
        "verify_app": handle_verify,
        "build_and_repair": handle_build_and_repair,
        "repair_app": handle_repair,
        "run_in_sandbox": handle_run_sandbox,
        "stop_sandbox": handle_stop_sandbox,
        "restart_sandbox": handle_restart_sandbox,
        "inspect_workspace": handle_inspect_workspace,
        "read_workspace_file": handle_read_workspace_file,
        "apply_workspace_patch": handle_apply_workspace_patch,
        "run_checks": handle_run_checks,
        "finish": handle_finish,
    }

    handler = handlers.get(name)
    if not handler:
        result = ToolResult(
            ok=False,
            tool=name,
            error=f"Unknown tool: {name}",
            code="unknown_tool",
        )
        return result.model_dump_json()

    try:
        result = await handler(args, ctx)
        if isinstance(result, ToolResult):
            return result.model_dump_json()
        if isinstance(result, dict | list):
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)
    except Exception as e:
        result = ToolResult(
            ok=False,
            tool=name,
            error=str(e),
            code="tool_exception",
            retryable=True,
        )
        return result.model_dump_json()


# ===== Tool Handlers =====

def _resolve_app_path(args: dict[str, Any], ctx: ToolContext) -> str:
    """Resolve an app artifact to its server-owned workspace path.

    ``app_path`` remains a compatibility input for trusted internal callers;
    LLM-facing calls should pass ``app_artifact_id`` so ownership is checked.
    """
    artifact_id = args.get("app_artifact_id")
    if artifact_id:
        artifact = ctx.storage.get_artifact(artifact_id)
        if not artifact:
            raise ValueError(f"App artifact not found: {artifact_id}")
        if artifact.get("type") != "nextjs_app":
            raise ValueError(f"Artifact is not a Next.js app: {artifact_id}")
        if artifact.get("run_id") != ctx.run_id:
            raise PermissionError("App artifact does not belong to this run")
        metadata = artifact.get("metadata") or {}
        data = artifact.get("data") or {}
        app_path = metadata.get("app_path") or data.get("app_path")
        if not app_path:
            raise ValueError(f"App artifact has no workspace path: {artifact_id}")
        resolved = Path(app_path).resolve()
        try:
            resolved.relative_to(ctx.storage.apps_dir.resolve())
        except (ValueError, RuntimeError) as exc:
            raise PermissionError("App path is outside the server workspace") from exc
        if resolved == ctx.storage.apps_dir.resolve():
            raise PermissionError("App path must name a generated app workspace")
        if not resolved.exists() or not resolved.is_dir():
            raise FileNotFoundError(f"App path not found: {resolved}")
        return str(resolved)

    app_path = args.get("app_path")
    if not app_path:
        raise ValueError("Either app_artifact_id or app_path must be provided")
    resolved = Path(app_path).resolve()
    try:
        resolved.relative_to(ctx.storage.apps_dir.resolve())
    except (ValueError, RuntimeError) as exc:
        raise PermissionError("App path is outside the server workspace") from exc
    if resolved == ctx.storage.apps_dir.resolve():
        raise PermissionError("App path must name a generated app workspace")
    owned = False
    for artifact in ctx.storage.list_artifacts(run_id=ctx.run_id, artifact_type="nextjs_app"):
        metadata = artifact.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        if Path(metadata.get("app_path", "")).resolve() == resolved:
            owned = True
            break
    if not owned:
        raise PermissionError("App path does not belong to this run")
    if not resolved.exists() or not resolved.is_dir():
        raise FileNotFoundError(f"App path not found: {resolved}")
    return str(resolved)

async def handle_parse_paper(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Parse a PDF and extract a capability card.

    Accepts either `paper_id` (preferred — Storage resolves pdf_path) or
    `pdf_path` (legacy). The LLM should never construct server paths.
    """
    from paperforge.agents.paper_parser import parse_paper

    paper_id = args.get("paper_id")
    pdf_path = args.get("pdf_path")

    progress = ctx.progress()
    step_id = await progress.start(kind="paper_parse", title="Parsing paper")
    try:
        if paper_id:
            # Preferred path: look the paper up in the library to resolve pdf_path.
            paper = ctx.storage.get_paper(paper_id)
            if paper is not None and not pdf_path:
                pdf_path = paper.get("pdf_path")
        elif pdf_path:
            paper_id = Path(pdf_path).stem
        else:
            await progress.fail(step_id, error="Either paper_id or pdf_path must be provided.")
            return ToolResult(
                ok=False,
                tool="parse_paper",
                error="Either paper_id or pdf_path must be provided.",
            )

        card = await parse_paper(pdf_path=pdf_path, paper_id=paper_id, llm=ctx.llm)
        await progress.complete(step_id, summary="Paper parsed into capability card.")
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise

    card_data = card if isinstance(card, dict) else card
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="capability_card",
        data=card_data,
        task_id=ctx.task_id,
    )
    card_path = str(ctx.storage.library_dir / f"{artifact_id}.json")

    # Persist card_path on the paper row so composer/planner can find it.
    paper = ctx.storage.get_paper(paper_id)
    if paper is None:
        ctx.storage.upsert_paper(
            paper_id=paper_id,
            title=paper_id,
            pdf_path=pdf_path,
            card_path=card_path,
            status="parsed",
        )
    else:
        ctx.storage.update_paper_status(paper_id, "parsed", card_path=card_path)

    await ctx.emit.artifact_created("capability_card", str(ctx.storage.library_dir), artifact_id)

    return ToolResult(
        ok=True,
        tool="parse_paper",
        artifact_id=artifact_id,
        data={"card_id": paper_id, "card": card_data},
        summary=f"Parsed paper '{paper_id}' into capability card.",
        next_phase="parsed",
    )


async def handle_compose(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Compose multiple capability cards into novel product concepts."""
    from paperforge.agents.composer import compose

    card_ids = args["card_ids"]
    progress = ctx.progress()
    step_id = await progress.start(kind="planning", title="Composing capabilities")
    try:
        composition = await compose(card_ids=card_ids, llm=ctx.llm, storage=ctx.storage)
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise
    await progress.complete(step_id, summary=f"Composed {len(card_ids)} capability cards.")

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="composition",
        data=composition,
        task_id=ctx.task_id,
    )
    await ctx.emit.artifact_created("composition", str(ctx.storage.compositions_dir), artifact_id)

    return ToolResult(
        ok=True,
        tool="compose_capabilities",
        artifact_id=artifact_id,
        data={
            "composition_id": composition.get("composition_id"),
            "composition": composition,
        },
        summary=f"Composed {len(card_ids)} capability cards into product candidates.",
        next_phase="composed",
    )


async def handle_plan_product(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Refine composition into a PRD, or surface clarifying questions.

    The planner returns a PlannerOutput wrapper:
      - needs_more_input=True: questions are surfaced back to the LLM/user
        and no PRD artifact is saved. Tool returns BLOCKED so the orchestrator
        does not advance phase.
      - needs_more_input=False: a PRD is saved as an artifact.
    """
    from paperforge.agents.product_planner import plan_product

    composition_id = args.get("composition_id")
    card_ids = args.get("card_ids")
    user_requirement = args["user_requirement"]

    if not composition_id and not card_ids:
        return ToolResult(
            tool="plan_product",
            status=ToolStatus.FAILED,
            error="Either composition_id or card_ids must be provided.",
        )

    progress = ctx.progress()
    step_id = await progress.start(kind="planning", title="Planning product")
    try:
        planner_output = await plan_product(
            user_requirement=user_requirement,
            llm=ctx.llm,
            storage=ctx.storage,
            composition_id=composition_id,
            card_ids=card_ids,
        )
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise

    if planner_output.get("needs_more_input"):
        await progress.complete(step_id, summary="Asked user for more input.")
        questions = planner_output.get("questions") or []
        return ToolResult(
            tool="plan_product",
            status=ToolStatus.BLOCKED,
            code="needs_user_input",
            data={"questions": questions},
            summary="Need more input from user before generating PRD.",
            stop_loop=True,
        )

    prd = planner_output.get("prd") or {}
    await progress.complete(step_id, summary="PRD generated.")
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="prd",
        data=prd,
        task_id=ctx.task_id,
    )
    await ctx.emit.artifact_created("prd", str(ctx.storage.prds_dir), artifact_id)

    return ToolResult(
        tool="plan_product",
        status=ToolStatus.SUCCEEDED,
        artifact_id=artifact_id,
        data={"prd_id": prd.get("prd_id"), "prd": prd},
        summary=f"Generated PRD from composition {composition_id}.",
        next_phase="planned",
    )


async def handle_generate(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Generate a Next.js app from a PRD."""
    from paperforge.agents.nextjs_generator import generate_nextjs_app

    prd_id = args["prd_id"]
    progress = ctx.progress()
    step_id = await progress.start(kind="codegen", title="Generating Next.js app")
    requested_output = args.get("output_dir")
    if requested_output:
        requested_path = Path(requested_output).resolve()
        try:
            requested_path.relative_to(ctx.storage.apps_dir.resolve())
        except ValueError as exc:
            raise ValueError("output_dir must be inside the server app workspace") from exc
        if requested_path == ctx.storage.apps_dir.resolve():
            raise ValueError("output_dir must name a child app directory")
        output_dir = str(requested_path)
    else:
        output_dir = str(ctx.storage.apps_dir / f"app_{uuid.uuid4().hex[:6]}")

    try:
        manifest = await generate_nextjs_app(
            prd_id=prd_id,
            output_dir=output_dir,
            llm=ctx.llm,
            storage=ctx.storage,
        )
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise
    await progress.complete(step_id, summary=f"App generated at {output_dir}.")

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="nextjs_app",
        data=manifest,
        metadata={"app_path": output_dir},
        task_id=ctx.task_id,
    )
    revision = ctx.storage.create_workspace_revision(
        run_id=ctx.run_id,
        app_id=artifact_id,
        source="generator",
        app_path=output_dir,
    )
    await ctx.emit.artifact_created("nextjs_app", output_dir, artifact_id)

    return ToolResult(
        ok=True,
        tool="generate_nextjs_app",
        artifact_id=artifact_id,
        data={
            "app_id": manifest.get("app_id"),
            "app_path": output_dir,
            "manifest": manifest,
            "revision_id": revision["id"],
        },
        summary=f"Generated Next.js app at {output_dir}.",
        next_phase="generated",
    )

async def handle_verify(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Verify a generated Next.js app, running the full build/lint/typecheck."""
    from paperforge.agents.verifier import verify_app

    app_path = _resolve_app_path(args, ctx)
    prd_id = args.get("prd_id")

    progress = ctx.progress()
    step_id = await progress.start(kind="test", title="Verifying app")
    try:
        report = await verify_app(
            app_path=app_path,
            prd_id=prd_id,
            llm=ctx.llm,
            storage=ctx.storage,
        )
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise

    ready = bool(report.get("ready_for_preview"))
    await progress.complete(
        step_id,
        summary=f"Score={report.get('overall_score', 0):.2f}, "
                f"ready={ready}.",
    )
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="verification_report",
        data=report,
        task_id=ctx.task_id,
    )
    await ctx.emit.artifact_created("verification_report", str(ctx.storage.reports_dir), artifact_id)

    ready = bool(report.get("ready_for_preview"))
    return ToolResult(
        tool="verify_app",
        status=ToolStatus.SUCCEEDED if ready else ToolStatus.FAILED,
        artifact_id=artifact_id,
        data={"report": report},
        summary=f"Verified app: score={report.get('overall_score', 0):.2f}, "
                f"ready={report.get('ready_for_preview', False)}.",
        next_phase="verified" if ready else None,
    )


async def handle_build_and_repair(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Run bounded verification/repair and keep failed work recoverable."""
    from paperforge.agents.verifier import build_and_repair

    app_path = _resolve_app_path(args, ctx)
    progress = ctx.progress()
    step_id = await progress.start(kind="build", title="Build and repair")
    try:
        report = await build_and_repair(
            app_path=app_path,
            prd_id=args.get("prd_id"),
            llm=ctx.llm,
            storage=ctx.storage,
            max_attempts=min(max(int(args.get("max_attempts", 3)), 1), 3),
        )
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise
    ready = bool(report.get("ready_for_preview"))
    await progress.complete(step_id, summary="Build and repair complete." if ready else "Build and repair needs another iteration.")
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="verification_report",
        data=report,
        metadata={"app_path": app_path, "workflow": "build_and_repair"},
        task_id=ctx.task_id,
    )
    await ctx.emit.artifact_created(
        "verification_report",
        str(ctx.storage.reports_dir),
        artifact_id,
    )
    app_artifact_id = args.get("app_artifact_id")
    revision_id = None
    if app_artifact_id:
        revision = ctx.storage.create_workspace_revision(
            run_id=ctx.run_id,
            app_id=app_artifact_id,
            source="repair",
            app_path=app_path,
        )
        revision_id = revision["id"]
    ready = bool(report.get("ready_for_preview"))
    return ToolResult(
        tool="build_and_repair",
        status=ToolStatus.SUCCEEDED if ready else ToolStatus.FAILED,
        artifact_id=artifact_id,
        data={"report": report, "revision_id": revision_id},
        summary="Build and repair completed." if ready else "Build and repair needs another iteration.",
        code=None if ready else "verification_failed",
        retryable=not ready,
        next_phase="verified" if ready else None,
    )


async def handle_repair(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Compatibility name used by the product workflow specification."""
    result = await handle_build_and_repair(args, ctx)
    return result.model_copy(update={"tool": "repair_app"})


async def handle_run_sandbox(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Launch a generated app in a Docker sandbox."""
    app_path = _resolve_app_path(args, ctx)
    run_id = args.get("run_id", ctx.run_id)
    if run_id != ctx.run_id:
        return ToolResult(
            tool="run_in_sandbox",
            status=ToolStatus.FAILED,
            error="Sandbox run_id must match the current run",
            code="run_ownership_mismatch",
        )

    manager = ctx.get_sandbox_manager()
    if manager is None:
        return ToolResult(
            tool="run_in_sandbox",
            status=ToolStatus.FAILED,
            error="Docker sandbox is unavailable",
            code="sandbox_unavailable",
            retryable=True,
        )
    progress = ctx.progress()
    step_id = await progress.start(kind="preview", title="Starting preview")
    try:
        sandbox = await manager.start(run_id=run_id, app_path=app_path)
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        raise

    if sandbox.get("status") != "running":
        ctx.storage.update_sandbox(
            sandbox["id"],
            preview_status="degraded",
            error=sandbox.get("error") or "Sandbox failed to start",
        )
        await progress.fail(step_id, error=sandbox.get("error") or "Sandbox failed to start")
        await ctx.emit.sandbox_error(
            sandbox.get("error") or "Sandbox failed to start"
        )
        await _finalize_verification_runtime(
            ctx,
            sandbox,
            runtime_ok=False,
            runtime_error=sandbox.get("error") or "Sandbox failed to start",
        )
        return ToolResult(
            tool="run_in_sandbox",
            status=ToolStatus.FAILED,
            error=sandbox.get("error") or "Sandbox did not enter running state",
            code="sandbox_unavailable",
            data={"sandbox": sandbox, "environment": "docker"},
            retryable=True,
        )

    await ctx.emit.sandbox_started(sandbox["id"], sandbox.get("container_id", ""), sandbox.get("preview_port", 0))
    ctx.storage.update_sandbox(
        sandbox["id"],
        preview_status="starting",
        error=None,
    )

    # Wait for the Next.js dev server to be ready before emitting preview.ready
    ready = await manager.wait_for_ready(sandbox["id"], timeout=60)
    if not ready:
        ctx.storage.update_sandbox(
            sandbox["id"],
            preview_status="degraded",
            error="Preview server did not become HTTP-ready within 60 seconds",
        )
        await progress.fail(step_id, error="Preview server did not become HTTP-ready within 60 seconds")
        await ctx.emit.sandbox_error(f"Sandbox {sandbox['id']} failed health check within 60s")
        await _finalize_verification_runtime(
            ctx,
            sandbox,
            runtime_ok=False,
            runtime_error="Preview server did not become HTTP-ready within 60 seconds",
        )
        return ToolResult(
            tool="run_in_sandbox",
            status=ToolStatus.FAILED,
            error="Preview server did not become HTTP-ready within 60 seconds",
            code="preview_not_ready",
            data={"sandbox_id": sandbox["id"], "environment": "docker"},
            retryable=True,
        )

    preview_url = _preview_url_for_sandbox(ctx, sandbox["id"])
    ctx.storage.update_sandbox(
        sandbox["id"],
        preview_status="running",
        preview_url=preview_url,
        error=None,
    )
    await progress.complete(step_id, summary=f"Preview ready on port {sandbox.get('preview_port')}.")
    await ctx.emit.preview_ready(sandbox["id"], preview_url)
    report = await _finalize_verification_runtime(ctx, sandbox, runtime_ok=True)
    return ToolResult(
        tool="run_in_sandbox",
        status=ToolStatus.SUCCEEDED,
        data={
            "sandbox_id": sandbox["id"],
            "container_id": sandbox.get("container_id"),
            "preview_port": sandbox.get("preview_port"),
            "preview_url": preview_url,
            "status": sandbox.get("status"),
            "verification": report,
        },
        summary=f"Launched sandbox {sandbox['id']} on port {sandbox.get('preview_port')}.",
        next_phase="preview_ready",
    )


def _preview_url_for_sandbox(ctx, sandbox_id: str) -> str:
    """Build the preview URL, preferring an absolute preview origin so a
    user-generated app never shares an origin with the main app (doc 38)."""
    from paperforge.config import get_config

    origin = get_config().PREVIEW_ORIGIN.rstrip("/")
    if origin:
        return f"{origin}/api/preview/{sandbox_id}/"
    return f"/api/preview/{sandbox_id}/"


async def handle_stop_sandbox(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Stop a running sandbox."""
    sandbox_id = args["sandbox_id"]
    sandbox = ctx.storage.get_sandbox(sandbox_id)
    if not sandbox or sandbox.get("run_id") != ctx.run_id:
        return ToolResult(
            tool="stop_sandbox",
            status=ToolStatus.FAILED,
            error="Sandbox does not belong to this run",
            code="sandbox_not_found",
        )
    manager = ctx.get_sandbox_manager()
    if manager is None:
        return ToolResult(
            tool="stop_sandbox",
            status=ToolStatus.FAILED,
            error="Docker sandbox is unavailable",
            code="sandbox_unavailable",
        )
    await manager.stop(sandbox_id)
    return ToolResult(
        tool="stop_sandbox",
        status=ToolStatus.SUCCEEDED,
        data={"sandbox_id": sandbox_id, "status": "stopped"},
        summary=f"Stopped sandbox {sandbox_id}.",
    )


async def handle_restart_sandbox(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Restart a sandbox and report whether its preview became ready."""
    manager = ctx.get_sandbox_manager()
    sandbox_id = args.get("sandbox_id")
    if not sandbox_id:
        latest = ctx.storage.get_latest_sandbox_for_run(ctx.run_id)
        sandbox_id = latest["id"] if latest else None
    if not sandbox_id:
        return ToolResult(
            tool="restart_sandbox",
            status=ToolStatus.FAILED,
            error="No sandbox exists for this run",
            code="sandbox_not_found",
        )

    existing = ctx.storage.get_sandbox(sandbox_id)
    if not existing or existing.get("run_id") != ctx.run_id:
        return ToolResult(
            tool="restart_sandbox",
            status=ToolStatus.FAILED,
            error="Sandbox does not belong to this run",
            code="sandbox_not_found",
        )
    if manager is None:
        return ToolResult(
            tool="restart_sandbox",
            status=ToolStatus.FAILED,
            error="Docker sandbox is unavailable",
            code="sandbox_unavailable",
        )

    progress = ctx.progress()
    step_id = await progress.start(kind="preview", title="Restarting preview")
    try:
        sandbox = await manager.restart(sandbox_id)
    except Exception as exc:
        await progress.fail(step_id, error=str(exc))
        return ToolResult(
            tool="restart_sandbox",
            status=ToolStatus.FAILED,
            error=str(exc),
            code="sandbox_restart_failed",
            retryable=True,
        )

    if sandbox.get("status") != "running":
        ctx.storage.update_sandbox(
            sandbox["id"],
            preview_status="degraded",
            error=sandbox.get("error") or "Sandbox did not enter running state",
        )
        await progress.fail(step_id, error=sandbox.get("error") or "Sandbox did not enter running state")
        await _finalize_verification_runtime(
            ctx,
            sandbox,
            runtime_ok=False,
            runtime_error=sandbox.get("error") or "Sandbox did not enter running state",
        )
        return ToolResult(
            tool="restart_sandbox",
            status=ToolStatus.FAILED,
            error=sandbox.get("error") or "Sandbox did not enter running state",
            code="sandbox_unavailable",
            data={"sandbox": sandbox},
            retryable=True,
        )

    ready = await manager.wait_for_ready(sandbox["id"], timeout=60)
    if not ready:
        ctx.storage.update_sandbox(
            sandbox["id"],
            preview_status="degraded",
            error="Preview server did not become HTTP-ready after restart",
        )
        await progress.fail(step_id, error="Preview server did not become HTTP-ready after restart")
        await _finalize_verification_runtime(
            ctx,
            sandbox,
            runtime_ok=False,
            runtime_error="Preview server did not become HTTP-ready after restart",
        )
        return ToolResult(
            tool="restart_sandbox",
            status=ToolStatus.FAILED,
            error="Preview server did not become HTTP-ready after restart",
            code="preview_not_ready",
            data={"sandbox": sandbox},
            retryable=True,
        )
    preview_url = _preview_url_for_sandbox(ctx, sandbox["id"])
    ctx.storage.update_sandbox(
        sandbox["id"],
        preview_status="running",
        preview_url=preview_url,
        error=None,
    )
    await progress.complete(step_id, summary="Preview restarted.")
    await ctx.emit.preview_ready(sandbox["id"], preview_url)
    report = await _finalize_verification_runtime(ctx, sandbox, runtime_ok=True)
    return ToolResult(
        tool="restart_sandbox",
        status=ToolStatus.SUCCEEDED,
        data={"sandbox": sandbox, "preview_url": preview_url, "verification": report},
        summary=f"Restarted sandbox {sandbox['id']}.",
        next_phase="preview_ready",
    )


async def handle_finish(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Complete the current task without ending the Run/Thread (doc 5).

    A completed task must not mark the whole Run as done, because the
    Run is a persistent thread that can receive follow-up tasks.
    """
    summary = args.get("summary", "Task completed")
    return ToolResult(
        tool="finish",
        status=ToolStatus.SUCCEEDED,
        data={"summary": summary, "task_status": "completed"},
        summary=summary,
        stop_loop=True,
    )


def _resolve_workspace_root(args: dict[str, Any], ctx: ToolContext) -> Path:
    """Resolve the app workspace root, defaulting app_artifact_id to this run's app."""
    app_path = _resolve_app_path(args, ctx)
    return Path(app_path)


async def handle_inspect_workspace(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """List the generated app workspace tree (paths only)."""
    root = _resolve_workspace_root(args, ctx)
    from paperforge.agents.verifier import collect_files
    files = [p for p, _ in collect_files(root)]
    return ToolResult(
        tool="inspect_workspace",
        status=ToolStatus.SUCCEEDED,
        data={"app_path": str(root), "files": sorted(files)},
        summary=f"Workspace contains {len(files)} files.",
    )


async def handle_read_workspace_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Read a single file from the workspace via the safe policy."""
    from paperforge.schemas.workspace_policy import SafeWorkspacePolicy

    root = _resolve_workspace_root(args, ctx)
    rel = args.get("path") or ""
    try:
        normalized = SafeWorkspacePolicy().normalize(rel)
    except ValueError as exc:
        return ToolResult(
            tool="read_workspace_file",
            status=ToolStatus.FAILED,
            error=str(exc),
            code="unsafe_path",
        )
    target = (root / normalized).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return ToolResult(
            tool="read_workspace_file",
            status=ToolStatus.FAILED,
            error="Path escapes the workspace",
            code="unsafe_path",
        )
    if not target.is_file():
        return ToolResult(
            tool="read_workspace_file",
            status=ToolStatus.FAILED,
            error=f"No such file: {normalized}",
            code="not_found",
        )
    content = target.read_text(encoding="utf-8")
    return ToolResult(
        tool="read_workspace_file",
        status=ToolStatus.SUCCEEDED,
        data={"path": normalized, "content": content},
    )


async def handle_apply_workspace_patch(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Apply a bounded safe patch to the workspace, creating a revision."""
    from paperforge.schemas.workspace_policy import (
        SafeWorkspacePolicy,
        WorkspacePatch,
        apply_workspace_patch,
    )

    root = _resolve_workspace_root(args, ctx)
    patch_data = args.get("files") or []
    if not patch_data:
        return ToolResult(
            tool="apply_workspace_patch",
            status=ToolStatus.FAILED,
            error="No files in patch",
            code="empty_patch",
        )
    patch = WorkspacePatch(
        summary=args.get("summary", "Workspace patch"),
        files=patch_data,
    )
    progress = ctx.progress()
    step_id = await progress.start(kind="codegen", title="Applying workspace patch")
    try:
        changed = apply_workspace_patch(root, patch, SafeWorkspacePolicy())
    except ValueError as exc:
        await progress.fail(step_id, error=str(exc))
        return ToolResult(
            tool="apply_workspace_patch",
            status=ToolStatus.FAILED,
            error=str(exc),
            code="patch_rejected",
        )
    await progress.complete(step_id, summary=f"{len(changed)} files changed.")

    artifact_id = _latest_app_artifact_id(ctx)
    revision_id = None
    if artifact_id:
        revision = ctx.storage.create_workspace_revision(
            run_id=ctx.run_id,
            app_id=artifact_id,
            source="patch",
            app_path=str(root),
        )
        revision_id = revision["id"]
    return ToolResult(
        tool="apply_workspace_patch",
        status=ToolStatus.SUCCEEDED,
        data={"changed": changed, "revision_id": revision_id},
        summary=f"Applied patch: {len(changed)} files changed.",
        next_phase="generated",
    )


async def handle_run_checks(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Run typecheck + lint on the workspace and report pass/fail."""
    root = _resolve_workspace_root(args, ctx)
    from paperforge.agents.verifier import _run_checks_streaming, TYPECHECK_TIMEOUT

    progress = ctx.progress()
    step_id = await progress.start(kind="test", title="Running checks")
    ok, errors = await _run_checks_streaming(
        root, TYPECHECK_TIMEOUT, progress, step_id
    )
    await progress.complete(step_id, summary="Checks pass." if ok else "Checks failed.")
    return ToolResult(
        tool="run_checks",
        status=ToolStatus.SUCCEEDED if ok else ToolStatus.FAILED,
        data={"ok": ok, "errors": errors[:40]},
        summary="Typecheck and lint pass." if ok else "Typecheck / lint failed.",
        retryable=not ok,
    )


def _latest_app_artifact_id(ctx: ToolContext) -> str | None:
    for artifact in ctx.storage.list_artifacts(
        run_id=ctx.run_id, artifact_type="nextjs_app"
    ):
        return artifact["id"]
    return None
