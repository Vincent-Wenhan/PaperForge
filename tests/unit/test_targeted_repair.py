"""Tests for Targeted Repair V2 (doc 22): error-path extraction and dependency expansion."""

from __future__ import annotations

from pathlib import Path

from paperforge.agents.verifier import expand_repair_context, extract_error_paths


# ===== 22.1 extract_error_paths =====


def test_extract_error_paths_picks_unique_paths():
    errors = [
        "app/page.tsx:12 - Type 'X' is not assignable to type 'Y'",
        "components/Card.tsx(34): Property 'title' does not exist",
        "lib/api.ts:5 - Cannot find name 'foo'",
        "app/page.tsx:99 - another error in the same file",
        "not/relative/path:3 - should be ignored",
    ]
    paths = extract_error_paths(errors)
    assert paths == ["app/page.tsx", "components/Card.tsx", "lib/api.ts"]


def test_extract_error_paths_empty():
    assert extract_error_paths([]) == []


# ===== 22.2 expand_repair_context =====


def test_expand_repair_context_includes_local_dependencies(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "components").mkdir()

    (tmp_path / "app" / "page.tsx").write_text(
        "import { Card } from '@/components/Card';\n"
        "import { fetchData } from '@/lib/api';\n"
    )
    (tmp_path / "components" / "Card.tsx").write_text("export const Card = () => null;\n")
    (tmp_path / "lib" / "api.ts").write_text("export const fetchData = () => {};\n")

    selected = expand_repair_context(tmp_path, ["app/page.tsx"])

    assert "app/page.tsx" in selected
    assert "components/Card.tsx" in selected
    assert "lib/api.ts" in selected


def test_expand_repair_context_respects_max_files(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "lib").mkdir()

    (tmp_path / "app" / "page.tsx").write_text(
        "".join(
            f"import {{ x{i} }} from '@/lib/file{i}';\n" for i in range(30)
        )
    )
    for i in range(30):
        (tmp_path / "lib" / f"file{i}.ts").write_text(f"export const x{i} = 1;\n")

    selected = expand_repair_context(tmp_path, ["app/page.tsx"], max_files=12)
    assert len(selected) <= 12


def test_expand_repair_context_ignores_missing_seed(tmp_path: Path):
    selected = expand_repair_context(tmp_path, ["app/missing.tsx"])
    assert selected == ["app/missing.tsx"]
