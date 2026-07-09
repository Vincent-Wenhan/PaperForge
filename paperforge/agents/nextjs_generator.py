"""NextjsGenerator: PRD → Next.js app files.

Strategy (template-based):
1. Copy a pre-baked Next.js template (paperforge/templates/nextjs_lightweight)
   to the output directory with shutil.copytree.
2. Call LLM with generator prompt + PRD JSON. The LLM only generates the
   business files: app/page.tsx, lib/mock-api.ts, lib/real-api.ts.
3. Overwrite the template's placeholder business files with the LLM output.
4. Validate against AppManifest schema.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.app_manifest import AppManifest
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "nextjs_lightweight"

# Files the LLM is responsible for generating. Everything else is provided
# by the template scaffolding.
BUSINESS_FILES = ["app/page.tsx", "lib/mock-api.ts", "lib/real-api.ts"]


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

    # Step 1: copy template scaffolding
    if not TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Template directory not found: {TEMPLATE_DIR}")
    shutil.copytree(src=TEMPLATE_DIR, dst=output_dir, dirs_exist_ok=True)
    logger.info(f"Copied template scaffolding to {output_dir}")

    # Step 2: call LLM to generate only business files
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

    last_error: Exception | None = None
    manifest: dict[str, Any] = {}
    for attempt in range(1, MAX_RETRIES + 1):
        response = await llm.chat(
            model=cfg.GENERATOR_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )

        content = response.content or "{}"
        try:
            manifest = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: invalid JSON: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your previous response was not valid JSON: {e}. Please output a valid JSON object only."))
            continue

        manifest["app_id"] = app_id
        manifest["prd_id"] = prd_id

        try:
            validated = AppManifest.model_validate(manifest)
            manifest = validated.model_dump()
            break
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: schema validation failed: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your JSON did not match the AppManifest schema: {e}. Please fix and return a valid AppManifest."))
    else:
        raise ValueError(f"NextjsGenerator failed after {MAX_RETRIES} retries: {last_error}")

    # Step 3: write LLM-generated business files, overwriting template placeholders
    files = manifest.get("files", [])
    for f in files:
        file_path = output_dir / f["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f["content"], encoding="utf-8")

    # Step 4: merge template package.json with manifest-declared dependencies
    pkg_path = output_dir / "package.json"
    template_pkg = json.loads(pkg_path.read_text(encoding="utf-8")) if pkg_path.exists() else {}
    deps = manifest.get("dependencies", {})
    scripts = manifest.get("scripts") or template_pkg.get("scripts", {
        "dev": "next dev",
        "build": "next build",
        "start": "next start",
    })
    pkg = {
        "name": manifest.get("app_id", "generated-app"),
        "version": "0.1.0",
        "private": True,
        "scripts": scripts,
        "dependencies": {**template_pkg.get("dependencies", {}), **deps},
        "devDependencies": template_pkg.get("devDependencies", {}),
    }
    pkg_path.write_text(json.dumps(pkg, indent=2), encoding="utf-8")

    manifest["app_id"] = app_id
    manifest["prd_id"] = prd_id
    manifest["output_dir"] = str(output_dir)

    return manifest
