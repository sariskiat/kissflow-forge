"""Mirror tests for `app.application.use_cases.intake._engine` -- ported from
`tests/test_engine.py` (Stage D group 8; the module moved from
`app.application.engine`).

Pure + offline: plan_change describes what apply WOULD do, without writing or
calling Kissflow.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.application.use_cases.intake._engine import plan_change
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType

FIXTURE = pathlib.Path(__file__).resolve().parents[4] / "fixtures" / "form_draft.json"
MODEL_ID = "TestForm_x001"


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_plan_reports_adds_and_is_read_only():
    draft = _load()
    before = json.dumps(draft, sort_keys=True)

    diff = plan_change(
        draft, [FieldSpec(name="Notes", type=FieldType.TEXT, required=True)]
    )

    assert len(diff.adds) == 1
    assert diff.edits == ()
    assert "Notes" in diff.human_readable
    assert "Text" in diff.human_readable
    assert "required" in diff.human_readable
    assert json.dumps(draft, sort_keys=True) == before, (
        "plan_change must not mutate the draft"
    )


def test_plan_matches_apply():
    draft = _load()
    diff = plan_change(draft, [FieldSpec(name="Notes", type=FieldType.TEXT)])
    applied = (
        FlowDraft.from_wire(draft)
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
        .to_wire()
    )
    added = set(applied[MODEL_ID]["Model::Field"]) - set(
        draft[MODEL_ID]["Model::Field"]
    )
    assert len(added) == len(diff.adds) == 1, (
        "the preview count must equal what apply produces"
    )


def test_plan_empty_is_noop():
    diff = plan_change(_load(), [])
    assert diff.adds == () and diff.edits == ()
    assert "no change" in diff.human_readable.lower()


def test_plan_rejects_bad_type():
    with pytest.raises((ValueError, TypeError, KeyError)):
        # deliberately not a FieldType — the raise is the assertion.
        plan_change(_load(), [FieldSpec(name="Bad", type="Frobnicate")])  # ty: ignore[invalid-argument-type]
