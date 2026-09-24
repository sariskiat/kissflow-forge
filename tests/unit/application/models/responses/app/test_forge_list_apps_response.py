"""`ForgeListAppsResponse`: `model_dump(mode="json")` equals today's
`forge_list_apps` success dict (pre-refactor) without `isError`. A pure read --
no `snapshot_version` field at all."""

from __future__ import annotations

from app.application.models.responses.app.forge_list_apps_response import (
    ForgeListAppsResponse,
)


def test_model_dump_matches_the_old_success_dict() -> None:
    resp = ForgeListAppsResponse(
        apps=[{"_id": "App_1", "Name": "Demo"}, {"_id": "App_2", "Name": "Other"}],
        count=2,
    )
    assert resp.model_dump(mode="json") == {
        "apps": [{"_id": "App_1", "Name": "Demo"}, {"_id": "App_2", "Name": "Other"}],
        "count": 2,
    }


def test_carries_no_snapshot_version_field() -> None:
    assert "snapshot_version" not in ForgeListAppsResponse.model_fields
