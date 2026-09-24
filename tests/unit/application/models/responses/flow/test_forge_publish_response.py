"""`ForgePublishResponse`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_publish_response import (
    ForgePublishResponse,
)


def test_a_flow_publish_carries_status_and_snapshot_version() -> None:
    resp = ForgePublishResponse(
        kind="process", id="F1", published=True, status="Live", snapshot_version="v1"
    )
    assert resp.model_dump(mode="json") == {
        "kind": "process",
        "id": "F1",
        "published": True,
        "status": "Live",
        "snapshot_version": "v1",
    }


def test_a_page_or_application_publish_defaults_status_to_none() -> None:
    resp = ForgePublishResponse(kind="page", id="P1", published=True)
    assert resp.status is None
    assert resp.snapshot_version is None


def test_a_page_or_application_publish_leaves_status_out_of_the_payload() -> None:
    """The old dict never carried a `status` key for `kind` in `"page"`/
    `"application"` at all (`server.py`'s own literal dicts) -- the response
    DTO leaves the key out too, rather than serializing it as `status: null`
    (brief_stage_d_common.md lesson 15)."""
    resp = ForgePublishResponse(kind="application", id="App1", published=True)
    assert "status" not in resp.model_dump(mode="json")
