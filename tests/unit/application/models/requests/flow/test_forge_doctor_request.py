"""`ForgeDoctorRequest`."""

from __future__ import annotations

from app.application.models.requests.flow.forge_doctor_request import (
    ForgeDoctorRequest,
)


def test_round_trips_every_field() -> None:
    req = ForgeDoctorRequest(
        flow_id="F1",
        kind="case",
        visibility_role_claims=["Manager sees X"],
        app_id="A1",
    )
    assert req.model_dump(mode="json") == {
        "flow_id": "F1",
        "kind": "case",
        "visibility_role_claims": ["Manager sees X"],
        "app_id": "A1",
    }


def test_kind_and_visibility_role_claims_default() -> None:
    req = ForgeDoctorRequest(flow_id="F1", app_id="A1")
    assert req.kind == "process"
    assert req.visibility_role_claims is None
