"""app.application.models.requests.flow.forge_set_events_request — the
`forge_set_events` request DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.value_objects.kinds import FlowKind

_EVENTS_EXAMPLE = '{"Total": [[null, "kf.form.getField(\'Total\')"]]}'


def _brief(value: Any, limit: int = 120) -> str:
    """A repr short enough to belong in an error message.

    Ports `app.application.tools._brief` verbatim.

    Args:
        value: The value to render.
        limit: The character cap before truncation.

    Returns:
        `repr(value)`, truncated with an ellipsis past `limit` characters.
    """
    s = repr(value)
    return s if len(s) <= limit else s[:limit] + "…"


def _shape_msg(param: str, got: Any, want: str) -> str:
    """Port `app.application.tools._shape_error`'s own message text verbatim.

    Args:
        param: The failing parameter path (for example `"events['f'][0]"`).
        got: The value that was rejected.
        want: A short description of the expected shape.

    Returns:
        The formatted refusal text, naming `param`, `want`, `got`'s own
        repr, and the correct-shape example.
    """
    return (
        f"{param}: expected {want}, got {type(got).__name__} {_brief(got)} — "
        f"correct shape: {_EVENTS_EXAMPLE}"
    )


class ForgeSetEventsRequest(BaseModel):
    """Shape for `forge_set_events`: `events` maps a field name to its
    `[trigger, script]` pairs.

    A plain `dict[str, list[tuple[str | None, str]]]` field type already
    rejects every wrong SHAPE `tools.coerce_events` used to (not a dict, not
    a list of pairs, a pair of the wrong length, a non-string script) with a
    Pydantic `ValidationError` -- but with Pydantic's own generic
    "too_long"/"missing"/"string_type" text, not `coerce_events`'s own
    message naming the correct shape (`brief_stage_d_common.md` review, fix
    5). The `mode="before"` validator below runs first and raises that same
    text verbatim. A `None` (or, over the wire, `""`) trigger is legal -- it
    means "derive it from the source field's live type", resolved in the
    use case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    events: dict[str, list[tuple[str | None, str]]]
    kind: FlowKind = "process"
    publish: bool = False
    app_id: str

    @field_validator("events", mode="before")
    @classmethod
    def _events_are_shaped(cls, value: Any) -> Any:
        """Refuse a malformed event spec with `coerce_events`'s own text.

        Args:
            value: The raw `events` mapping, before Pydantic's own
                dict/tuple coercion runs.

        Returns:
            `value`, unchanged -- Pydantic's own type coercion still runs on
            it afterwards.

        Raises:
            ValueError: A field's events are not a list, a pair is not
                exactly `[trigger, script]`, the trigger is neither `None`
                nor a string, or the script is not a string.
        """
        if not isinstance(value, dict):
            return value
        for field, specs in value.items():
            if not isinstance(specs, list):
                raise ValueError(
                    _shape_msg(
                        f"events[{field!r}]", specs, "a list of [trigger, script] pairs"
                    )
                )
            for i, spec in enumerate(specs):
                at = f"events[{field!r}][{i}]"
                if not isinstance(spec, (list, tuple)) or len(spec) != 2:
                    raise ValueError(
                        _shape_msg(
                            at,
                            spec,
                            "a [trigger, script] pair — pass null for the "
                            "trigger to derive it from the field's live type",
                        )
                    )
                trigger, script = spec
                if trigger is not None and not isinstance(trigger, str):
                    raise ValueError(
                        _shape_msg(
                            f"{at}[0]",
                            trigger,
                            "a trigger string, or null to derive it",
                        )
                    )
                if not isinstance(script, str):
                    raise ValueError(
                        _shape_msg(f"{at}[1]", script, "the event script source")
                    )
        return value
