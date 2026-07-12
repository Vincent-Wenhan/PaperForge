"""Tool definitions and dispatcher for the orchestrator.

Each sub-agent is registered as a tool. The orchestrator's main loop calls
`dispatch_tool` when the LLM returns a tool_call.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from paperforge.config import get_config
from paperforge.llm.base import LLMClient, Message, ToolCall, ToolDefinition
from paperforge.orchestrator.events import EventEmitter
from paperforge.schemas.tool_result import ToolResult
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
        description="Verify a generated Next.js app builds and matches the PRD.",
        input_schema={
            "type": "object",
            "properties": {
                "app_path": {"type": "string"},
                "prd_id": {"type": "string"},
            },
            "required": ["app_path"],
        },
    ),
    ToolDefinition(
        name="run_in_sandbox",
        description="Launch a generated app in a Docker sandbox for live preview.",
        input_schema={
            "type": "object",
            "properties": {
                "app_path": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["app_path"],
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
    ) -> None:
        self.run_id = run_id
        self.storage = storage
        self.llm = llm
        self.emit = emit


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
        "run_in_sandbox": handle_run_sandbox,
        "stop_sandbox": handle_stop_sandbox,
        "finish": handle_finish,
    }

    handler = handlers.get(name)
    if not handler:
        result = ToolResult(ok=False, tool=name, error=f"Unknown tool: {name}")
        return result.model_dump_json()

    try:
        result = await handler(args, ctx)
        if isinstance(result, ToolResult):
            return result.model_dump_json()
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)
    except Exception as e:
        result = ToolResult(ok=False, tool=name, error=str(e))
        return result.model_dump_json()


# ===== Tool Handlers =====

async def handle_parse_paper(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Parse a PDF and extract a capability card.

    Accepts either `paper_id` (preferred — Storage resolves pdf_path) or
    `pdf_path` (legacy). The LLM should never construct server paths.
    """
    from paperforge.agents.paper_parser import parse_paper

    paper_id = args.get("paper_id")
    pdf_path = args.get("pdf_path")

    if paper_id:
        # Preferred path: look the paper up in the library to resolve pdf_path.
        paper = ctx.storage.get_paper(paper_id)
        if paper is not None and not pdf_path:
            pdf_path = paper.get("pdf_path")
    elif pdf_path:
        paper_id = Path(pdf_path).stem
    else:
        return ToolResult(
            ok=False,
            tool="parse_paper",
            error="Either paper_id or pdf_path must be provided.",
        )

    card = await parse_paper(pdf_path=pdf_path, paper_id=paper_id, llm=ctx.llm)

    card_data = card if isinstance(card, dict) else card
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="capability_card",
        data=card_data,
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
    )


async def handle_compose(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Compose multiple capability cards into novel product concepts."""
    from paperforge.agents.composer import compose

    card_ids = args["card_ids"]
    composition = await compose(card_ids=card_ids, llm=ctx.llm, storage=ctx.storage)

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="composition",
        data=composition,
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
    )


async def handle_plan_product(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Refine composition into a PRD, or surface clarifying questions.

    The planner returns a PlannerOutput wrapper:
      - needs_more_input=True: questions are surfaced back to the LLM/user
        and no PRD artifact is saved.
      - needs_more_input=False: a PRD is saved as an artifact.
    """
    from paperforge.agents.product_planner import plan_product

    composition_id = args.get("composition_id")
    card_ids = args.get("card_ids")
    user_requirement = args["user_requirement"]

    if not composition_id and not card_ids:
        return ToolResult(
            ok=False,
            tool="plan_product",
            error="Either composition_id or card_ids must be provided.",
        )

    planner_output = await plan_product(
        user_requirement=user_requirement,
        llm=ctx.llm,
        storage=ctx.storage,
        composition_id=composition_id,
        card_ids=card_ids,
    )

    if planner_output.get("needs_more_input"):
        questions = planner_output.get("questions") or []
        return ToolResult(
            ok=True,
            tool="plan_product",
            data={
                "needs_more_input": True,
                "questions": questions,
            },
            summary="Need more input from user before generating PRD.",
        )

    prd = planner_output.get("prd") or {}
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="prd",
        data=prd,
    )
    await ctx.emit.artifact_created("prd", str(ctx.storage.prds_dir), artifact_id)

    return ToolResult(
        ok=True,
        tool="plan_product",
        artifact_id=artifact_id,
        data={"prd_id": prd.get("prd_id"), "prd": prd},
        summary=f"Generated PRD from composition {composition_id}.",
    )


async def handle_generate(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Generate a Next.js app from a PRD."""
    from paperforge.agents.nextjs_generator import generate_nextjs_app

    prd_id = args["prd_id"]
    output_dir = args.get("output_dir") or str(ctx.storage.apps_dir / f"app_{uuid.uuid4().hex[:6]}")

    manifest = await generate_nextjs_app(
        prd_id=prd_id,
        output_dir=output_dir,
        llm=ctx.llm,
        storage=ctx.storage,
    )

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="nextjs_app",
        data=manifest,
        metadata={"app_path": output_dir},
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
        },
        summary=f"Generated Next.js app at {output_dir}.",
    )


async def handle_verify(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Verify a generated Next.js app."""
    from paperforge.agents.verifier import verify_app

    app_path = args["app_path"]
    prd_id = args.get("prd_id")

    report = await verify_app(
        app_path=app_path,
        prd_id=prd_id,
        llm=ctx.llm,
        storage=ctx.storage,
    )

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="verification_report",
        data=report,
    )
    await ctx.emit.artifact_created("verification_report", str(ctx.storage.reports_dir), artifact_id)

    return ToolResult(
        ok=True,
        tool="verify_app",
        artifact_id=artifact_id,
        data={"report": report},
        summary=f"Verified app: score={report.get('overall_score', 0):.2f}, "
                f"ready={report.get('ready_for_preview', False)}.",
    )


async def handle_run_sandbox(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Launch a generated app in a Docker sandbox."""
    from paperforge.sandbox.docker_runner import DockerSandboxManager

    app_path = args["app_path"]
    run_id = args.get("run_id", ctx.run_id)

    manager = DockerSandboxManager(storage=ctx.storage)
    try:
        sandbox = await manager.start(run_id=run_id, app_path=app_path)
    except Exception as e:
        await ctx.emit.sandbox_error(str(e))
        return ToolResult(
            ok=False,
            tool="run_in_sandbox",
            error=str(e),
        )

    await ctx.emit.sandbox_started(sandbox["id"], sandbox.get("container_id", ""), sandbox.get("preview_port", 0))

    # Wait for the Next.js dev server to be ready before emitting preview.ready
    ready = await manager.wait_for_ready(sandbox["id"], timeout=60)
    if ready:
        preview_url = f"/api/preview/{sandbox['id']}/"
        await ctx.emit.preview_ready(sandbox["id"], preview_url)
    else:
        await ctx.emit.sandbox_error(f"Sandbox {sandbox['id']} failed health check within 60s")

    return ToolResult(
        ok=True,
        tool="run_in_sandbox",
        data={
            "sandbox_id": sandbox["id"],
            "container_id": sandbox.get("container_id"),
            "preview_port": sandbox.get("preview_port"),
            "preview_url": preview_url if ready else None,
            "status": sandbox.get("status"),
        },
        summary=f"Launched sandbox {sandbox['id']} on port {sandbox.get('preview_port')}.",
    )


async def handle_stop_sandbox(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Stop a running sandbox."""
    from paperforge.sandbox.docker_runner import DockerSandboxManager

    sandbox_id = args["sandbox_id"]
    manager = DockerSandboxManager(storage=ctx.storage)
    await manager.stop(sandbox_id)
    return ToolResult(
        ok=True,
        tool="stop_sandbox",
        data={"sandbox_id": sandbox_id, "status": "stopped"},
        summary=f"Stopped sandbox {sandbox_id}.",
    )


async def handle_finish(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """Signal that the orchestration is complete."""
    summary = args.get("summary", "Task completed")
    return ToolResult(
        ok=True,
        tool="finish",
        data={"summary": summary, "status": "done"},
        summary=summary,
    )
