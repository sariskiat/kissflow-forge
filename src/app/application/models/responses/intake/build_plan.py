"""app.application.models.responses.intake.build_plan — the ordered list of `Op` the
engine executes to build one app, compiled by
`app.application.intake.compile.compile_spec`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.application.models.responses.intake.op import Op


class BuildPlan(BaseModel):
    """An ordered, executable plan. `ops` is always in the proven build order
    (`app.application.intake.compile.OP_ORDER`) regardless of what order the
    spec's own dimensions happened to be filled in.
    """

    model_config = ConfigDict(frozen=True)

    ops: tuple[Op, ...]

    def summary(self) -> dict[str, int]:
        """Op count per kind — always reconciles with `ops` because it's
        computed FROM `ops`, never tracked separately (the output-invariant
        audit this module owes its own caller)."""
        counts: dict[str, int] = {}
        for op in self.ops:
            counts[op.kind] = counts.get(op.kind, 0) + 1
        return counts
