"""Composition schema for multi-paper innovation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductCandidate(BaseModel):
    """A distinct product direction derived from composition."""

    candidate_id: str
    name: str
    target_user: str = ""
    user_job: str = ""
    value_proposition: str = ""
    paper_capabilities_used: list[str] = Field(default_factory=list)
    mock_strategy: str = ""
    real_integration_boundary: str = ""
    feasibility_score: float = 0.0
    novelty_score: float = 0.0
    risk_score: float = 0.0


class Composition(BaseModel):
    composition_id: str
    source_cards: list[str] = Field(default_factory=list)

    novel_idea: str = ""
    combination_mechanism: str = ""
    emergent_capability: str = ""

    product_candidates: list[ProductCandidate] = Field(default_factory=list)

    technical_risks: list[str] = Field(default_factory=list)
    integration_challenges: list[str] = Field(default_factory=list)
