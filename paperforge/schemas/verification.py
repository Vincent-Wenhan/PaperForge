"""Verification report schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VerificationGates(BaseModel):
    """Hard gates. A gate failure cannot be overridden by an overall score."""

    workspace_ok: bool = False
    typecheck_ok: bool = False
    build_ok: bool = False
    lint_ok: bool = False
    security_ok: bool = False
    runtime_ok: bool | None = None
    acceptance_ok: bool | None = None

    @property
    def technical_ready(self) -> bool:
        return all([self.workspace_ok, self.typecheck_ok, self.build_ok, self.security_ok])

    @property
    def preview_allowed(self) -> bool:
        return self.workspace_ok and self.build_ok

    @property
    def product_ready(self) -> bool:
        return (
            self.technical_ready
            and self.runtime_ok is True
            and self.acceptance_ok is True
        )


class VerificationReport(BaseModel):
    app_id: str
    prd_id: str | None = None
    layers: list[dict] = Field(default_factory=list)
    build_environment: str = "local"
    build_degraded: bool = False
    build_fallback_reason: str | None = None
    runtime_status: str = "pending"
    acceptance_status: str = "pending"
    browser_smoke: dict = Field(default_factory=dict)

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

    gates: VerificationGates = Field(default_factory=VerificationGates)
    technical_ready: bool = False
    preview_allowed: bool = False
    product_ready: bool = False

    overall_score: float = 0.0
    ready_for_preview: bool = False
    recommendations: list[str] = Field(default_factory=list)
