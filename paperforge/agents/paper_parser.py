"""PaperParser: PDF → capability card JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from paperforge.llm.base import LLMClient, Message
from paperforge.prompts import load_prompt
from paperforge.schemas.capability_contract import CapabilityContract, ParseCoverage
from paperforge.schemas.paper import CapabilityCard

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_CHUNK_CHARS = 12000
MAX_CHUNKS = 32
MAX_MAP_CHUNKS = 16  # chunks fed to the LLM per map call
REDUCE_GROUP_SIZE = 6  # chunks summarized per group step in the hierarchy


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

    # Whole-paper bounded hierarchy: instead of dumping every mapped chunk into
    # one giant reduce (or truncating the paper to the first N chunks), fold
    # groups of maps up level by level until a single summary remains.
    summaries = await _hierarchical_reduce(mapped=mapped, llm=llm, prompt=prompt, paper_id=paper_id)

    final_summary = await _synthesize_capability(
        summaries=summaries,
        llm=llm,
        prompt=prompt,
        paper_id=paper_id,
    )

    card = final_summary.get("card") or final_summary
    contract = final_summary.get("contract") or _extract_contract_from_card(card)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            validated = CapabilityCard.model_validate(card)
            card = validated.model_dump()
            card["paper_id"] = paper_id
            if contract:
                card["capability_contract"] = CapabilityContract.model_validate(contract).model_dump()
            # Reconstruct coverage from the chunks that *actually* mapped
            # successfully, using their real 1-based index, not a contiguous
            # slice. A failed chunk between successes must not count as
            # processed.
            processed_chunks: list[str] = []
            for item in mapped:
                try:
                    position = int(item.get("chunk")) - 1
                except (TypeError, ValueError):
                    continue
                if 0 <= position < len(chunks):
                    processed_chunks.append(chunks[position])
            coverage = _build_parse_coverage(pages, processed_chunks).model_dump()
            card["parse_coverage"] = coverage
            return card
        except Exception as exc:
            last_error = exc
            logger.warning("Contract validation failed: %s", exc)
            return card

    raise ValueError(f"PaperParser failed after {MAX_RETRIES} retries: {last_error}")


async def _hierarchical_reduce(
    *,
    mapped: list[dict[str, Any]],
    llm: LLMClient,
    prompt: str,
    paper_id: str,
) -> list[dict[str, Any]]:
    """Fold mapped chunk summaries up a bounded hierarchy.

    Each level summarises up to ``REDUCE_GROUP_SIZE`` entries into one; repeating
    until a single summary remains. Budget is bounded per level rather than by
    dropping the second half of the paper.
    """
    level: list[dict[str, Any]] = [item.get("data", {}) for item in mapped]
    while len(level) > REDUCE_GROUP_SIZE:
        next_level: list[dict[str, Any]] = []
        for offset in range(0, len(level), REDUCE_GROUP_SIZE):
            group = level[offset : offset + REDUCE_GROUP_SIZE]
            next_level.append(
                await _reduce_group(group=group, llm=llm, prompt=prompt, paper_id=paper_id)
            )
        level = next_level
    return level


async def _reduce_group(
    *,
    group: list[dict[str, Any]],
    llm: LLMClient,
    prompt: str,
    paper_id: str,
) -> dict[str, Any]:
    """Summarise a group of chunk maps into one merged map."""
    from paperforge.config import get_config
    response = await llm.chat(
        model=get_config().PARSER_MODEL,
        messages=[
            Message(role="system", content=prompt),
            Message(
                role="user",
                content=(
                    f"Paper ID: {paper_id}\n\n"
                    "Summarize these chunk maps into one merged chunk map JSON. "
                    "Preserve evidence, do not invent claims.\n"
                    f"Maps:\n{json.dumps(group, ensure_ascii=False)}"
                ),
            ),
        ],
        response_format={"type": "json_object"},
    )
    try:
        data = json.loads(response.content or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def _synthesize_capability(
    *,
    summaries: list[dict[str, Any]],
    llm: LLMClient,
    prompt: str,
    paper_id: str,
) -> dict[str, Any]:
    """Synthesize the final CapabilityCard and its CapabilityContract JSON."""
    from paperforge.config import get_config
    response = await llm.chat(
        model=get_config().PARSER_MODEL,
        messages=[
            Message(role="system", content=prompt),
            Message(
                role="user",
                content=(
                    f"Paper ID: {paper_id}\n\n"
                    "Reduce the following summaries into one object with two keys:\n"
                    "- `card`: a CapabilityCard JSON (title, authors, problem, method, "
                    "key_innovations, metrics, evidence, ...).\n"
                    "- `contract`: a CapabilityContract JSON for the Product Planner "
                    "(inputs, outputs, preconditions, failure_modes, compute_requirements, "
                    "integration_mode, implementation_refs, confidence).\n"
                    f"Summaries:\n{json.dumps(summaries, ensure_ascii=False)}"
                ),
            ),
        ],
        response_format={"type": "json_object"},
    )
    try:
        parsed = json.loads(response.content or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    card = parsed.get("card")
    if not isinstance(card, dict):
        # Old-style flat card with no contract split.
        return parsed
    return parsed


def _extract_contract_from_card(card: dict[str, Any]) -> dict[str, Any] | None:
    """Fallback: derive a minimal contract from a legacy flat card."""
    inputs = [
        {"name": name, "type": "any", "description": ""}
        for name in (card.get("inputs") or [])
        if isinstance(name, str)
    ]
    outputs = [
        {"name": name, "type": "any", "description": ""}
        for name in (card.get("outputs") or [])
        if isinstance(name, str)
    ]
    if not inputs and not outputs:
        return None
    return {
        "name": card.get("title", ""),
        "description": card.get("problem", ""),
        "inputs": inputs,
        "outputs": outputs,
        "integration_mode": "unknown",
        "confidence": 0.0,
    }


def _build_parse_coverage(pages: list[str], chunks: list[str]) -> ParseCoverage:
    """Reconstruct which PDF pages are covered by the processed chunks.

    Each chunk carries ``[[Page N]]`` markers. Pages whose text appears in at
    least one kept chunk are ``processed``; the rest are ``omitted`` so we never
    silently truncate a paper. If chunking truncated the pages, coverage is
    marked incomplete.
    """
    total_pages = len(pages)
    marker_pattern = "[[Page "
    processed: set[int] = set()
    for chunk in chunks:
        for marker in [c for c in chunk.split("[[") if c.startswith("Page ")]:
            try:
                num = int(marker[len("Page "):].split("]]")[0])
            except ValueError:
                continue
            if 1 <= num <= total_pages:
                processed.add(num)
    processed_pages = sorted(processed)
    omitted_pages = [p for p in range(1, total_pages + 1) if p not in processed]
    complete = not omitted_pages
    return ParseCoverage(
        total_pages=total_pages,
        processed_pages=processed_pages,
        omitted_pages=omitted_pages,
        complete=complete,
    )
