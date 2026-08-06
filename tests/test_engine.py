"""Unit spec for the offline dry-run planner. RED until kfforge.engine exists.

Pure + offline: plan_change describes what apply WOULD do, without writing or calling Kissflow.
"""
import json
import pathlib

import pytest

from kfforge.engine import plan_change
from kfforge.graph import apply_changes
from kfforge.types import FieldSpec, FieldType

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "form_draft.json"
MODEL_ID = "TestForm_x001"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_plan_reports_adds_and_is_read_only():
    draft = _load()
    before = json.dumps(draft, sort_keys=True)

    diff = plan_change(draft, [FieldSpec(name="Notes", type=FieldType.TEXT, required=True)])

    assert len(diff.adds) == 1
    assert diff.edits == ()
    assert "Notes" in diff.human_readable
    assert "Text" in diff.human_readable
    assert "required" in diff.human_readable
    assert json.dumps(draft, sort_keys=True) == before, "plan_change must not mutate the draft"


def test_plan_matches_apply():
    draft = _load()
    diff = plan_change(draft, [FieldSpec(name="Notes", type=FieldType.TEXT)])
    applied = apply_changes(draft, [FieldSpec(name="Notes", type=FieldType.TEXT)])
    added = set(applied[MODEL_ID]["Model::Field"]) - set(draft[MODEL_ID]["Model::Field"])
    assert len(added) == len(diff.adds) == 1, "the preview count must equal what apply produces"


def test_plan_empty_is_noop():
    diff = plan_change(_load(), [])
    assert diff.adds == () and diff.edits == ()
    assert "no change" in diff.human_readable.lower()


def test_plan_rejects_bad_type():
    with pytest.raises((ValueError, TypeError, KeyError)):
        plan_change(_load(), [FieldSpec(name="Bad", type="Frobnicate")])
