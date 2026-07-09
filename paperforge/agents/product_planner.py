"""ProductPlanner: refine composition into a PRD (single-shot)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.prd import PRD
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def plan_product(
    composition_id: str,
    user_requirement: str,
    llm: LLMClient,
    storage: Storage,
) -> dict[str, Any]:
    """Refine a composition into a PRD.

    Args:
        composition_id: ID of the composition artifact
        user_requirement: user's stated product goal
        llm: LLM client
        storage: storage instance

    Returns:
        PRD dict matching the PRD schema
    """
    # Load composition artifact
    from paperforge.storage.artifacts import ArtifactStore
    artifact_store = ArtifactStore(storage)

    # Find composition artifact by ID
    composition = None
    artifacts = storage.list_artifacts(artifact_type="composition")
    for a in artifacts:
        if a["id"] == composition_id or a.get("metadata", {}).get("composition_id") == composition_id:
            composition = a.get("data") or {}
            break

    if not composition:
        # Try direct artifact load
        artifact = storage.get_artifact(composition_id)
        if artifact:
            composition = artifact.get("data") or {}
        else:
            raise ValueError(f"Composition not found: {composition_id}")

    prd_id = f"prd_{uuid.uuid4().hex[:8]}"

    # Build prompt
    prompt = load_prompt("product_planner")
    user_content = (
        f"PRD ID: {prd_id}\n"
        f"Composition ID: {composition_id}\n"
        f"User requirement: {user_requirement}\n\n"
        f"Composition:\n{json.dumps(composition, ensure_ascii=False, indent=2)}"
    )

    messages = [
        Message(role="system", content=prompt),
        Message(role="user", content=user_content),
    ]

    # Call LLM
    from paperforge.config import get_config
    cfg = get_config()

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        response = await llm.chat(
            model=cfg.PLANNER_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )

        content = response.content or "{}"
        try:
            prd = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: invalid JSON: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your previous response was not valid JSON: {e}. Please output a valid JSON object only."))
            continue

        prd["prd_id"] = prd_id
        prd["composition_id"] = composition_id

        try:
            validated = PRD.model_validate(prd)
            prd = validated.model_dump()
            return prd
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: schema validation failed: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your JSON did not match the PRD schema: {e}. Please fix and return a valid PRD."))

    raise ValueError(f"ProductPlanner failed after {MAX_RETRIES} retries: {last_error}")
