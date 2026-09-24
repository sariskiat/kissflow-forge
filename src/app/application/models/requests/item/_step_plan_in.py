"""app.application.models.requests.item._step_plan_in — one requested walk
step, the element shape of the `steps` parameter on `forge_simulate_case`.

Replaces `app.application.tools.coerce_case_steps` for this tool: Pydantic
validates `name` is a non-blank string and `values`/`comment` carry their
shape checks natively, the same checks the old hand-written coercer ran.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class StepPlanIn(BaseModel):
    """One hop of a `forge_simulate_case` walk: fields to fill, then either
    advance (submit) or, when `reject` is set, reject with `comment`.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    values: dict[str, Any] = {}
    reject: bool = False
    comment: str = ""

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        """Refuse a blank name, the same rule `coerce_case_steps` used to run.

        Args:
            value: The raw `name` field.

        Returns:
            `value`, unchanged.

        Raises:
            ValueError: `value` is empty or all whitespace.
        """
        if not value.strip():
            raise ValueError("name must not be blank — it is the step's activity name")
        return value
