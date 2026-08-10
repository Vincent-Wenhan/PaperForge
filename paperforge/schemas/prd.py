"""PRD schema for product planning (PRD V2, doc 8.2).

Features carry stable ids and priority; acceptance criteria are executable
(routable/selectable) and every must-have feature requires at least one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Priority = Literal["must", "should", "could"]


class Feature(BaseModel):
    id: str
    name: str
    description: str = ""
    priority: Priority = "should"
    user_value: str = ""
    acceptance_notes: list[str] = Field(default_factory=list)


class AcceptanceCriterion(BaseModel):
    id: str
    feature_id: str
    priority: Priority = "should"
    description: str
    test_kind: Literal["route", "text", "interaction", "api", "visual"] = "interaction"
    route: str = "/"
    selector: str | None = None
    action: Literal["none", "click", "fill", "upload", "select"] = "none"
    input_value: str | None = None
    expected: str | bool | int | float | None = None


class PRD(BaseModel):
    prd_id: str
    composition_id: str | None = None

    product_name: str
    one_liner: str = ""
    target_users: list[str] = Field(default_factory=list)
    user_jobs: list[str] = Field(default_factory=list)
    value_proposition: str = ""

    features: list[Feature] = Field(default_factory=list)
    wont_have: list[str] = Field(default_factory=list)

    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)

    mock_strategy: str = ""
    data_strategy: str = ""
    performance_targets: dict[str, str] = Field(default_factory=dict)

    ui_style: str = "minimal"
    key_screens: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_executable_acceptance(self) -> "PRD":
        feature_ids = {feature.id for feature in self.features}
        criteria_by_feature: dict[str, list[AcceptanceCriterion]] = {}
        for criterion in self.acceptance_criteria:
            if criterion.feature_id not in feature_ids:
                raise ValueError(
                    f"Acceptance criterion {criterion.id!r} references "
                    f"unknown feature {criterion.feature_id!r}"
                )
            criteria_by_feature.setdefault(criterion.feature_id, []).append(criterion)

        missing_must = [
            feature.id
            for feature in self.features
            if feature.priority == "must" and not criteria_by_feature.get(feature.id)
        ]
        if missing_must:
            raise ValueError(
                "Every must-have feature needs at least one executable "
                "acceptance criterion: " + ", ".join(missing_must)
            )
        return self
