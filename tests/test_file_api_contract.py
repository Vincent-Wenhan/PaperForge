from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import create_app
from api.routes.files import MAX_FILE_SIZE


def _sandbox(storage, tmp_path):
    storage.create_run("run_files_contract", "Files", status="active")
    root = tmp_path / "app"
    root.mkdir()
    storage.save_sandbox(
        "sb_contract",
        "run_files_contract",
        str(root),
        status="running",
    )
    return TestClient(create_app()), root


def test_file_api_allows_directory_entries_and_rejects_invalid_type(storage, tmp_path):
    client, root = _sandbox(storage, tmp_path)

    created = client.post(
        "/api/files/sandboxes/sb_contract/entries",
        json={"type": "directory", "path": "src/components"},
    )
    assert created.status_code == 200
    assert (root / "src" / "components").is_dir()

    invalid = client.post(
        "/api/files/sandboxes/sb_contract/entries",
        json={"type": "symlink", "path": "src/link.ts"},
    )
    assert invalid.status_code == 400


def test_file_api_limits_incoming_content_and_rejects_traversal(storage, tmp_path):
    client, _ = _sandbox(storage, tmp_path)

    oversized = client.put(
        "/api/files/sandboxes/sb_contract/files/src/page.tsx",
        json={"content": "x" * (MAX_FILE_SIZE + 1)},
    )
    assert oversized.status_code == 413

    traversal = client.put(
        "/api/files/sandboxes/sb_contract/files/../escape.ts",
        json={"content": "bad"},
    )
    assert traversal.status_code in {400, 403, 404}
