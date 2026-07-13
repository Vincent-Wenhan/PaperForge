"""AppManifest schema for generated Next.js apps."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator

# Files the LLM is allowed to generate. Anything else is rejected.
BUSINESS_FILES: set[str] = {
    "app/page.tsx",
    "lib/mock-api.ts",
    "lib/real-api.ts",
}

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


class AppFile(BaseModel):
    path: str
    content: str
    description: str = ""

    @field_validator("path")
    @classmethod
    def safe_business_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").lstrip("/")
        path = PurePosixPath(normalized)
        if ".." in path.parts:
            raise ValueError("Path traversal is not allowed")
        if normalized not in BUSINESS_FILES:
            raise ValueError(
                f"LLM may only generate: {sorted(BUSINESS_FILES)}"
            )
        return normalized

    @field_validator("content")
    @classmethod
    def size_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 300_000:
            raise ValueError("Generated file is too large")
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
