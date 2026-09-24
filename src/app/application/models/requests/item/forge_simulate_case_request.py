"""app.application.models.requests.item.forge_simulate_case_request — the
`forge_simulate_case` request DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.application.models.requests.item._step_plan_in import StepPlanIn

_STEPS_EXAMPLE = (
    '[{"name": "Manager Approve", "values": {"Urgency": "High"}, "reject": false, '
    '"comment": ""}]'
)


def _shape_error(at: str, got: Any, want: str, example: str) -> ValueError:
    """A caller-recognizable "wrong shape" message.

    Restores `app.application.tools.coerce_case_steps`'s own
    `<path>: expected <want>, got <type> <repr> — correct shape: <example>`
    form (review fix 3), without importing that old module (the shared
    brief forbids it) -- the same approach
    `forge_build_workflow_request.py`'s own `_shape_error` already took.

    Args:
        at: The wire path of the bad value (for example `steps[0]['name']`).
        got: The bad value itself.
        want: A short description of what was expected there.
        example: A correct-shape example, verbatim wire JSON.

    Returns:
        A `ValueError` ready to raise from a field validator.
    """
    return ValueError(
        f"{at}: expected {want}, got {type(got).__name__} {got!r} — "
        f"correct shape: {example}"
    )


class ForgeSimulateCaseRequest(BaseModel):
    """One `forge_simulate_case` call: walk one item through create, fill,
    advance/reject, per `steps`.

    `app_id` is already resolved by the tool: the per-call `app_id`
    argument, else `settings.kf_app`, else `""` (see
    `brief_stage_d_common.md`, "The app id") -- the item routes themselves
    carry no `app_id`, but resolving the flow's field-name index does
    (`FlowRepository.get_draft`).
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    steps: list[StepPlanIn]
    poll: bool = True
    poll_tries: int = 8
    poll_delay: float = 0.9
    app_id: str

    @field_validator("steps", mode="before")
    @classmethod
    def _steps_shape(cls, value: Any) -> Any:
        """Restore `coerce_case_steps`'s own shape-error text (review fix
        3), lost when `StepPlanIn`'s per-field validators replaced it with
        a generic Pydantic message that named neither the step's own index
        nor a correct-shape example.

        Args:
            value: The raw `steps` argument, before Pydantic parses each
                entry into a `StepPlanIn`.

        Returns:
            `value`, unchanged apart from a `None`/missing `values` folded
            to `{}` (`tools.py:502`'s own `step.get("values") or {}`).

        Raises:
            ValueError: `value` is not a list, an entry is not an object,
                or an entry's `name`/`values`/`comment` is the wrong shape
                -- the exact `coerce_case_steps` wording, so this port
                changes no refusal text a caller already depends on.
        """
        if not isinstance(value, list):
            raise _shape_error("steps", value, "a list of walk steps", _STEPS_EXAMPLE)
        checked: list[Any] = []
        for i, step in enumerate(value):
            at = f"steps[{i}]"
            if not isinstance(step, dict):
                raise _shape_error(at, step, "a walk step object", _STEPS_EXAMPLE)
            name = step.get("name")
            if not isinstance(name, str) or not name.strip():
                raise _shape_error(
                    f"{at}['name']", name, "the step's activity name", _STEPS_EXAMPLE
                )
            values = step.get("values") or {}
            if not isinstance(values, dict):
                raise _shape_error(
                    f"{at}['values']",
                    values,
                    "an object of field name (or id) -> value",
                    _STEPS_EXAMPLE,
                )
            comment = step.get("comment", "")
            if not isinstance(comment, str):
                raise _shape_error(
                    f"{at}['comment']", comment, "a comment string", _STEPS_EXAMPLE
                )
            checked.append({**step, "values": values, "comment": comment})
        return checked
