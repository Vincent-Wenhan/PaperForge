"""PRD schema for product planning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AcceptanceCriterion(BaseModel):
    """Executable acceptance criterion mapped to a PRD feature.

    Each criterion is bound to a feature via ``feature_id`` and carries
    enough metadata for a browser/smoke test runner to verify it without
    further LLM calls.
    """

    id: str
    feature_id: str
    priority: Literal["must", "should", "could"] = "should"
    description: str
    test_kind: Literal["route", "text", "interaction", "visual", "api"] = "interaction"
    selector: str | None = None
    expected: str | bool | int | float | None = None


class Feature(BaseModel):
    name: str
    description: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)


class PRD(BaseModel):
    prd_id: str
    composition_id: str | None = None

    product_name: str
    one_liner: str = ""
    target_users: list[str] = Field(default_factory=list)
    user_jobs: list[str] = Field(default_factory=list)
    value_proposition: str = ""

    must_have: list[Feature] = Field(default_factory=list)
    should_have: list[Feature] = Field(default_factory=list)
    could_have: list[Feature] = Field(default_factory=list)
    wont_have: list[str] = Field(default_factory=list)

    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)

    mock_strategy: str = ""
    data_strategy: str = ""
    performance_targets: dict[str, str] = Field(default_factory=dict)

    ui_style: str = "minimal"
    key_screens: list[str] = Field(default_factory=list)
