"""AppManifest schema for generated Next.js apps.

The exact 3-file allowlist (BUSINESS_FILES) is retired in favor of the
bounded SafeWorkspacePolicy (doc 9.2/9.5). ``BusinessFile`` keeps the old
name as a thin subclass so existing imports and the generator's validation
flow keep working while allowing multi-file generation.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator

from paperforge.schemas.workspace_policy import SafeWorkspacePolicy

# Kept for backwards compatibility with prompts/tests that reference it.
# New generation uses SafeWorkspacePolicy.ALLOWED_ROOTS instead of a fixed set.
BUSINESS_FILES: set[str] = set()

# Dependencies the generator is allowed to declare in package.json.
# Anything outside this set is rejected at validation time so a
# compromised or hallucinating model cannot pull arbitrary packages.
ALLOWED_DEPENDENCIES: set[str] = {
    "next",
    "react",
    "react-dom",
    "lucide-react",
    "zod",
    "recharts",
    "date-fns",
}

_policy = SafeWorkspacePolicy()


class AppFile(BaseModel):
    path: str
    content: str
    description: str = ""

    @field_validator("path")
    @classmethod
    def safe_business_path(cls, value: str) -> str:
        return _policy.normalize(value)

    @field_validator("content")
    @classmethod
    def size_limit(cls, value: str) -> str:
        _policy.validate_content(value)
        return value


class AppManifest(BaseModel):
    app_id: str
    prd_id: str | None = None

    files: list[AppFile] = Field(default_factory=list)
    dependencies: dict[str, str] = Field(default_factory=dict)
    scripts: dict[str, str] = Field(default_factory=dict)
    env_example: dict[str, str] = Field(default_factory=dict)

    mock_adapters: list[str] = Field(default_factory=list)
    real_adapters: list[str] = Field(default_factory=list)

    preview_port: int = 3000
    preview_route: str = "/"

    @model_validator(mode="after")
    def validate_manifest(self) -> "AppManifest":
        paths = [f.path for f in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate generated file path")
        unknown = set(self.dependencies) - ALLOWED_DEPENDENCIES
        if unknown:
            raise ValueError(
                f"Dependencies are not allowed: {sorted(unknown)}"
            )
        return self
