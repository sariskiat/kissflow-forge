"""`ForgeCreateListResponse` -- the former `ListReport.as_tool_result()` shape,
minus `isError`, plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_create_list_response import (
    ForgeCreateListResponse,
)


def test_equals_todays_success_dict_plus_snapshot_version() -> None:
    resp = ForgeCreateListResponse(
        list_id="L1",
        name="Priorities",
        created=True,
        items=["Low", "High"],
        verified_items=["Low", "High"],
        missing_items=[],
        snapshot_version=None,
    )
    assert resp.model_dump(mode="json") == {
        "list_id": "L1",
        "name": "Priorities",
        "created": True,
        "items": ["Low", "High"],
        "verified_items": ["Low", "High"],
        "missing_items": [],
        "snapshot_version": None,
    }
