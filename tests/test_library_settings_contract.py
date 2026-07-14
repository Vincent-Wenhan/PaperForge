from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient

from api.main import create_app


def test_library_upload_validates_pdf_payload_and_detail_includes_card(storage):
    client = TestClient(create_app())

    empty = client.post(
        "/api/library/upload",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert empty.status_code == 400

    wrong_magic = client.post(
        "/api/library/upload",
        files={"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
    )
    assert wrong_magic.status_code == 400

    pdf_bytes = b"%PDF-1.4\\n%\\xe2\\xe3\\xcf\\xd3\\n"
    uploaded = client.post(
        "/api/library/upload",
        files={"file": ("valid.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )
    assert uploaded.status_code == 200
    paper_id = uploaded.json()["paper_id"]

    card_path = storage.library_dir / "valid-card.json"
    card_path.write_text(json.dumps({"title": "Card", "method": "Method"}), encoding="utf-8")
    storage.update_paper_status(paper_id, "parsed", card_path=str(card_path))

    detail = client.get(f"/api/library/{paper_id}")
    assert detail.status_code == 200
    assert detail.json()["capability_card"]["title"] == "Card"


def test_settings_returns_all_runtime_model_fields(storage):
    payload = TestClient(create_app()).get("/api/settings")

    assert payload.status_code == 200
    data = payload.json()
    assert data["orchestrator_model"]
    assert data["parser_model"]
    assert data["planner_model"]
    assert data["generator_model"]
    assert "max_iterations" in data
    assert "llm_max_retries" in data
