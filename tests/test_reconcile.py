"""Idempotent reconcile: applying a manifest adds only missing fields, never duplicates.

This is what lets the AI-Clinic manifest run against the EXISTING process safely. Offline.
"""
import json
import pathlib

from kfforge.engine import plan_change
from kfforge.graph import apply_changes, field_names
from kfforge.types import FieldSpec, FieldType

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "form_draft.json"


def _draft() -> dict:
    return json.loads(FIXTURE.read_text())


def test_field_names_reads_existing():
    assert "Full Name" in field_names(_draft())


def test_plan_skips_existing_adds_only_new():
    diff = plan_change(
        _draft(),
        [FieldSpec(name="Full Name", type=FieldType.TEXT),   # already exists in fixture
         FieldSpec(name="canvas_1", type=FieldType.TEXT)],   # new
    )
    assert [s.name for s in diff.adds] == ["canvas_1"]
    assert "Full Name" in diff.skipped


def test_apply_skips_existing_field():
    d = _draft()
    out = apply_changes(d, [FieldSpec(name="Full Name", type=FieldType.TEXT)])
    assert field_names(out) == field_names(d)  # nothing added — idempotent


def test_apply_is_idempotent_on_repeat():
    d = _draft()
    once = apply_changes(d, [FieldSpec(name="canvas_1", type=FieldType.TEXT)])
    twice = apply_changes(once, [FieldSpec(name="canvas_1", type=FieldType.TEXT)])
    assert field_names(twice) == field_names(once)  # second run adds nothing
