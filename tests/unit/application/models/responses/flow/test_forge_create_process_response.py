"""`ForgeCreateProcessResponse` -- the former `ProcessCreateReport.as_tool_result()`
shape, minus `isError`, plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_create_process_response import (
    ForgeCreateProcessResponse,
)

_BASE: dict[str, object] = {
    "flow_id": "F1",
    "added": [],
    "skipped": [],
    "verified": [],
    "missing": [],
    "changed_ignored": [],
    "collateral": [],
    "remediation": [],
    "meta_version": "v2",
    "published": True,
    "from_template": True,
    "template_sections": ["System"],
    "template_required_fields": ["Department"],
    "template_steps": ["Manager Approve"],
    "template_read_error": None,
}


def test_equals_todays_success_dict_plus_snapshot_version() -> None:
    resp = ForgeCreateProcessResponse.model_validate(
        {**_BASE, "note": "a note", "snapshot_version": "v1"}
    )
    assert resp.model_dump(mode="json") == {
        **_BASE,
        "note": "a note",
        "snapshot_version": "v1",
    }


def test_note_and_snapshot_version_default_to_none() -> None:
    resp = ForgeCreateProcessResponse.model_validate(_BASE)
    assert resp.note is None
    assert resp.snapshot_version is None
