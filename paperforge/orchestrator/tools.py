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
from paperforge.storage.db import Storage


# ===== Tool Definitions =====

TOOL_DEFINITIONS = [
    ToolDefinition(
        name="parse_paper",
        description="Parse a PDF and extract a capability card. Returns card_id and card JSON.",
        input_schema={
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Path to the PDF file"},
                "paper_id": {"type": "string", "description": "Optional paper ID"},
            },
            "required": ["pdf_path"],
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
        description="Refine composition into a PRD. Returns PRD JSON.",
        input_schema={
            "type": "object",
            "properties": {
                "composition_id": {"type": "string"},
                "user_requirement": {"type": "string"},
            },
            "required": ["composition_id", "user_requirement"],
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
        name="read_file",
        description="Read a file from the project workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    ToolDefinition(
        name="write_file",
        description="Write content to a file in the project workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
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
        "read_file": handle_read_file,
        "write_file": handle_write_file,
        "finish": handle_finish,
    }

    handler = handlers.get(name)
    if not handler:
        result = {"error": f"Unknown tool: {name}"}
        return json.dumps(result, ensure_ascii=False)

    try:
        result = await handler(args, ctx)
        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=False, default=str)
        return str(result)
    except Exception as e:
        return json.dumps({"error": str(e), "tool": name}, ensure_ascii=False)


# ===== Tool Handlers =====

async def handle_parse_paper(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Parse a PDF and extract a capability card."""
    from paperforge.agents.paper_parser import parse_paper

    pdf_path = args["pdf_path"]
    paper_id = args.get("paper_id") or Path(pdf_path).stem

    card = await parse_paper(pdf_path=pdf_path, paper_id=paper_id, llm=ctx.llm)

    card_data = card if isinstance(card, dict) else card
    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="capability_card",
        data=card_data,
    )

    await ctx.emit.artifact_created("capability_card", str(ctx.storage.library_dir), artifact_id)

    return {
        "card_id": paper_id,
        "artifact_id": artifact_id,
        "card": card_data,
    }


async def handle_compose(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Compose multiple capability cards into novel product concepts."""
    from paperforge.agents.composer import compose

    card_ids = args["card_ids"]
    composition = await compose(card_ids=card_ids, llm=ctx.llm, storage=ctx.storage)

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="composition",
        data=composition,
    )

    return {"composition_id": composition.get("composition_id"), "composition": composition, "artifact_id": artifact_id}


async def handle_plan_product(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Refine composition into a PRD."""
    from paperforge.agents.product_planner import plan_product

    composition_id = args["composition_id"]
    user_requirement = args["user_requirement"]

    prd = await plan_product(
        composition_id=composition_id,
        user_requirement=user_requirement,
        llm=ctx.llm,
        storage=ctx.storage,
    )

    artifact_id = ctx.storage.save_artifact(
        run_id=ctx.run_id,
        artifact_type="prd",
        data=prd,
    )

    return {"prd_id": prd.get("prd_id"), "prd": prd, "artifact_id": artifact_id}


async def handle_generate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
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

    return {
        "app_id": manifest.get("app_id"),
        "app_path": output_dir,
        "artifact_id": artifact_id,
        "manifest": manifest,
    }


async def handle_verify(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
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

    return {"report": report, "artifact_id": artifact_id}


async def handle_run_sandbox(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Launch a generated app in a Docker sandbox."""
    from paperforge.sandbox.docker_runner import DockerSandboxManager

    app_path = args["app_path"]
    run_id = args.get("run_id", ctx.run_id)

    manager = DockerSandboxManager(storage=ctx.storage)
    sandbox = await manager.start(run_id=run_id, app_path=app_path)

    await ctx.emit.sandbox_started(sandbox["id"], sandbox.get("container_id", ""), sandbox.get("preview_port", 0))

    preview_url = f"/api/preview/{sandbox['id']}/"
    await ctx.emit.preview_ready(sandbox["id"], preview_url)

    return {
        "sandbox_id": sandbox["id"],
        "container_id": sandbox.get("container_id"),
        "preview_port": sandbox.get("preview_port"),
        "preview_url": preview_url,
        "status": sandbox.get("status"),
    }


async def handle_stop_sandbox(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Stop a running sandbox."""
    from paperforge.sandbox.docker_runner import DockerSandboxManager

    sandbox_id = args["sandbox_id"]
    manager = DockerSandboxManager(storage=ctx.storage)
    await manager.stop(sandbox_id)
    return {"sandbox_id": sandbox_id, "status": "stopped"}


async def handle_read_file(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Read a file from the workspace."""
    path = Path(args["path"])
    if not path.is_absolute():
        path = Path(get_config().DATA_DIR) / path

    if not path.exists():
        return {"error": f"File not found: {path}"}
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


async def handle_write_file(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Write content to a file in the workspace."""
    path = Path(args["path"])
    content = args["content"]

    if not path.is_absolute():
        path = Path(get_config().DATA_DIR) / path

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "saved": True}


async def handle_finish(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Signal that the orchestration is complete."""
    summary = args.get("summary", "Task completed")
    return {"summary": summary, "status": "done"}
