"""Library API routes: upload/list/delete/rename papers."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from paperforge.storage.db import get_storage

router = APIRouter()


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

    storage = get_storage()
    paper_id = _slugify(Path(file.filename).stem)
    if storage.get_paper(paper_id):
        suffix = 2
        while storage.get_paper(f"{paper_id}_{suffix}"):
            suffix += 1
        paper_id = f"{paper_id}_{suffix}"

    pdf_path = storage.library_dir / f"{paper_id}.pdf"
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

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
    return {"paper": paper}


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
