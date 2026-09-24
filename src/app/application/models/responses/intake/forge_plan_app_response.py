"""app.application.models.responses.intake.forge_plan_app_response -- the DTO
for `forge_plan_app`'s result: today's `BuildPlan`, echoed as ops/summary/
op_count.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.responses.intake.op import Op


class ForgePlanAppResponse(BaseModel):
    """The compiled `BuildPlan`: every op, a per-kind count, and the total."""

    model_config = ConfigDict(frozen=True)

    ops: list[Op]
    summary: dict[str, int]
    op_count: int
