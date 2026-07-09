"""Library API routes: upload/list/delete papers."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from paperforge.storage.db import get_storage

router = APIRouter()


def _slugify(name: str) -> str:
    """Convert a filename stem to a filesystem-safe paper_id slug."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
    return slug or "paper"


def _unique_paper_id(storage: object, stem: str) -> str:
    """Return a paper_id that does not collide with an existing paper.

    Strategy: slugify the stem, then if that ID already exists in the
    library, append a numeric suffix (2, 3, 4, ...) until we find a free
    slot. This keeps human-readable IDs while preventing silent overwrites.
    """
    base = _slugify(stem)
    candidate = base
    suffix = 2
    # Keep probing until we find an unused paper_id.
    # If a paper with `candidate` already exists, treat it as occupied.
    while True:
        existing = storage.get_paper(candidate)
        if not existing:
            return candidate
        candidate = f"{base}_{suffix}"
        suffix += 1


@router.get("")
async def list_papers() -> dict:
    """List all papers in the library."""
    storage = get_storage()
    papers = storage.list_papers()
    return {"papers": papers}


@router.post("/upload")
async def upload_paper(file: UploadFile) -> dict:
    """Upload a PDF to the library.

    Uses a unique paper_id (with numeric suffix on collision) so re-uploading
    a same-named PDF does not silently overwrite the previous paper record.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    storage = get_storage()
    paper_id = _unique_paper_id(storage, Path(file.filename).stem)

    # Save PDF to library directory
    pdf_path = storage.library_dir / f"{paper_id}.pdf"
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Upsert paper record
    paper = storage.upsert_paper(
        paper_id=paper_id,
        title=paper_id,  # will be updated after parsing
        pdf_path=str(pdf_path),
        status="uploaded",
    )

    return paper


@router.get("/{paper_id}")
async def get_paper(paper_id: str) -> dict:
    """Get a paper and its capability card (if parsed)."""
    storage = get_storage()
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    card = None
    card_path = paper.get("card_path")
    if card_path and Path(card_path).exists():
        card = json.loads(Path(card_path).read_text(encoding="utf-8"))

    return {"paper": paper, "capability_card": card}


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str) -> dict:
    """Delete a paper from the library."""
    storage = get_storage()
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    # Delete PDF file
    pdf_path = Path(paper["pdf_path"])
    if pdf_path.exists():
        pdf_path.unlink()

    # Delete capability card if exists
    card_path = paper.get("card_path")
    if card_path and Path(card_path).exists():
        Path(card_path).unlink()

    storage.delete_paper(paper_id)
    return {"status": "deleted", "paper_id": paper_id}


@router.get("/{paper_id}/pdf")
async def download_pdf(paper_id: str) -> FileResponse:
    """Download the original PDF."""
    storage = get_storage()
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    pdf_path = Path(paper["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{paper_id}.pdf",
    )
