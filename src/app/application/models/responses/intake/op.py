"""app.application.models.responses.intake.op — one build-plan step: a single Kissflow
write the engine knows how to execute, plus the human-readable reason it exists.

`args` is already a JSON-safe dict by construction — every `_op_*` builder in
`app.application.intake.compile` shapes it that way (enums by `.value`, tuples of pairs,
nested dicts for a page's design tree). `model_dump(mode="json")` is the exact wire form
`app.infrastructure.mcp.server`'s `forge_plan_app` tool hands back to a caller.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Op(BaseModel):
    """One step of a `BuildPlan`: `kind` names the engine operation (one of
    `app.application.intake.compile.OP_ORDER`), `args` are its keyword arguments,
    and `why` is one sentence of human-readable justification traced back to the
    spec.
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    args: dict[str, Any]
    why: str
