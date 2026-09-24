"""app.application.models.requests.page.forge_build_page_request — the
`forge_build_page` request DTO.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.application.models.requests.page._page_build_step_in import (
    PageBuildStepIn,
)

_STEPS_EXAMPLE = (
    '[{"kind": "widget", "kwargs": {"container_id": "Container001", '
    '"widget": "general/button"}}]'
)


def _shape_error(at: str, got: Any, want: str, example: str) -> ValueError:
    """A caller-recognizable "wrong shape" message.

    Restores `app.application.tools.coerce_page_steps`'s own
    `<path>: expected <want>, got <type> <repr> — correct shape: <example>`
    form (review fix 3), without importing that old module (the shared
    brief forbids it) -- the same approach
    `forge_build_workflow_request.py`'s own `_shape_error` already took.

    Args:
        at: The wire path of the bad value (for example `steps[0]['kind']`).
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


class ForgeBuildPageRequest(BaseModel):
    """One `forge_build_page` call. Two entries, exactly one required:
    `op` (the governed path) or `steps` + `page_id` (the raw primitive).

    `steps` stays a raw `list[dict]` at the tool boundary (HR3); each entry
    is parsed into a `PageBuildStepIn` here, replacing `app.application.
    tools.coerce_page_steps`.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    page_id: str | None = None
    steps: list[PageBuildStepIn] | None = None
    publish: bool = False
    op: dict[str, Any] | None = None

    @field_validator("steps", mode="before")
    @classmethod
    def _steps_shape(cls, value: Any) -> Any:
        """Restore `coerce_page_steps`'s own shape-error text (review fix
        3), lost when `PageBuildStepIn`'s per-field validators replaced it
        with a generic Pydantic message that named neither the step's own
        index nor a correct-shape example.

        Args:
            value: The raw `steps` argument (or `None`, the raw primitive
                entry not in use), before Pydantic parses each entry into a
                `PageBuildStepIn`.

        Returns:
            `value`, unchanged apart from a `None` `kwargs` folded to `{}`
            (`coerce_page_steps`'s own `if kwargs is None: kwargs = {}`).

        Raises:
            ValueError: `value` is not a list, an entry is not an object,
                or an entry's `kind`/`kwargs` is the wrong shape -- the
                exact `coerce_page_steps` wording, so this port changes no
                refusal text a caller already depends on.
        """
        if value is None:
            return None
        if not isinstance(value, list):
            raise _shape_error(
                "steps", value, "a list of {kind, kwargs} build steps", _STEPS_EXAMPLE
            )
        checked: list[Any] = []
        for i, step in enumerate(value):
            at = f"steps[{i}]"
            if not isinstance(step, dict):
                raise _shape_error(
                    at, step, "a {kind, kwargs} build step", _STEPS_EXAMPLE
                )
            kind = step.get("kind")
            if not isinstance(kind, str) or not kind.strip():
                raise _shape_error(
                    f"{at}['kind']",
                    kind,
                    "one of container|widget|popup|event|style|bind|design",
                    _STEPS_EXAMPLE,
                )
            kwargs = step.get("kwargs", {})
            if kwargs is None:
                kwargs = {}
            if not isinstance(kwargs, dict):
                raise _shape_error(
                    f"{at}['kwargs']",
                    kwargs,
                    "an object of arguments for that builder",
                    _STEPS_EXAMPLE,
                )
            checked.append({**step, "kwargs": kwargs})
        return checked

    @model_validator(mode="after")
    def _exactly_one_entry(self) -> Self:
        """Enforce the two-entry contract server.py's tool body used to run.

        Returns:
            `self`, unchanged.

        Raises:
            ValueError: Neither or both of `op`/`steps` were given, or
                `steps` was given with no `page_id`.
        """
        if (self.op is None) == (self.steps is None):
            raise ValueError(
                "pass exactly one of 'op' (governed compiled build_page op) "
                "or 'steps' (+ 'page_id', raw primitive)"
            )
        if self.steps is not None and not self.page_id:
            raise ValueError("'steps' entry requires 'page_id'")
        return self
