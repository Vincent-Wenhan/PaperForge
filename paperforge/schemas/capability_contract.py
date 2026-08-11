"""CapabilityContract and ParseCoverage schemas.

A CapabilityContract is the typed boundary of a paper-derived capability:
what it takes in, what it produces, its preconditions/failure modes, how it
integrates (mock vs real), and an optional confidence score. ParseCoverage
makes implicit PDF truncation explicit so we never silently drop paper content.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CapabilityInput(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str = ""


class CapabilityOutput(BaseModel):
    name: str
    type: str
    description: str = ""


class ImplementationReference(BaseModel):
    kind: Literal["github", "project_page", "dataset", "model", "api", "paper"]
    url: str
    label: str = ""


class CapabilityContract(BaseModel):
    name: str
    description: str

    inputs: list[CapabilityInput] = Field(default_factory=list)
    outputs: list[CapabilityOutput] = Field(default_factory=list)

    preconditions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)

    expected_latency: str | None = None

    compute_requirements: list[str] = Field(default_factory=list)

    integration_mode: Literal["mock", "local_model", "remote_api", "unknown"] = "unknown"

    implementation_refs: list[ImplementationReference] = Field(default_factory=list)

    confidence: float = 0.0


class ParseCoverage(BaseModel):
    """Explicit record of how much of a PDF was actually processed."""

    total_pages: int
    processed_pages: list[int] = Field(default_factory=list)
    omitted_pages: list[int] = Field(default_factory=list)
    complete: bool = True
