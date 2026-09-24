"""`ForgeCreateProcessRequest`."""

from __future__ import annotations

from app.application.models.requests.flow.forge_create_process_request import (
    ForgeCreateProcessRequest,
)


def test_round_trips_every_field() -> None:
    req = ForgeCreateProcessRequest(
        name="N", publish=True, from_template=False, app_id="A1"
    )
    assert req.model_dump(mode="json") == {
        "name": "N",
        "publish": True,
        "from_template": False,
        "app_id": "A1",
    }


def test_publish_and_from_template_default() -> None:
    req = ForgeCreateProcessRequest(name="N", app_id="A1")
    assert req.publish is False
    assert req.from_template is True
