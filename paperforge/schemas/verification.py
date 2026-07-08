"""Verification report schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VerificationReport(BaseModel):
    app_id: str
    prd_id: str | None = None

    build_succeeded: bool = False
    build_errors: list[str] = Field(default_factory=list)
    build_warnings: list[str] = Field(default_factory=list)

    prd_coverage: float = 0.0
    missing_features: list[str] = Field(default_factory=list)
    extra_features: list[str] = Field(default_factory=list)

    mock_adapters_count: int = 0
    real_adapters_count: int = 0
    boundary_clear: bool = False
    boundary_issues: list[str] = Field(default_factory=list)

    type_errors: list[str] = Field(default_factory=list)
    lint_errors: list[str] = Field(default_factory=list)

    security_issues: list[str] = Field(default_factory=list)

    overall_score: float = 0.0
    ready_for_preview: bool = False
    recommendations: list[str] = Field(default_factory=list)
