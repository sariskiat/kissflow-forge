"""`ForgePublishAppResponse`: `model_dump(mode="json")` equals today's
`publish_application_verified` success dict (pre-refactor) without `isError`,
plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.app.forge_publish_app_response import (
    ForgePublishAppResponse,
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgePublishAppResponse(
        app_id="App1",
        published=True,
        runtime_id=None,
        meta_version="v9",
        note="no Runtime_-prefixed node observed",
    )
    assert resp.model_dump(mode="json") == {
        "app_id": "App1",
        "published": True,
        "runtime_id": None,
        "meta_version": "v9",
        "note": "no Runtime_-prefixed node observed",
        "snapshot_version": None,
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgePublishAppResponse(
        app_id="App1",
        published=True,
        runtime_id="Runtime_abc123",
        meta_version="v9",
        note=None,
    )
    assert resp.snapshot_version is None
