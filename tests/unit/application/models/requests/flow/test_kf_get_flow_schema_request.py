"""`KfGetFlowSchemaRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.kf_get_flow_schema_request import (
    KfGetFlowSchemaRequest,
)


def test_round_trips_every_field() -> None:
    req = KfGetFlowSchemaRequest(
        flow_kind="page", flow_id="P1", app_id="A1", app_id_given=True
    )
    assert req.model_dump(mode="json") == {
        "flow_kind": "page",
        "flow_id": "P1",
        "app_id": "A1",
        "app_id_given": True,
    }


def test_refuses_an_unknown_flow_kind() -> None:
    with pytest.raises(ValidationError):
        KfGetFlowSchemaRequest(
            flow_kind="bogus",  # type: ignore
            flow_id="F1",
            app_id="A1",
            app_id_given=True,
        )
