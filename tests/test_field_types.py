"""Extended field-type coverage. Offline.

Number + Attachment wire-strings CONFIRMED live (2026-08-03 read-only sweep of all 7 dev flows).
Canvas boxes are Type "Textarea" (a real field type), NOT Text with a multiline Widget — corrected
from the earlier guess by the live capture (spikes/spike_capture_schema.py).
"""

import json
import pathlib

from app.application.tools import plan_field_change
from app.domain.graph import apply_changes
from app.domain.types import FieldSpec, FieldType

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "form_draft.json"
MODEL_ID = "TestForm_x001"


def _draft() -> dict:
    return json.loads(FIXTURE.read_text())


def test_number_and_attachment_exist():
    assert FieldType.NUMBER.value == "Number"
    assert FieldType.ATTACHMENT.value == "Attachment"


def test_textarea_exists():
    # NEW type confirmed live (9 fields across the dev app); was missing from the enum.
    assert FieldType.TEXTAREA.value == "Textarea"


def test_apply_number_field_writes_correct_type():
    new = apply_changes(_draft(), [FieldSpec(name="score_coverage", type=FieldType.NUMBER)])
    fid = (set(new[MODEL_ID]["Model::Field"]) - {"field_fullname_a001"}).pop()
    assert new[fid]["Type"] == "Number"


def test_apply_textarea_field_writes_correct_type():
    new = apply_changes(_draft(), [FieldSpec(name="canvas_1", type=FieldType.TEXTAREA)])
    fid = (set(new[MODEL_ID]["Model::Field"]) - {"field_fullname_a001"}).pop()
    assert new[fid]["Type"] == "Textarea"


def test_plan_accepts_number_now():
    out = plan_field_change(_draft(), [{"name": "score_coverage", "type": "Number"}])
    assert out["adds"][0]["type"] == "Number"


def test_canvas_is_textarea():
    # CORRECTED by live capture 2026-08-03: canvas boxes are Type "Textarea", NOT plain Text.
    out = plan_field_change(_draft(), [{"name": "canvas_1", "type": "Textarea"}])
    assert out["adds"][0]["type"] == "Textarea"


def test_trigger_for_covers_every_field_type_or_refuses_by_name() -> None:
    """`trigger_for` is declared to return an EventTrigger, and its callers do
    `trigger_for(t).value`. Its match had no default, so FieldType.DATETIME — a real member,
    absent from the other cases — fell through and returned None implicitly: callers got an
    opaque `AttributeError: 'NoneType' has no attribute 'value'`, several frames from the cause.

    The fix is a refusal, not a guess. DATETIME is deliberately absent from
    TRIGGER_LIVE_CONFIRMED, and inferring onSelect from the Date family is exactly the
    uncaptured guess CLAUDE.md's THE RULE exists to stop.

    This walks EVERY member so a field type added later cannot reintroduce the silent None:
    each one must either return a real EventTrigger or raise a ValueError that names it.
    """
    import pytest

    from app.domain.types import EventTrigger, trigger_for

    for t in FieldType:
        try:
            got = trigger_for(t)
        except ValueError as e:
            assert t.value in str(e), f"{t}: refusal must name the type it refused"
            continue
        assert isinstance(got, EventTrigger), f"{t}: returned {got!r}, not an EventTrigger"

    # The specific regression: DateTime refuses loudly instead of returning None.
    with pytest.raises(ValueError, match="DateTime"):
        trigger_for(FieldType.DATETIME)
