"""Spec for app.application.models.requests.dataset.forge_dataset_records_request."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.requests.dataset.forge_dataset_records_request import (
    ForgeDatasetRecordsRequest,
)


def test_constructs_from_the_minimal_shape() -> None:
    req = ForgeDatasetRecordsRequest(flow_id="Flow_1", op="list", app_id="A1")
    assert req.flow_id == "Flow_1"
    assert req.op == "list"
    assert req.record is None
    assert req.record_id is None


def test_every_field_is_settable() -> None:
    req = ForgeDatasetRecordsRequest(
        flow_id="Flow_1",
        op="create",
        record={"Name": "K1"},
        record_id="Rec_1",
        app_id="A1",
    )
    assert req.record == {"Name": "K1"}
    assert req.record_id == "Rec_1"


def test_rejects_an_op_this_route_does_not_know() -> None:
    with pytest.raises(ValidationError):
        ForgeDatasetRecordsRequest(
            flow_id="Flow_1",
            op="purge",  # ty: ignore[invalid-argument-type]
            app_id="A1",
        )


def test_rejects_a_missing_app_id() -> None:
    with pytest.raises(ValidationError):
        ForgeDatasetRecordsRequest.model_validate({"flow_id": "Flow_1", "op": "list"})


def test_is_frozen() -> None:
    req = ForgeDatasetRecordsRequest(flow_id="Flow_1", op="list", app_id="A1")
    with pytest.raises(ValidationError):
        req.op = "create"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
