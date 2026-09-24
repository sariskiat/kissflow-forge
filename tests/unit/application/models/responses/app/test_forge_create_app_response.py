"""`ForgeCreateAppResponse`: `model_dump(mode="json")` equals today's
`create_application_verified` success dict (pre-refactor) without `isError`,
plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.app.forge_create_app_response import (
    ForgeCreateAppResponse,
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeCreateAppResponse(
        app_id="App_1",
        name="Sample App",
        verified=True,
        supported=True,
        note=None,
    )
    assert resp.model_dump(mode="json") == {
        "app_id": "App_1",
        "name": "Sample App",
        "verified": True,
        "supported": True,
        "note": None,
        "snapshot_version": None,
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeCreateAppResponse(
        app_id="App_1", name="Sample App", verified=True, supported=True, note=None
    )
    assert resp.snapshot_version is None
