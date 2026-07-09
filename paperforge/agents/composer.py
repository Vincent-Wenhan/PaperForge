"""Composer: combine multiple capability cards into novel product concepts."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.composition import Composition
from paperforge.storage.db import Storage

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def compose(
    card_ids: list[str],
    llm: LLMClient,
    storage: Storage,
) -> dict[str, Any]:
    """Compose multiple capability cards into a single composition artifact."""
    if not card_ids:
        raise ValueError("card_ids must be non-empty")

    # Load each capability card from the paper's card_path
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

    prompt = load_prompt("composer")
    composition_id = f"comp_{uuid.uuid4().hex[:8]}"

    user_content = (
        f"Composition ID: {composition_id}\n\n"
        f"Source cards ({len(cards)}):\n\n"
        + "\n\n---\n\n".join(json.dumps(c, ensure_ascii=False, indent=2) for c in cards)
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
            model=cfg.COMPOSER_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )

        content = response.content or "{}"
        try:
            composition = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: invalid JSON: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your previous response was not valid JSON: {e}. Please output a valid JSON object only."))
            continue

        composition["composition_id"] = composition_id
        composition["source_cards"] = list(card_ids)

        try:
            validated = Composition.model_validate(composition)
            composition = validated.model_dump()
            return composition
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: schema validation failed: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your JSON did not match the Composition schema: {e}. Please fix and return a valid Composition."))

    raise ValueError(f"Composer failed after {MAX_RETRIES} retries: {last_error}")
