"""`_events`: `resolve_event_triggers`, the trigger-derivation helper
`ForgeSetEvents` uses. Ported from `tests/test_client.py`'s
`apply_field_events` derivation cases (pre-refactor)."""

from __future__ import annotations

import pytest

from app.application.use_cases.flow._events import resolve_event_triggers


def _field(fid: str, name: str, ftype: str) -> dict:
    return {fid: {"Kind": "Field", "Name": name, "Type": ftype}}


def test_derives_onclick_for_a_select_source() -> None:
    draft = _field("F1", "Route", "Select")
    plan = resolve_event_triggers(draft, {"Route": [(None, "kf.x();")]})
    assert plan.events == {"Route": [("onClick", "kf.x();")]}
    assert plan.derived == ("Route",)
    assert plan.triggers == ("Route (Select) -> onClick",)
    assert plan.unverified == ()


@pytest.mark.parametrize(
    "ftype,trigger",
    [
        ("Text", "onChange"),
        ("Textarea", "onChange"),
        ("Date", "onSelect"),
        ("Number", "onSelect"),
        ("Select", "onClick"),
    ],
)
def test_derives_every_live_confirmed_trigger(ftype: str, trigger: str) -> None:
    draft = _field("F1", "Src", ftype)
    plan = resolve_event_triggers(draft, {"Src": [(None, "kf.x();")]})
    assert plan.events == {"Src": [(trigger, "kf.x();")]}
    assert plan.unverified == ()


def test_refuses_a_stated_trigger_that_disagrees_with_the_derived_one() -> None:
    draft = _field("F1", "Route", "Select")
    with pytest.raises(ValueError, match="onClick") as exc_info:
        resolve_event_triggers(draft, {"Route": [("onChange", "kf.x();")]})
    assert "onChange" in str(exc_info.value)


def test_accepts_an_explicit_trigger_that_agrees() -> None:
    draft = _field("F1", "Note", "Text")
    plan = resolve_event_triggers(draft, {"Note": [("onChange", "kf.x();")]})
    assert plan.events == {"Note": [("onChange", "kf.x();")]}
    assert plan.derived == ()
    assert plan.triggers == ("Note (Text) -> onChange",)


def test_refuses_an_attachment_source_outright() -> None:
    draft = _field("F1", "Doc", "Attachment")
    with pytest.raises(ValueError, match="never carry an event"):
        resolve_event_triggers(draft, {"Doc": [(None, "kf.x();")]})


@pytest.mark.parametrize(
    "wire_type", ["Attachment", "Image", "Signature", "SequenceNumber", "Geolocation"]
)
def test_refuses_every_event_less_field_type(wire_type: str) -> None:
    draft = _field("F1", "X", wire_type)
    with pytest.raises(ValueError, match=wire_type):
        resolve_event_triggers(draft, {"X": [("onChange", "kf.x();")]})


@pytest.mark.parametrize(
    "ftype,trigger", [("User", "onSelect"), ("Boolean", "onClick")]
)
def test_family_inferred_triggers_are_derived_but_flagged_unverified(
    ftype: str, trigger: str
) -> None:
    draft = _field("F1", "Who", ftype)
    plan = resolve_event_triggers(draft, {"Who": [(None, "kf.x();")]})
    assert plan.events == {"Who": [(trigger, "kf.x();")]}
    assert len(plan.unverified) == 1
    assert "family-inferred" in plan.unverified[0] and trigger in plan.unverified[0]


def test_refuses_to_guess_a_trigger_for_a_type_with_no_mapping() -> None:
    draft = _field("F1", "Cost", "Currency")
    with pytest.raises(ValueError, match="will not guess"):
        resolve_event_triggers(draft, {"Cost": [(None, "kf.x();")]})


def test_takes_a_stated_trigger_for_an_unmapped_type_but_flags_it() -> None:
    draft = _field("F1", "Cost", "Currency")
    plan = resolve_event_triggers(draft, {"Cost": [("onSelect", "kf.x();")]})
    assert plan.events == {"Cost": [("onSelect", "kf.x();")]}
    assert len(plan.unverified) == 1 and "outside" in plan.unverified[0]


def test_empty_string_trigger_means_derive_it() -> None:
    draft = _field("F1", "Route", "Select")
    plan = resolve_event_triggers(draft, {"Route": [("", "kf.x();")]})
    assert plan.events == {"Route": [("onClick", "kf.x();")]}
    assert plan.derived == ("Route",)


def test_unknown_field_with_a_stated_trigger_passes_through_verbatim() -> None:
    draft = _field("F1", "Real", "Text")
    plan = resolve_event_triggers(draft, {"Ghost": [("onChange", "1;")]})
    assert plan.events == {"Ghost": [("onChange", "1;")]}


def test_unknown_field_with_nothing_to_derive_from_raises() -> None:
    draft = _field("F1", "Real", "Text")
    with pytest.raises(ValueError, match="cannot derive a trigger for 'Ghost'"):
        resolve_event_triggers(draft, {"Ghost": [(None, "1;")]})


def test_event_less_refusal_uses_an_em_dash_and_names_the_old_module() -> None:
    """Restores the old refusal's exact punctuation and module reference
    (brief_d13_fix.md fix 5): `it can never carry an event -- ` becomes
    `it can never carry an event — `, and `(field_type.NO_EVENT_FIELD_TYPES)`
    becomes `(types.NO_EVENT_FIELD_TYPES)`, the old client's own import
    name for this same table."""
    draft = _field("F1", "Doc", "Attachment")
    with pytest.raises(ValueError) as exc_info:
        resolve_event_triggers(draft, {"Doc": [(None, "kf.x();")]})
    message = str(exc_info.value)
    assert "it can never carry an event — " in message
    assert "it can never carry an event -- " not in message
    assert "(types.NO_EVENT_FIELD_TYPES)" in message
    assert "field_type.NO_EVENT_FIELD_TYPES" not in message


def test_no_captured_trigger_refusal_uses_an_em_dash_and_names_the_old_module() -> None:
    """Same restoration for the second refusal (fix 5): `types.trigger_for`,
    not `field_type.trigger_for`, and an em dash, not a double hyphen."""
    draft = _field("F1", "Cost", "Currency")
    with pytest.raises(ValueError) as exc_info:
        resolve_event_triggers(draft, {"Cost": [(None, "kf.x();")]})
    message = str(exc_info.value)
    assert "`types.trigger_for` — this engine" in message
    assert "field_type.trigger_for" not in message
    assert " -- " not in message


def test_unverified_taken_from_caller_note_uses_an_em_dash_and_old_module() -> None:
    """Same restoration for the unverified note (fix 5)."""
    draft = _field("F1", "Cost", "Currency")
    plan = resolve_event_triggers(draft, {"Cost": [("onSelect", "kf.x();")]})
    note = plan.unverified[0]
    assert "taken from the caller — " in note
    assert "`types.trigger_for`" in note
    assert "field_type.trigger_for" not in note
    assert " -- " not in note


def test_disagreeing_trigger_refusal_uses_an_em_dash() -> None:
    """Same restoration for the disagreement refusal (fix 5)."""
    draft = _field("F1", "Route", "Select")
    with pytest.raises(ValueError) as exc_info:
        resolve_event_triggers(draft, {"Route": [("onChange", "kf.x();")]})
    message = str(exc_info.value)
    assert "asks for 'onChange' — a wrong trigger" in message
    assert " -- " not in message
