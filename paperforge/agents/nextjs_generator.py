"""NextjsGenerator: PRD → Next.js app files.

Strategy:
1. Call LLM with generator prompt + PRD JSON
2. Parse response as AppManifest
3. Write each file to output_dir
4. Return manifest
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)


async def generate_nextjs_app(
    prd_id: str,
    output_dir: str | Path,
    llm: LLMClient,
    storage: Storage,
) -> dict[str, Any]:
    """Generate a Next.js app from a PRD.

    Args:
        prd_id: ID of the PRD artifact
        output_dir: where to write the generated app files
        llm: LLM client
        storage: storage instance

    Returns:
        App manifest dict
    """
    artifact = storage.get_artifact(prd_id)
    if not artifact:
        raise ValueError(f"PRD not found: {prd_id}")

    prd = artifact.get("data") or {}

    app_id = f"app_{uuid.uuid4().hex[:8]}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = load_prompt("nextjs_generator")
    user_content = (
        f"App ID: {app_id}\n"
        f"PRD ID: {prd_id}\n\n"
        f"PRD:\n{json.dumps(prd, ensure_ascii=False, indent=2)}"
    )

    messages = [
        Message(role="system", content=prompt),
        Message(role="user", content=user_content),
    ]

    from paperforge.config import get_config
    cfg = get_config()

    response = await llm.chat(
        model=cfg.GENERATOR_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )

    content = response.content or "{}"
    try:
        manifest = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Generator returned invalid JSON: {e}\nContent: {content[:500]}")
        raise ValueError(f"Generator returned invalid JSON: {e}")

    files = manifest.get("files", [])
    for f in files:
        file_path = output_dir / f["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f["content"], encoding="utf-8")

    pkg_path = output_dir / "package.json"
    if not pkg_path.exists():
        deps = manifest.get("dependencies", {})
        scripts = manifest.get("scripts", {"dev": "next dev", "build": "next build", "start": "next start"})
        pkg = {
            "name": manifest.get("app_id", "generated-app"),
            "version": "0.1.0",
            "private": True,
            "scripts": scripts,
            "dependencies": deps,
        }
        pkg_path.write_text(json.dumps(pkg, indent=2), encoding="utf-8")

    manifest["app_id"] = app_id
    manifest["prd_id"] = prd_id
    manifest["output_dir"] = str(output_dir)

    return manifest
