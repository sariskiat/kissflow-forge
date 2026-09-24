"""`KfGetFlowSchemaResponse` -- a `RootModel`, the draft dict verbatim."""

from __future__ import annotations

from app.application.models.responses.flow.kf_get_flow_schema_response import (
    KfGetFlowSchemaResponse,
)


def test_dumps_the_draft_dict_unwrapped() -> None:
    draft = {"Root": "M1", "M1": {"Kind": "Model"}}
    resp = KfGetFlowSchemaResponse(draft)
    assert resp.model_dump(mode="json") == draft


def test_round_trips_an_empty_dict() -> None:
    resp = KfGetFlowSchemaResponse({})
    assert resp.model_dump(mode="json") == {}
