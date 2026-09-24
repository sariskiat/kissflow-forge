"""`KfCreateProcessResponse` -- the former `ProcessCreateReport.as_tool_result()`
shape, minus `isError`, plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.kf_create_process_response import (
    KfCreateProcessResponse,
)

_BASE: dict[str, object] = {
    "flow_id": "F1",
    "added": ["Ticket No"],
    "skipped": [],
    "verified": ["Ticket No"],
    "missing": [],
    "changed_ignored": [],
    "collateral": [],
    "remediation": [],
    "meta_version": "v2",
    "published": False,
    "from_template": True,
    "template_sections": ["System"],
    "template_required_fields": ["Department"],
    "template_steps": ["Manager Approve"],
    "template_read_error": None,
}


def test_equals_todays_success_dict_plus_snapshot_version() -> None:
    resp = KfCreateProcessResponse.model_validate(
        {**_BASE, "note": "a note", "snapshot_version": "v1"}
    )
    assert resp.model_dump(mode="json") == {
        **_BASE,
        "note": "a note",
        "snapshot_version": "v1",
    }


def test_note_and_snapshot_version_default_to_none() -> None:
    resp = KfCreateProcessResponse.model_validate(_BASE)
    assert resp.note is None
    assert resp.snapshot_version is None
