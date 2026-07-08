"""Composition schema for multi-paper innovation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductConcept(BaseModel):
    name: str
    user_job: str
    target_users: list[str] = Field(default_factory=list)
    value_proposition: str = ""
    mvp_scope: str = ""
    mock_strategy: str = ""


class Composition(BaseModel):
    composition_id: str
    source_cards: list[str] = Field(default_factory=list)

    novel_idea: str = ""
    combination_mechanism: str = ""
    emergent_capability: str = ""

    product_concepts: list[ProductConcept] = Field(default_factory=list)

    technical_risks: list[str] = Field(default_factory=list)
    integration_challenges: list[str] = Field(default_factory=list)
