"""PaperParser: PDF → capability card JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.paper import CapabilityCard

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz
    except ImportError as e:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF parsing. Install with: pip install pymupdf"
        ) from e

    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n\n".join(pages)


async def parse_paper(
    pdf_path: str | Path,
    paper_id: str | None,
    llm: LLMClient,
) -> dict[str, Any]:
    """Parse a PDF and return a capability card as a dict."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    paper_id = paper_id or pdf_path.stem

    text = extract_pdf_text(pdf_path)
    if not text.strip():
        raise ValueError(f"No text could be extracted from PDF: {pdf_path}")

    max_chars = 80000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... truncated ...]"
        logger.warning(f"Truncated PDF text from {len(text)} to {max_chars} chars")

    prompt = load_prompt("paper_parser")

    from paperforge.config import get_config
    cfg = get_config()

    messages = [
        Message(role="system", content=prompt),
        Message(role="user", content=f"Paper ID: {paper_id}\n\nPaper text:\n{text}"),
    ]

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        response = await llm.chat(
            model=cfg.PARSER_MODEL,
            messages=messages,
            response_format={"type": "json_object"},
        )

        content = response.content or "{}"
        try:
            card = json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: invalid JSON: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your previous response was not valid JSON: {e}. Please output a valid JSON object only."))
            continue

        try:
            validated = CapabilityCard.model_validate(card)
            card = validated.model_dump()
            card["paper_id"] = paper_id
            return card
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES}: schema validation failed: {e}")
            messages.append(Message(role="assistant", content=content))
            messages.append(Message(role="user", content=f"Your JSON did not match the CapabilityCard schema: {e}. Please fix and return a valid CapabilityCard."))

    raise ValueError(f"PaperParser failed after {MAX_RETRIES} retries: {last_error}")
