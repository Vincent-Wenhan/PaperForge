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
MAX_CHUNK_CHARS = 12000
MAX_CHUNKS = 32


def extract_pdf_pages(pdf_path: str | Path) -> list[str]:
    """Extract text from a PDF using PyMuPDF (fitz), with page markers.

    Returns:
        One string per page, each prefixed with a stable page marker.
    """
    try:
        import fitz
    except ImportError as e:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF parsing. Install with: pip install pymupdf"
        ) from e

    doc = fitz.open(str(pdf_path))
    pages: list[str] = []
    for i, page in enumerate(doc):
        text = page.get_text()
        pages.append(f"[[Page {i + 1}]]\n{text}")
    doc.close()
    return pages


def extract_pdf_text(pdf_path: str | Path) -> str:
    """Extract a backward-compatible page-marked text string."""
    return "\n\n".join(extract_pdf_pages(pdf_path))


def chunk_pdf_pages(
    pages: list[str],
    *,
    max_chars: int = MAX_CHUNK_CHARS,
    max_chunks: int = MAX_CHUNKS,
) -> list[str]:
    """Split page-marked text into bounded chunks without losing page anchors."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    chunks: list[str] = []
    current = ""
    for page in pages:
        if len(page) <= max_chars:
            candidate = f"{current}\n\n{page}" if current else page
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = page
            else:
                current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""
        marker, _, body = page.partition("\n")
        body_limit = max(1, max_chars - len(marker) - 1)
        for offset in range(0, len(body), body_limit):
            chunks.append(f"{marker}\n{body[offset:offset + body_limit]}")

    if current:
        chunks.append(current)
    if len(chunks) > max_chunks:
        logger.warning("Truncating parsed PDF chunks from %s to %s", len(chunks), max_chunks)
        chunks = chunks[:max_chunks]
    return chunks


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

    pages = extract_pdf_pages(pdf_path)
    if not any(page.strip() for page in pages):
        raise ValueError(f"No text could be extracted from PDF: {pdf_path}")

    chunks = chunk_pdf_pages(pages, max_chars=MAX_CHUNK_CHARS)

    prompt = load_prompt("paper_parser")

    from paperforge.config import get_config
    cfg = get_config()

    mapped: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        response = await llm.chat(
            model=cfg.PARSER_MODEL,
            messages=[
                Message(role="system", content=prompt),
                Message(
                    role="user",
                    content=(
                        f"Paper ID: {paper_id}\n\n"
                        f"Map chunk {index}/{len(chunks)} into evidence-backed JSON.\n"
                        f"Paper text:\n{chunk}"
                    ),
                ),
            ],
            response_format={"type": "json_object"},
        )
        content = response.content or "{}"
        try:
            chunk_data = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid map JSON for PDF chunk %s", index)
            continue
        if isinstance(chunk_data, dict):
            mapped.append({"chunk": index, "data": chunk_data})

    if not mapped:
        raise ValueError("PaperParser produced no valid map results")

    reduce_messages = [
        Message(role="system", content=prompt),
        Message(
            role="user",
            content=(
                f"Paper ID: {paper_id}\n\n"
                "Reduce the following page/chunk maps into one CapabilityCard JSON. "
                "Preserve evidence page numbers and do not invent claims.\n"
                f"Mapped chunks:\n{json.dumps(mapped, ensure_ascii=False)}"
            ),
        ),
    ]

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        response = await llm.chat(
            model=cfg.PARSER_MODEL,
            messages=reduce_messages,
            response_format={"type": "json_object"},
        )
        content = response.content or "{}"
        try:
            card = json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
            reduce_messages.append(Message(role="assistant", content=content))
            reduce_messages.append(
                Message(role="user", content="Return valid CapabilityCard JSON only.")
            )
            continue

        try:
            validated = CapabilityCard.model_validate(card)
            card = validated.model_dump()
            card["paper_id"] = paper_id
            return card
        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %s/%s: schema validation failed: %s", attempt, MAX_RETRIES, exc)
            reduce_messages.append(Message(role="assistant", content=content))
            reduce_messages.append(
                Message(
                    role="user",
                    content=f"Fix the CapabilityCard schema errors and return JSON only: {exc}",
                )
            )

    raise ValueError(f"PaperParser failed after {MAX_RETRIES} retries: {last_error}")
