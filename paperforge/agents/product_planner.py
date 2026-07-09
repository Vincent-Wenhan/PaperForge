"""ProductPlanner: refine composition into a PRD, or ask clarifying questions."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.prd import PRD
from paperforge.schemas.planner_output import PlannerOutput
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def plan_product(
    user_requirement: str,
    llm: LLMClient,
    storage: Storage,
    composition_id: str | None = None,
    card_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Refine a composition into a PRD, or return clarifying questions.

    Supports two flows:
    - Multi-paper: pass composition_id (from compose_capabilities)
    - Single-paper: pass card_ids (bypasses composition)

    Args:
        user_requirement: user's stated product goal
        llm: LLM client
        storage: storage instance
        composition_id: ID of the composition artifact (multi-paper flow)
        card_ids: list of capability card IDs (single-paper flow)

    Returns:
        PlannerOutput dict. If `needs_more_input` is True, `questions`
        contains clarifying questions to ask the user before re-running
        the planner. If False, `prd` contains the generated PRD.
    """
    if not composition_id and not card_ids:
        raise ValueError("Either composition_id or card_ids must be provided")

    if composition_id:
        # Multi-paper flow: load composition artifact
        composition = None
        artifacts = storage.list_artifacts(artifact_type="composition")
        for a in artifacts:
            if a["id"] == composition_id or a.get("metadata", {}).get("composition_id") == composition_id:
                composition = a.get("data") or {}
                break

        if not composition:
            artifact = storage.get_artifact(composition_id)
            if artifact:
                composition = artifact.get("data") or {}
            else:
                raise ValueError(f"Composition not found: {composition_id}")

        source_data = composition
        source_label = "composition"
    else:
        # Single-paper flow: synthesize a minimal composition from raw cards
        cards: list[dict[str, Any]] = []
        for paper_id in card_ids:
            paper = storage.get_paper(paper_id)
            if not paper:
                raise ValueError(f"Paper not found: {paper_id}")
            card_path = paper.get("card_path")
            if not card_path or not Path(card_path).exists():
                raise ValueError(f"Capability card not found for paper: {paper_id}")
            card = json.loads(Path(card_path).read_text(encoding="utf-8"))
            cards.append(card)

        source_data = {
            "composition_id": f"single_{card_ids[0]}",
            "source_cards": list(card_ids),
            "product_candidates": [],
        }
        source_label = "single-paper"

    prd_id = f"prd_{uuid.uuid4().hex[:8]}"

    # Build prompt
    prompt = load_prompt("product_planner")
    user_content = (
        f"PRD ID: {prd_id}\n"
        f"Source type: {source_label}\n"
        f"User requirement: {user_requirement}\n\n"
        f"Source data:\n{json.dumps(source_data, ensure_ascii=False, indent=2)}"
    )

    messages = [
        Message(role="system", content=prompt),
        Message(role="user", content=user_content),
    ]

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
            raw = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: invalid JSON: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your previous response was not valid JSON: {e}. Please output a valid JSON object only."))
            continue

        # Handle needs_more_input case
        if raw.get("needs_more_input"):
            questions = raw.get("questions") or []
            if not questions:
                questions = [
                    "目标用户是谁？",
                    "demo 更偏科研工具还是普通用户产品？",
                    "是否需要真实模型接入？",
                ]
            output = PlannerOutput(
                needs_more_input=True,
                questions=questions,
                prd=None,
            )
            return output.model_dump()

        # Handle PRD case
        prd_dict = raw.get("prd") or raw
        prd_dict["prd_id"] = prd_id
        if composition_id:
            prd_dict["composition_id"] = composition_id
        elif card_ids:
            prd_dict["card_ids"] = list(card_ids)

        try:
            validated = PRD.model_validate(prd_dict)
            prd_dict = validated.model_dump()
            output = PlannerOutput(
                needs_more_input=False,
                questions=[],
                prd=prd_dict,
            )
            return output.model_dump()
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: schema validation failed: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your JSON did not match the PRD schema: {e}. Please fix and return a valid PRD."))

    raise ValueError(f"ProductPlanner failed after {MAX_RETRIES} retries: {last_error}")
