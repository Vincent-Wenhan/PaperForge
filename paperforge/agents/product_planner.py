"""ProductPlanner: refine composition into a PRD (single-shot)."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)


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

    response = await llm.chat(
        model=cfg.PLANNER_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )

    content = response.content or "{}"
    try:
        prd = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Planner returned invalid JSON: {e}\nContent: {content[:500]}")
        raise ValueError(f"Planner returned invalid JSON: {e}")

    # Ensure required fields
    prd["prd_id"] = prd_id
    prd["composition_id"] = composition_id

    return prd
