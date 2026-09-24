"""Unit tests for app.domain.value_objects.field_type.

FieldType/EventTrigger/Visibility/FlowType are closed StrEnums with wire strings
pinned by a live capture (CLAUDE.md THE RULE); `trigger_for` is the one derivation
table both the intake spec layer and the live write path share. Pure + offline: no
network, no Kissflow calls.
"""

from __future__ import annotations

import pytest

from app.domain.value_objects.field_type import (
    NO_EVENT_FIELD_TYPES,
    TRIGGER_LIVE_CONFIRMED,
    EventTrigger,
    FieldType,
    FlowType,
    Visibility,
    trigger_for,
)


def test_field_type_wire_strings() -> None:
    assert FieldType.TEXT.value == "Text"
    assert FieldType.TEXTAREA.value == "Textarea"
    assert FieldType.DATE.value == "Date"
    assert FieldType.DATETIME.value == "DateTime"
    assert FieldType.BOOLEAN.value == "Boolean"
    assert FieldType.SELECT.value == "Select"
    assert FieldType.USER.value == "User"
    assert FieldType.NUMBER.value == "Number"
    assert FieldType.ATTACHMENT.value == "Attachment"


def test_event_trigger_wire_strings() -> None:
    assert EventTrigger.ON_CHANGE.value == "onChange"
    assert EventTrigger.ON_SELECT.value == "onSelect"
    assert EventTrigger.ON_CLICK.value == "onClick"


def test_trigger_live_confirmed_is_the_five_live_observed_types() -> None:
    assert {
        FieldType.TEXT,
        FieldType.TEXTAREA,
        FieldType.DATE,
        FieldType.NUMBER,
        FieldType.SELECT,
    } == TRIGGER_LIVE_CONFIRMED


def test_no_event_field_types_has_five_not_six() -> None:
    # "Rich text" is deliberately absent (its inferred shape is indistinguishable from
    # a plain Textarea, which DOES fire onChange) -- see field_type.py's own docstring
    # note.
    assert len(NO_EVENT_FIELD_TYPES) == 5
    assert "Rich text" not in NO_EVENT_FIELD_TYPES
    assert {
        "Attachment",
        "Image",
        "Signature",
        "SequenceNumber",
        "Geolocation",
    } == NO_EVENT_FIELD_TYPES


def test_trigger_for_covers_every_field_type_or_refuses_by_name() -> None:
    """`trigger_for` is declared to return an EventTrigger, and its callers do
    `trigger_for(t).value`. Its match had no default, so FieldType.DATETIME — a real
    member, absent from the other cases — fell through and returned None implicitly:
    callers got an opaque `AttributeError: 'NoneType' has no attribute 'value'`, several
    frames from the cause.

    The fix is a refusal, not a guess. DATETIME is deliberately absent from
    TRIGGER_LIVE_CONFIRMED, and inferring onSelect from the Date family is exactly the
    uncaptured guess CLAUDE.md's THE RULE exists to stop.

    This walks EVERY member so a field type added later cannot reintroduce the silent
    None: each one must either return a real EventTrigger or raise a ValueError that
    names it.
    """
    for t in FieldType:
        try:
            got = trigger_for(t)
        except ValueError as e:
            assert t.value in str(e), f"{t}: refusal must name the type it refused"
            continue
        assert isinstance(got, EventTrigger), (
            f"{t}: returned {got!r}, not an EventTrigger"
        )

    # The specific regression: DateTime refuses loudly instead of returning None.
    with pytest.raises(ValueError, match="DateTime"):
        trigger_for(FieldType.DATETIME)


def test_trigger_for_attachment_refuses_by_name() -> None:
    with pytest.raises(ValueError, match="Attachment"):
        trigger_for(FieldType.ATTACHMENT)


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (FieldType.TEXT, EventTrigger.ON_CHANGE),
        (FieldType.TEXTAREA, EventTrigger.ON_CHANGE),
        (FieldType.DATE, EventTrigger.ON_SELECT),
        (FieldType.NUMBER, EventTrigger.ON_SELECT),
        (FieldType.USER, EventTrigger.ON_SELECT),
        (FieldType.SELECT, EventTrigger.ON_CLICK),
        (FieldType.BOOLEAN, EventTrigger.ON_CLICK),
    ],
)
def test_trigger_for_the_live_observed_mapping(
    t: FieldType, expected: EventTrigger
) -> None:
    assert trigger_for(t) is expected


def test_visibility_wire_strings() -> None:
    assert Visibility.EDITABLE.value == "Editable"
    assert Visibility.READONLY.value == "ReadOnly"
    assert Visibility.HIDDEN.value == "Hidden"
    assert len(list(Visibility)) == 3


def test_flow_type_wire_strings() -> None:
    assert FlowType.FORM.value == "form"
    assert FlowType.PROCESS.value == "process"
    assert FlowType.CASE.value == "case"
