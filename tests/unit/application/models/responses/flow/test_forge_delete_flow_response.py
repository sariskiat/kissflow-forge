"""`ForgeDeleteFlowResponse`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_delete_flow_response import (
    ForgeDeleteFlowResponse,
)


def test_equals_todays_success_dict_plus_snapshot_version() -> None:
    resp = ForgeDeleteFlowResponse(kind="process", id="F1", deleted=True, verified=True)
    assert resp.model_dump(mode="json") == {
        "kind": "process",
        "id": "F1",
        "deleted": True,
        "verified": True,
        "snapshot_version": None,
    }
