"""app.application.models.requests.flow.forge_build_workflow_request — the
request DTO for `forge_build_workflow`.

`steps`/`parallel` replace `app.application.tools`'s old `coerce_workflow_steps`/
`coerce_parallel`. `steps` arrives over the wire as `[[name, role], ...]`, which
Pydantic already coerces positionally into `list[Step]` (`FlowDraft`'s own type
alias -- a workflow step shape is a domain concept, not one this DTO
re-invents), rejecting a wrong-length pair or a non-string name/role on its
own. `parallel` arrives as an OBJECT (`{"name": ..., "branches": [...]}`), so a
`mode="before"` validator reshapes it into the `(name, branches)` tuple
`ParallelSpec` expects before Pydantic's own tuple coercion runs over it. Both
fields get one more check no type hint alone expresses: a step or branch name
that is present but blank.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from app.domain.entities.flow_draft import ParallelSpec, Step
from app.domain.value_objects.kinds import FlowKind

_STEPS_EXAMPLE = '[["Manager Approve", "AppRole_ab12"], ["Finance Check", null]]'
_PARALLEL_EXAMPLE = (
    '{"name": "Route", "branches": [["Standard", [["Approve", null]]], '
    '["Express", [["Fast Approve", null]]]]}'
)


def _shape_error(at: str, got: Any, want: str, example: str) -> ValueError:
    """A caller-recognizable "wrong shape" message.

    Ports `app.application.tools._shape_error`'s own
    `<path>: expected <want>, got <type> <repr> — correct shape: <example>`
    form, without importing that old module (the shared brief forbids it).

    Args:
        at: The wire path of the bad value (for example `steps[0][0]`).
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


class ForgeBuildWorkflowRequest(BaseModel):
    """One `forge_build_workflow` call: replace the whole workflow.

    Attributes:
        flow_id: The flow to rebuild.
        steps: `[(step name, app-role id or None), ...]`.
        parallel: `(gateway name, [(branch name, [(step, role), ...]), ...])`,
            or `None` for a plain sequential chain.
        parallel_after: The 0-indexed position into `steps` the `parallel`
            gateway follows.
        roles: `{role id: display name}`, used to label each step's assignee.
        step_meta: `{step name: {"suspended": bool, "description": str}}`.
        kind: The flow kind.
        publish: Publish the flow once the workflow is written and verified.
        app_id: The resolved application id (see the shared brief's "The app
            id"). Empty means "no app selected".
    """

    flow_id: str
    steps: list[Step]
    parallel: ParallelSpec | None = None
    parallel_after: int | None = None
    roles: dict[str, str] | None = None
    step_meta: dict[str, dict[str, Any]] | None = None
    kind: FlowKind = "process"
    publish: bool = False
    app_id: str = ""

    @field_validator("steps")
    @classmethod
    def _steps_are_named(cls, value: list[Step]) -> list[Step]:
        for i, (name, _role) in enumerate(value):
            if not name.strip():
                raise _shape_error(
                    f"steps[{i}][0]", name, "a step name", _STEPS_EXAMPLE
                )
        return value

    @field_validator("parallel", mode="before")
    @classmethod
    def _parallel_from_wire_object(cls, value: Any) -> Any:
        """`parallel` arrives as `{"name": ..., "branches": [...]}`, never as a bare
        `[name, branches]` pair -- reshape it into that tuple here, before Pydantic's
        own `ParallelSpec` (`tuple[str, list[Branch]]`) coercion runs over it."""
        if value is None or not isinstance(value, dict):
            return value
        if not value:
            # The old tool passed `parallel or None`, so an empty dict meant
            # "no gateway", the same as omitting the parameter.
            return None
        return (value.get("name"), value.get("branches"))

    @field_validator("parallel")
    @classmethod
    def _parallel_is_named(cls, value: ParallelSpec | None) -> ParallelSpec | None:
        if value is None:
            return value
        gateway_name, branches = value
        if not gateway_name.strip():
            raise _shape_error(
                "parallel['name']",
                gateway_name,
                "the Parallel gateway's name",
                _PARALLEL_EXAMPLE,
            )
        for i, (branch_name, steps) in enumerate(branches):
            at = f"parallel['branches'][{i}]"
            if not branch_name.strip():
                raise _shape_error(
                    f"{at}[0]", branch_name, "a branch name", _PARALLEL_EXAMPLE
                )
            for j, (step_name, _role) in enumerate(steps):
                if not step_name.strip():
                    raise _shape_error(
                        f"{at}[1][{j}][0]", step_name, "a step name", _STEPS_EXAMPLE
                    )
        return value
