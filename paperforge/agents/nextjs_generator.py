"""NextjsGenerator: PRD → Next.js app files.

Strategy (template-based):
1. Copy a pre-baked Next.js template (paperforge/templates/nextjs_lightweight)
   to a temporary directory under storage.apps_dir.
2. Call LLM with generator prompt + PRD JSON. The LLM only generates the
   business files: app/page.tsx, lib/mock-api.ts, lib/real-api.ts.
3. Validate against AppManifest schema. The schema enforces:
   - Only files in BUSINESS_FILES may be generated.
   - Path traversal (``..`` parts, absolute paths) is rejected.
   - Only dependencies in ALLOWED_DEPENDENCIES may be declared.
4. Write LLM-generated business files to the temp dir.
5. Atomically rename the temp dir to the final output_dir, replacing any
   previous attempt. Never partially overwrite the destination.
6. Always pin npm scripts to SAFE_SCRIPTS; ignore model-returned scripts.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
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

# npm scripts the generator pins. The model may not override these —
# otherwise a hallucinating or compromised model could swap ``build``
# for an arbitrary shell command.
SAFE_SCRIPTS: dict[str, str] = {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit",
    "lint": "next lint",
}


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
    final_dir = Path(output_dir).resolve()

    apps_root = storage.apps_dir.resolve()
    try:
        final_dir.relative_to(apps_root)
    except ValueError as exc:
        raise ValueError(
            f"output_dir must be inside {apps_root}, got {final_dir}"
        ) from exc
    if final_dir == apps_root:
        raise ValueError("output_dir must name a child app directory")
    final_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: copy template scaffolding into a temp dir under apps_root.
    if not TEMPLATE_DIR.exists():
        raise FileNotFoundError(f"Template directory not found: {TEMPLATE_DIR}")

    with tempfile.TemporaryDirectory(
        prefix="paperforge-generate-",
        dir=str(apps_root),
    ) as temp_name:
        temp_dir = Path(temp_name)
        shutil.copytree(src=TEMPLATE_DIR, dst=temp_dir, dirs_exist_ok=True)

        # Step 2: call LLM to generate only business files.
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
        manifest_dict: dict[str, Any] = {}
        for attempt in range(1, MAX_RETRIES + 1):
            response = await llm.chat(
                model=cfg.GENERATOR_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
            )

            content = response.content or "{}"
            try:
                manifest_dict = json.loads(content)
            except json.JSONDecodeError as e:
                last_error = e
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: invalid JSON: {e}")
                messages.append(Message(role="assistant", content=content))
                messages.append(Message(role="user", content=f"Your previous response was not valid JSON: {e}. Please output a valid JSON object only."))
                continue

            manifest_dict["app_id"] = app_id
            manifest_dict["prd_id"] = prd_id

            try:
                validated = AppManifest.model_validate(manifest_dict)
                manifest_dict = validated.model_dump()
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: schema validation failed: {e}")
                messages.append(Message(role="assistant", content=content))
                messages.append(Message(role="user", content=f"Your JSON did not match the AppManifest schema: {e}. Please fix and return a valid AppManifest."))
        else:
            raise ValueError(f"NextjsGenerator failed after {MAX_RETRIES} retries: {last_error}")

        # Step 3: write LLM-generated business files. AppFile.path is already
        # validated against BUSINESS_FILES, so no path traversal is possible.
        for f in validated.files:
            target = (temp_dir / f.path).resolve()
            try:
                target.relative_to(temp_dir.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"Refusing to write outside output dir: {f.path}"
                ) from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f.content, encoding="utf-8")

        # Step 4: merge template package.json with manifest-declared
        # dependencies. Always pin scripts to SAFE_SCRIPTS.
        write_safe_package_json(temp_dir, manifest_dict)

        # Step 5: atomically swap temp_dir → final_dir.
        if final_dir.exists():
            backup = final_dir.with_name(final_dir.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(final_dir, backup)
        os.replace(temp_dir, final_dir)

    manifest_dict["app_id"] = app_id
    manifest_dict["prd_id"] = prd_id
    manifest_dict["output_dir"] = str(final_dir)

    return manifest_dict


def write_safe_package_json(app_dir: Path, manifest: dict[str, Any]) -> None:
    """Write a package.json pinned to SAFE_SCRIPTS and allowed dependencies."""
    pkg_path = app_dir / "package.json"
    template_pkg = json.loads(pkg_path.read_text(encoding="utf-8")) if pkg_path.exists() else {}

    deps = manifest.get("dependencies", {}) or {}
    # ALLOWED_DEPENDENCIES is enforced by AppManifest, but we double-check
    # here so a future caller that bypasses validation cannot smuggle deps.
    from paperforge.schemas.app_manifest import ALLOWED_DEPENDENCIES
    blocked = {name: version for name, version in deps.items() if name not in ALLOWED_DEPENDENCIES}
    if blocked:
        raise ValueError(
            f"Refusing to declare non-allowlist dependencies: {sorted(blocked)}"
        )

    pkg = {
        "name": manifest.get("app_id", "generated-app"),
        "version": "0.1.0",
        "private": True,
        "scripts": SAFE_SCRIPTS,
        "dependencies": {**template_pkg.get("dependencies", {}), **deps},
        "devDependencies": template_pkg.get("devDependencies", {}),
    }
    pkg_path.write_text(json.dumps(pkg, indent=2), encoding="utf-8")
