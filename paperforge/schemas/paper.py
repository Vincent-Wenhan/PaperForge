"""Paper-related schemas: CapabilityCard."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Metric(BaseModel):
    name: str
    value: str
    context: str = ""


class CapabilityCard(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None

    problem: str = ""
    method: str = ""
    key_innovations: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)

    capability_category: str = ""
    reusable_components: list[str] = Field(default_factory=list)
    product_hints: list[str] = Field(default_factory=list)

    constraints: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
