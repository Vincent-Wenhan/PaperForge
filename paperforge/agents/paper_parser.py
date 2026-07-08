"""PaperParser: PDF → capability card JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt

logger = logging.getLogger(__name__)


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

    response = await llm.chat(
        model=cfg.PARSER_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
    )

    content = response.content or "{}"
    try:
        card = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON: {e}\nContent: {content[:500]}")
        raise ValueError(f"LLM returned invalid JSON: {e}")

    card["paper_id"] = paper_id

    return card
