"""AppManifest schema for generated Next.js apps."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AppFile(BaseModel):
    path: str
    content: str
    description: str = ""


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
