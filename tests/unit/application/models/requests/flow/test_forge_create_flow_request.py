"""`ForgeCreateFlowRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_create_flow_request import (
    ForgeCreateFlowRequest,
)


def test_round_trips_every_field() -> None:
    req = ForgeCreateFlowRequest(
        kind="case",
        name="Support",
        extra={"item_type": "Board", "prefix": "SUP"},
        app_id="A1",
    )
    assert req.model_dump(mode="json") == {
        "kind": "case",
        "name": "Support",
        "extra": {"item_type": "Board", "prefix": "SUP"},
        "app_id": "A1",
    }


def test_extra_defaults_to_none() -> None:
    req = ForgeCreateFlowRequest(kind="form", name="N", app_id="A1")
    assert req.extra is None


def test_refuses_a_kind_outside_the_closed_set() -> None:
    with pytest.raises(ValidationError):
        ForgeCreateFlowRequest(kind="page", name="N", app_id="A1")  # type: ignore
