"""Library API routes: upload/list/delete/rename papers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()
MAX_PDF_SIZE = 25 * 1024 * 1024


class PaperUpdate(BaseModel):
    title: str | None = None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
    return slug or "paper"


@router.get("")
async def list_papers() -> dict:
    storage = get_storage()
    papers = storage.list_papers()
    return {"papers": papers}


@router.post("/upload")
async def upload_paper(file: UploadFile) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    payload = await file.read(MAX_PDF_SIZE + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="PDF file is empty")
    if len(payload) > MAX_PDF_SIZE:
        raise HTTPException(status_code=413, detail="PDF file is too large")
    if not payload.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF")

    storage = get_storage()
    paper_id = _slugify(Path(file.filename).stem)
    if storage.get_paper(paper_id):
        suffix = 2
        while storage.get_paper(f"{paper_id}_{suffix}"):
            suffix += 1
        paper_id = f"{paper_id}_{suffix}"

    pdf_path = storage.library_dir / f"{paper_id}.pdf"
    pdf_path.write_bytes(payload)

    paper = storage.upsert_paper(
        paper_id=paper_id,
        title=Path(file.filename).stem,
        pdf_path=str(pdf_path),
        status="uploaded",
    )
    return paper


@router.get("/{paper_id}")
async def get_paper(paper_id: str) -> dict:
    storage = get_storage()
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    capability_card = None
    card_path = paper.get("card_path")
    if card_path and Path(card_path).exists():
        try:
            capability_card = json.loads(Path(card_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            capability_card = None
    return {"paper": paper, "capability_card": capability_card}


@router.patch("/{paper_id}")
async def update_paper(paper_id: str, req: PaperUpdate) -> dict:
    storage = get_storage()
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if req.title:
        storage.update_paper_title(paper_id, req.title)
    return storage.get_paper(paper_id)


@router.delete("/{paper_id}")
async def delete_paper(paper_id: str) -> dict:
    storage = get_storage()
    paper = storage.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")

    pdf_path = Path(paper["pdf_path"])
    if pdf_path.exists():
        pdf_path.unlink()

    card_path = paper.get("card_path")
    if card_path and Path(card_path).exists():
        Path(card_path).unlink()

    storage.delete_paper(paper_id)
    return {"status": "deleted", "paper_id": paper_id}


@router.get("/{paper_id}/pdf")
async def download_pdf(paper_id: str) -> FileResponse:
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
