"""`ForgeDoctorResponse` -- the former `run_doctor` dict shape, minus `isError`.
Not a write tool, so it carries no `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_doctor_response import (
    ForgeDoctorResponse,
)


def test_equals_todays_success_dict() -> None:
    resp = ForgeDoctorResponse(
        flow_id="F1",
        ok=True,
        problems=[],
        checked={"members": 1},
        unvalidated=[],
        unvalidatable_scripts=0,
        list_ids_checked=["L1"],
        list_fetch_errors={},
        members_found=3,
        member_fetch_error=None,
    )
    assert resp.model_dump(mode="json") == {
        "flow_id": "F1",
        "ok": True,
        "problems": [],
        "checked": {"members": 1},
        "unvalidated": [],
        "unvalidatable_scripts": 0,
        "list_ids_checked": ["L1"],
        "list_fetch_errors": {},
        "members_found": 3,
        "member_fetch_error": None,
    }
