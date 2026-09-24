"""app.application.models.requests.flow.forge_add_field_validation_request —
the `forge_add_field_validation` request DTO.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.value_objects.kinds import FlowKind

_RULES_EXAMPLE = '{"meeting link": [["CONTAINS", "microsoft"]]}'


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
        param: The failing parameter path (for example `"rules['f'][0]"`).
        got: The value that was rejected.
        want: A short description of the expected shape.

    Returns:
        The formatted refusal text, naming `param`, `want`, `got`'s own
        repr, and the correct-shape example.
    """
    return (
        f"{param}: expected {want}, got {type(got).__name__} {_brief(got)} — "
        f"correct shape: {_RULES_EXAMPLE}"
    )


class ForgeAddFieldValidationRequest(BaseModel):
    """Shape for `forge_add_field_validation`: `rules` maps a field name to
    its `[operator, value]` rules.

    A plain `dict[str, list[tuple[str, str]]]` field type already rejects
    every wrong SHAPE `tools.coerce_validation_rules` used to (not a dict,
    not a list of rules, a rule of the wrong length or element type) with a
    Pydantic `ValidationError` -- but with Pydantic's own generic
    "too_long"/"missing" text, not `coerce_validation_rules`'s own message
    naming the correct shape (`brief_stage_d_common.md` review, fix 5). The
    `mode="before"` validator below runs first and raises that same text
    verbatim for the one case reviewed live: a rule that is not a 2-element
    pair.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    rules: dict[str, list[tuple[str, str]]]
    kind: FlowKind = "process"
    publish: bool = False
    app_id: str

    @field_validator("rules", mode="before")
    @classmethod
    def _rules_are_shaped(cls, value: Any) -> Any:
        """Refuse a malformed rule with `coerce_validation_rules`'s own text.

        Args:
            value: The raw `rules` mapping, before Pydantic's own dict/tuple
                coercion runs.

        Returns:
            `value`, unchanged -- Pydantic's own type coercion still runs on
            it afterwards.

        Raises:
            ValueError: A field's rules are not a list, or a rule is not a
                2-element `[operator, value]` pair of strings.
        """
        if not isinstance(value, dict):
            return value
        for field, rules in value.items():
            if not isinstance(rules, list):
                raise ValueError(
                    _shape_msg(
                        f"rules[{field!r}]", rules, "a list of [operator, value] rules"
                    )
                )
            for i, rule in enumerate(rules):
                at = f"rules[{field!r}][{i}]"
                if not isinstance(rule, (list, tuple)) or len(rule) != 2:
                    raise ValueError(_shape_msg(at, rule, "an [operator, value] pair"))
                if not all(isinstance(x, str) for x in rule):
                    raise ValueError(
                        _shape_msg(at, rule, "an [operator, value] pair of two strings")
                    )
        return value
