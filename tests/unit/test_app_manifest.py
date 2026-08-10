"""Tests for the AppManifest schema (PR-02: generator safety)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from paperforge.schemas.app_manifest import (
    ALLOWED_DEPENDENCIES,
    AppFile,
    AppManifest,
)


class TestAppFileValidation:
    def test_accepts_business_file(self) -> None:
        f = AppFile(path="app/page.tsx", content="export default function Page() {}")
        assert f.path == "app/page.tsx"

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AppFile(path="../app/page.tsx", content="x")
        assert "Path traversal" in str(exc_info.value)

    def test_rejects_non_writable_root(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AppFile(path="app/evil.tsx", content="x")
            AppFile(path="script/evil.ts", content="x")
        assert "not writable" in str(exc_info.value) or "Root" in str(exc_info.value)

    def test_normalizes_backslash_and_leading_slash(self) -> None:
        f = AppFile(path="\\lib\\mock-api.ts", content="x")
        assert f.path == "lib/mock-api.ts"

    def test_rejects_oversized_content(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AppFile(path="app/page.tsx", content="x" * 400_001)
        assert "too large" in str(exc_info.value)

class TestAppManifestValidation:
    def test_accepts_valid_manifest(self) -> None:
        m = AppManifest(
            app_id="app_1",
            prd_id="prd_1",
            dependencies={"next": "^14.2.5"},
        )
        assert m.app_id == "app_1"

    def test_rejects_unknown_dependency(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AppManifest(
                app_id="app_1",
                dependencies={"evil-package": "1.0.0"},
            )
        assert "Dependencies are not allowed" in str(exc_info.value)

    def test_rejects_duplicate_file_paths(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            AppManifest(
                app_id="app_1",
                files=[
                    AppFile(path="app/page.tsx", content="a"),
                    AppFile(path="app/page.tsx", content="b"),
                ],
            )
        assert "Duplicate generated file path" in str(exc_info.value)

    def test_business_policy_roots(self) -> None:
        # The exact 3-file allowlist is retired; the safe-policy writable roots
        # still accept the canonical Next.js app entrypoint.
        from paperforge.schemas.workspace_policy import SafeWorkspacePolicy

        policy = SafeWorkspacePolicy()
        assert policy.normalize("app/page.tsx") == "app/page.tsx"
        assert policy.normalize("lib/mock-api.ts") == "lib/mock-api.ts"

    def test_allowed_dependencies_includes_core(self) -> None:
        assert "next" in ALLOWED_DEPENDENCIES
        assert "react" in ALLOWED_DEPENDENCIES
        assert "zod" in ALLOWED_DEPENDENCIES
