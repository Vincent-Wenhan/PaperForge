"""PRD schema for product planning."""

from __future__ import annotations

from pydantic import BaseModel, Field


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

    mock_strategy: str = ""
    data_strategy: str = ""
    performance_targets: dict[str, str] = Field(default_factory=dict)

    ui_style: str = "minimal"
    key_screens: list[str] = Field(default_factory=list)
