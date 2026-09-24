"""Spec for app.application.models.requests.flow.forge_apply_layout_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_apply_layout_request import (
    ForgeApplyLayoutRequest,
)


def _layout(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "flow_id": "F1",
        "layout": {"Case Info": [[["Ticket No", 0, 3], ["Urgency", 3, 6]]]},
        "app_id": "A1",
    }
    base.update(overrides)
    return base


def test_converts_the_wire_triples_into_tuples() -> None:
    req = ForgeApplyLayoutRequest.model_validate(_layout())
    assert req.layout == {"Case Info": [[("Ticket No", 0, 3), ("Urgency", 3, 6)]]}
    assert req.kind == "process"
    assert req.publish is False
    assert req.descriptions is None


def test_carries_descriptions_kind_and_publish() -> None:
    req = ForgeApplyLayoutRequest.model_validate(
        _layout(
            descriptions={"Case Info": "About this case"},
            kind="form",
            publish=True,
        )
    )
    assert req.descriptions == {"Case Info": "About this case"}
    assert req.kind == "form"
    assert req.publish is True


def test_rejects_a_layout_that_is_not_an_object() -> None:
    with pytest.raises(ValidationError, match="expected an object"):
        ForgeApplyLayoutRequest.model_validate(_layout(layout=["nope"]))


def test_rejects_a_section_whose_rows_are_not_a_list() -> None:
    with pytest.raises(ValidationError, match="expected a list of rows"):
        ForgeApplyLayoutRequest.model_validate(_layout(layout={"Case Info": "nope"}))


def test_rejects_a_row_that_is_not_a_list() -> None:
    with pytest.raises(ValidationError, match="expected a list of"):
        ForgeApplyLayoutRequest.model_validate(_layout(layout={"Case Info": ["nope"]}))


def test_rejects_a_cell_with_the_wrong_number_of_elements() -> None:
    with pytest.raises(ValidationError, match="Start, End. triple"):
        ForgeApplyLayoutRequest.model_validate(
            _layout(layout={"Case Info": [[["Ticket No", 0]]]})
        )


def test_rejects_a_blank_field_name() -> None:
    with pytest.raises(ValidationError, match="expected a field name"):
        ForgeApplyLayoutRequest.model_validate(
            _layout(layout={"Case Info": [[["  ", 0, 3]]]})
        )


def test_rejects_a_non_integer_start() -> None:
    with pytest.raises(ValidationError, match="whole grid unit"):
        ForgeApplyLayoutRequest.model_validate(
            _layout(layout={"Case Info": [[["Ticket No", "0", 3]]]})
        )


def test_rejects_a_bool_start_even_though_bool_is_an_int_subclass() -> None:
    """The one deliberate divergence from a bare `tuple[str, int, int]` field: `True`/
    `False` must not silently become grid position 1/0 (mirrors the old
    `coerce_layout`)."""
    with pytest.raises(ValidationError, match="whole grid unit"):
        ForgeApplyLayoutRequest.model_validate(
            _layout(layout={"Case Info": [[["Ticket No", True, 3]]]})
        )


def test_every_shape_error_names_what_it_actually_got() -> None:
    """Restores `app.application.tools._shape_error`'s `got <type> <value>`
    part, lost when this DTO stopped calling it (brief_d13_fix.md fix 6): a
    caller debugging a bad `layout` needs to see what it actually sent, not
    just what was wanted."""
    with pytest.raises(ValidationError) as exc_info:
        ForgeApplyLayoutRequest.model_validate(_layout(layout=["nope"]))
    message = str(exc_info.value)
    assert "got list ['nope']" in message

    with pytest.raises(ValidationError) as exc_info:
        ForgeApplyLayoutRequest.model_validate(
            _layout(layout={"Case Info": [[["  ", 0, 3]]]})
        )
    message = str(exc_info.value)
    assert "got str '  '" in message

    with pytest.raises(ValidationError) as exc_info:
        ForgeApplyLayoutRequest.model_validate(
            _layout(layout={"Case Info": [[["Ticket No", "0", 3]]]})
        )
    message = str(exc_info.value)
    assert "got str '0'" in message


def test_is_frozen() -> None:
    req = ForgeApplyLayoutRequest.model_validate(_layout())
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
