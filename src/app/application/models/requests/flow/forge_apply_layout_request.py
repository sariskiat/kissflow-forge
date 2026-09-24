"""app.application.models.requests.flow.forge_apply_layout_request — the DTO for
`forge_apply_layout` (today's `server.py`: `apply_layout`, `client.py`): re-place
every field at exact grid coordinates.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from app.domain.value_objects.kinds import FlowKindArg

_LAYOUT_EXAMPLE = '{"Case Info": [[["Ticket No", 0, 3], ["Urgency", 3, 6]]]}'


def _shape_error(at: str, got: Any, want: str) -> ValueError:
    """A caller-recognizable "wrong shape" message.

    Ports `app.application.tools._shape_error`'s own
    `<path>: expected <want>, got <type> <repr> — correct shape: <example>`
    form, without importing that old module (the shared brief forbids it).

    Args:
        at: The wire path of the bad value (for example `layout['Sec'][0]`).
        got: The bad value itself.
        want: A short description of what was expected there.

    Returns:
        A `ValueError` ready to raise from a field validator.
    """
    return ValueError(
        f"{at}: expected {want}, got {type(got).__name__} {got!r} — "
        f"correct shape: {_LAYOUT_EXAMPLE}"
    )


class ForgeApplyLayoutRequest(BaseModel):
    """One `forge_apply_layout` call.

    `app_id` is already resolved by the tool: the per-call `app_id` argument,
    else `settings.kf_app`, else `""` (see `brief_stage_d_common.md`, "The
    app id").
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    layout: dict[str, list[list[tuple[str, int, int]]]]
    descriptions: dict[str, str] | None = None
    kind: FlowKindArg = "process"
    publish: bool = False
    app_id: str

    @field_validator("layout", mode="before")
    @classmethod
    def _validate_layout_shape(cls, value: Any) -> Any:
        """Replace `app.application.tools.coerce_layout`'s shape checks.

        Only the SHAPE is checked here — the grid itself (0 <= Start < End
        <= 6, no overlap within a row) is `validate_layout_spans`'/
        `FlowDraft.apply_exact_layout`'s own first statement, so a
        legal-shaped but off-grid span is still refused before any write
        (see `app.application.use_cases.flow.forge_apply_layout`).

        Args:
            value: The raw `layout` argument.

        Returns:
            `value`, unchanged — Pydantic converts each now-validated
            `[name, Start, End]` list into a `(name, Start, End)` tuple on
            its own, against this field's declared type.

        Raises:
            ValueError: `value` is not `{section: [[[name, Start, End],
                ...], ...]}`, or a Start/End is a bool (deliberately
                excluded even though `bool` is an `int` subclass — the same
                exclusion the old coercer ran).
        """
        if not isinstance(value, dict):
            raise _shape_error(
                "layout", value, "an object of section title -> list of rows"
            )
        for section, rows in value.items():
            if not isinstance(rows, list):
                raise _shape_error(
                    f"layout[{section!r}]", rows, "a list of rows, top to bottom"
                )
            for ri, row in enumerate(rows):
                if not isinstance(row, list):
                    raise _shape_error(
                        f"layout[{section!r}][{ri}]",
                        row,
                        "a list of [field_name, Start, End] triples",
                    )
                for ci, cell in enumerate(row):
                    _validate_cell(section, ri, ci, cell)
        return value


def _validate_cell(section: str, ri: int, ci: int, cell: Any) -> None:
    """Validate one `[field_name, Start, End]` cell.

    Args:
        section: The section title the cell belongs to, for the message.
        ri: The row index, for the message.
        ci: The cell index within the row, for the message.
        cell: The raw cell value.

    Raises:
        ValueError: `cell` is not a 3-element `[name, Start, End]` list, the
            name is blank, or a Start/End is not a whole grid unit.
    """
    at = f"layout[{section!r}][{ri}][{ci}]"
    if not isinstance(cell, (list, tuple)) or len(cell) != 3:
        raise _shape_error(at, cell, "a [field_name, Start, End] triple")
    name, start, end = cell
    if not isinstance(name, str) or not name.strip():
        raise _shape_error(f"{at}[0]", name, "a field name")
    for label, n in (("Start", start), ("End", end)):
        if isinstance(n, bool) or not isinstance(n, int):
            raise _shape_error(f"{at} {label}", n, "a whole grid unit (0..6)")
