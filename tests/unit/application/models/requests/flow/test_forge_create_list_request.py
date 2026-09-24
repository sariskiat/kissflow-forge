"""`ForgeCreateListRequest`."""

from __future__ import annotations

from app.application.models.requests.flow.forge_create_list_request import (
    ForgeCreateListRequest,
)


def test_round_trips_every_field() -> None:
    req = ForgeCreateListRequest(name="Priorities", values=["Low", "High"], app_id="A1")
    assert req.model_dump(mode="json") == {
        "name": "Priorities",
        "values": ["Low", "High"],
        "app_id": "A1",
    }
