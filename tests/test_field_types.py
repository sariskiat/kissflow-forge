"""Extended field-type coverage. Offline.

Number + Attachment wire-strings CONFIRMED live (2026-08-03 read-only sweep of all 7 dev flows).
Canvas boxes are Type "Textarea" (a real field type), NOT Text with a multiline Widget — corrected
from the earlier guess by the live capture (spikes/spike_capture_schema.py).
"""
import json
import pathlib

from kfforge.graph import apply_changes
from kfforge.tools import plan_field_change
from kfforge.types import FieldSpec, FieldType

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
