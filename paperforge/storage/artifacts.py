"""File-based artifact storage helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from paperforge.storage.db import Storage


class ArtifactStore:
    """Convenience wrapper for reading/writing artifact JSON files."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def save_capability_card(self, run_id: str, card: dict[str, Any]) -> str:
        return self.storage.save_artifact(
            run_id, "capability_card", card, {"paper_id": card.get("paper_id")}
        )

    def save_composition(self, run_id: str, composition: dict[str, Any]) -> str:
        return self.storage.save_artifact(run_id, "composition", composition)

    def save_prd(self, run_id: str, prd: dict[str, Any]) -> str:
        return self.storage.save_artifact(run_id, "prd", prd)

    def save_verification_report(self, run_id: str, report: dict[str, Any]) -> str:
        return self.storage.save_artifact(run_id, "verification_report", report)

    def save_nextjs_app(self, run_id: str, manifest: dict[str, Any]) -> str:
        return self.storage.save_artifact(run_id, "nextjs_app", manifest)

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        return self.storage.get_artifact(artifact_id)

    def list_by_run(self, run_id: str, artifact_type: str | None = None) -> list[dict[str, Any]]:
        return self.storage.list_artifacts(run_id=run_id, artifact_type=artifact_type)
