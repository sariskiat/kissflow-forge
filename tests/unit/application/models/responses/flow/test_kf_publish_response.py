"""`KfPublishResponse`."""

from __future__ import annotations

from app.application.models.responses.flow.kf_publish_response import (
    KfPublishResponse,
)


def test_equals_todays_success_dict_plus_snapshot_version() -> None:
    resp = KfPublishResponse(published=True, flow_id="F1", snapshot_version="v1")
    assert resp.model_dump(mode="json") == {
        "published": True,
        "flow_id": "F1",
        "snapshot_version": "v1",
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = KfPublishResponse(published=True, flow_id="F1")
    assert resp.snapshot_version is None
