"""SafeWorkspacePolicy and workspace patch application.

Replaces the exact-3-file allowlist (BUSINESS_FILES) with a bounded-policy
check: finite writable roots, no traversal, protected files, size limits.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field


class SafeWorkspacePolicy:
    ALLOWED_ROOTS = {
        "app",
        "components",
        "hooks",
        "lib",
        "types",
        "public",
    }

    BLOCKED_PREFIXES = {
        ".git",
        "node_modules",
        ".next",
    }

    PROTECTED_FILES = {
        "package-lock.json",
        "next.config.mjs",
        "tsconfig.json",
    }

    MAX_FILE_BYTES = 400_000
    MAX_PATCH_BYTES = 1_500_000

    def normalize(self, raw_path: str) -> str:
        value = raw_path.replace("\\", "/").lstrip("/")
        path = PurePosixPath(value)

        if ".." in path.parts:
            raise ValueError("Path traversal is not allowed")
        if not path.parts:
            raise ValueError("Empty path")

        root = path.parts[0]
        if root not in self.ALLOWED_ROOTS:
            raise ValueError(f"Root {root!r} is not writable")

        if any(
            value == prefix or value.startswith(prefix + "/")
            for prefix in self.BLOCKED_PREFIXES
        ):
            raise ValueError("Protected workspace path")

        return str(path)

    def validate_content(self, content: str) -> None:
        if len(content.encode("utf-8")) > self.MAX_FILE_BYTES:
            raise ValueError("Generated file is too large")


class FilePatch(BaseModel):
    path: str
    operation: Literal["create", "replace", "delete"] = "create"
    content: str | None = None


class WorkspacePatch(BaseModel):
    summary: str = ""
    files: list[FilePatch] = Field(default_factory=list)


def apply_workspace_patch(
    workspace_root: Path,
    patch: WorkspacePatch,
    policy: SafeWorkspacePolicy | None = None,
) -> list[str]:
    policy = policy or SafeWorkspacePolicy()

    total_bytes = sum(
        len((item.content or "").encode("utf-8"))
        for item in patch.files
    )
    if total_bytes > policy.MAX_PATCH_BYTES:
        raise ValueError("Patch exceeds size limit")

    root_resolved = workspace_root.resolve()
    changed: list[str] = []

    for item in patch.files:
        relative = policy.normalize(item.path)

        if relative in policy.PROTECTED_FILES:
            raise ValueError(f"Protected file: {relative}")

        target = (workspace_root / relative).resolve()
        target.relative_to(root_resolved)

        if item.operation == "delete":
            if target.exists():
                target.unlink()
        else:
            content = item.content or ""
            policy.validate_content(content)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        changed.append(relative)

    return changed
