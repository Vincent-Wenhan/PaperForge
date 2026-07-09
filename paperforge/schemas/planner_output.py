"""Product planner output schema."""

from __future__ import annotations

from pydantic import BaseModel, Field

from paperforge.schemas.prd import PRD


class PlannerOutput(BaseModel):
    """Wrapper for product planner output.

    If `needs_more_input` is True, `questions` contains clarifying questions
    to ask the user before re-running the planner. If False, `prd` contains
    the generated PRD.
    """

    needs_more_input: bool = False
    questions: list[str] = Field(default_factory=list)
    prd: PRD | None = None
