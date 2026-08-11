"""WorkspacePlan schema: a bounded, dependency-aware plan of files."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RouteSpec(BaseModel):
    path: str
    purpose: str


class ComponentSpec(BaseModel):
    path: str
    purpose: str
    reusable: bool = True


class FileSpec(BaseModel):
    path: str
    kind: Literal["route", "component", "hook", "adapter", "type", "fixture", "api"]
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class WorkspacePlan(BaseModel):
    app_name: str
    routes: list[RouteSpec] = Field(default_factory=list)
    components: list[ComponentSpec] = Field(default_factory=list)
    files: list[FileSpec] = Field(default_factory=list)
    dependencies: dict[str, str] = Field(default_factory=dict)
    acceptance_test_ids: list[str] = Field(default_factory=list)
