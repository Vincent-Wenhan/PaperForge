"""Self-check for SafeWorkspacePolicy + patch apply (ponytail leave-behind)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from paperforge.schemas.workspace_policy import (
    SafeWorkspacePolicy,
    WorkspacePatch,
    FilePatch,
    apply_workspace_patch,
)


def demo() -> None:
    policy = SafeWorkspacePolicy()

    # traversal / bad root / protected rejected
    for bad in ("../escape.ts", "/etc/passwd", "node_modules/x.ts", "app/../y.ts"):
        try:
            policy.normalize(bad)
        except ValueError:
            continue
        raise AssertionError(f"should reject {bad!r}")
    assert policy.normalize("lib/mock-api.ts") == "lib/mock-api.ts"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        patch = WorkspacePatch(
            summary="add page",
            files=[FilePatch(path="app/page.tsx", content="export default () => null")],
        )
        changed = apply_workspace_patch(root, patch, policy)
        assert changed == ["app/page.tsx"]
        assert (root / "app/page.tsx").exists()

        # protected file refused
        try:
            apply_workspace_patch(
                root,
                WorkspacePatch(files=[FilePatch(path="tsconfig.json", operation="delete")]),
                policy,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("tsconfig.json is protected")

    print("workspace-policy ok")


if __name__ == "__main__":
    demo()
