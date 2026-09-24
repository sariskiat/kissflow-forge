"""`KfPublishRequest`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.flow.kf_publish_request import KfPublishRequest


def test_round_trips_every_field() -> None:
    req = KfPublishRequest(flow_kind="process", flow_id="F1", app_id="A1")
    assert req.model_dump(mode="json") == {
        "flow_kind": "process",
        "flow_id": "F1",
        "app_id": "A1",
    }


def test_refuses_a_kind_outside_the_closed_set() -> None:
    with pytest.raises(ValidationError):
        KfPublishRequest(flow_kind="page", flow_id="F1", app_id="A1")  # type: ignore
