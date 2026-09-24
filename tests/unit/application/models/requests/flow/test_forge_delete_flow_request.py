"""`ForgeDeleteFlowRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.forge_delete_flow_request import (
    ForgeDeleteFlowRequest,
)


def test_round_trips_every_field() -> None:
    req = ForgeDeleteFlowRequest(
        kind="page", flow_id="P1", app_id="A1", app_id_given=True
    )
    assert req.model_dump(mode="json") == {
        "kind": "page",
        "flow_id": "P1",
        "app_id": "A1",
        "app_id_given": True,
    }


def test_accepts_every_delete_kind_including_list_and_dataset() -> None:
    for kind in ("form", "process", "case", "list", "dataset", "page", "application"):
        ForgeDeleteFlowRequest(kind=kind, flow_id="X", app_id="A1", app_id_given=True)


def test_refuses_a_kind_outside_the_closed_set() -> None:
    with pytest.raises(ValidationError):
        ForgeDeleteFlowRequest(
            kind="bogus",  # type: ignore
            flow_id="X",
            app_id="A1",
            app_id_given=True,
        )
