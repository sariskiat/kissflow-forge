"""Spec for app.application.models.requests.app.forge_share_report_request."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.application.models.requests.app.forge_share_report_request import (
    ForgeShareReportRequest,
)

_MEMBER: dict[str, Any] = {
    "_id": "m1",
    "Name": "Lead",
    "Kind": "AppRole",
    "Role": "Ro_lead",
    "Permission": "Member",
}


def test_carries_every_field_as_given() -> None:
    req = ForgeShareReportRequest(
        flow_id="F1", report_id="Rep1", members=[_MEMBER], app_id="A1"
    )
    assert req.flow_id == "F1" and req.report_id == "Rep1" and req.app_id == "A1"
    assert req.members == [_MEMBER], "the member records pass through untouched"


def test_accepts_an_empty_member_list() -> None:
    """The old tool posted whatever list it got, an empty one included."""
    req = ForgeShareReportRequest(flow_id="F1", report_id="Rep1", members=[], app_id="")
    assert req.members == []


def test_rejects_members_that_are_not_a_list_of_records() -> None:
    with pytest.raises(ValidationError):
        ForgeShareReportRequest.model_validate(
            {"flow_id": "F1", "report_id": "Rep1", "members": ["m1"], "app_id": "A1"}
        )


def test_rejects_a_missing_report_id() -> None:
    with pytest.raises(ValidationError):
        ForgeShareReportRequest.model_validate(
            {"flow_id": "F1", "members": [], "app_id": "A1"}
        )


def test_is_frozen() -> None:
    req = ForgeShareReportRequest(
        flow_id="F1", report_id="Rep1", members=[], app_id="A1"
    )
    with pytest.raises(ValidationError):
        req.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
