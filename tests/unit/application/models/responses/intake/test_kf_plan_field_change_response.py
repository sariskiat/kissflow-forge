"""Tests for `KfPlanFieldChangeResponse`: payload parity with the old
`tools.plan_field_change` success dict.
"""

from __future__ import annotations

from app.application.models.responses.intake.kf_plan_field_change_response import (
    AddedField,
    EditedField,
    KfPlanFieldChangeResponse,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = KfPlanFieldChangeResponse(
        adds=[AddedField(name="Notes", type="Text", required=True)],
        edits=[EditedField(name="Existing")],
        skipped=["Already There"],
        human_readable="+ add field 'Notes' (Text, required)",
    )
    assert response.model_dump(mode="json") == {
        "adds": [{"name": "Notes", "type": "Text", "required": True}],
        "edits": [{"name": "Existing"}],
        "skipped": ["Already There"],
        "human_readable": "+ add field 'Notes' (Text, required)",
    }
