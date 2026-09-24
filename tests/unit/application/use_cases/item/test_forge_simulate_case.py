"""`ForgeSimulateCase`: ported from the old `forge_simulate_case` tool body
(`server.py:1646-1713`, pre-refactor) -- the field-name index is read
through the FLOW port before the walk, a read failure there falls back to
no index (never fatal), and a walk that stops at a step becomes a raised
`ApplicationError` (rule 7, `brief_stage_d_common.md`) rather than the old
`isError: true` data.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.item import FakeItemService

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.item.forge_simulate_case_request import (
    ForgeSimulateCaseRequest,
)
from app.application.use_cases.item.forge_simulate_case import ForgeSimulateCase
from app.domain.entities.flow_draft import FlowDraft

_CONTEXT = [{"_context_activity_instance_id": "AIID-1"}]


def _request(**overrides: Any) -> ForgeSimulateCaseRequest:
    fields: dict[str, Any] = {
        "flow_id": "Flow_1",
        "steps": [{"name": "step-1", "values": {"Field_a": "a1"}}],
        "app_id": "App1",
        # poll_after_transition is a live-only concern, already exhaustively
        # covered offline in test__walk.py; off here so these wiring tests
        # need not queue a third get_detail for the post-advance poll.
        "poll": False,
    }
    fields.update(overrides)
    return ForgeSimulateCaseRequest(**fields)


def _named_draft() -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "M1": {"Id": "M1", "Kind": "Model", "FlowType": "Process"},
            "Field_a": {
                "Id": "Field_a",
                "Kind": "Field",
                "Name": "Business Unit ID",
                "Model": "M1",
            },
        }
    )


@pytest.mark.asyncio
async def test_happy_path_creates_fills_and_advances() -> None:
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},
        {"Field_a": "a1", "_current_context": _CONTEXT},
    ]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]

    resp = await ForgeSimulateCase(item=item, flow=flow).execute(_request())

    assert resp.created is True
    assert resp.iid == "ITEM-1"
    assert resp.advanced == ["step-1"]
    assert resp.failed == []
    assert resp.error is None
    assert resp.snapshot_version is None
    get_draft_calls = [c for c in flow.calls if c[0] == "get_draft"]
    assert get_draft_calls[0][1] == ("App1", "process", "Flow_1")


@pytest.mark.asyncio
async def test_resolves_field_names_through_the_flow_draft() -> None:
    """The use case builds `field_index` from the FLOW port's draft, so a
    caller may key `values` by the field's display NAME, not just its id."""
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},
        {"Field_a": "a1", "_current_context": _CONTEXT},
    ]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]

    resp = await ForgeSimulateCase(item=item, flow=flow).execute(
        _request(steps=[{"name": "step-1", "values": {"Business Unit ID": "a1"}}])
    )

    assert resp.advanced == ["step-1"]
    put_calls = [c for c in item.calls if c[0] == "put_fields"]
    assert put_calls[0][1][2] == {"Field_a": "a1"}


@pytest.mark.asyncio
async def test_draft_read_failure_falls_back_to_no_index_not_fatal() -> None:
    class _NoDraft(FakeFlowRepository):
        async def get_draft(self, app_id, kind, flow_id):  # type: ignore[override]
            self.calls.append(("get_draft", (app_id, kind, flow_id), {}))
            raise RepositoryError("draft 500")

    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},
        {"Field_a": "a1", "_current_context": _CONTEXT},
    ]
    flow = _NoDraft()

    resp = await ForgeSimulateCase(item=item, flow=flow).execute(_request())

    assert resp.advanced == [
        "step-1"
    ]  # the walk still ran, keys passed through verbatim


@pytest.mark.asyncio
async def test_poll_true_is_threaded_through_to_the_walk() -> None:
    """`request.poll` (default `True`) reaches `_walk.walk`'s own
    `poll_after_transition` -- proven by a poll that needs, and gets, one
    extra `get_detail` read after the advance."""
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},  # fill-verify
        {"Field_a": "a1", "_current_context": _CONTEXT},  # advance's aiid
        {
            "Field_a": "a1",
            "_current_context": [{"_context_activity_instance_id": "AIID-NEW"}],
        },
    ]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]

    resp = await ForgeSimulateCase(item=item, flow=flow).execute(
        _request(poll=True, poll_tries=1, poll_delay=0)
    )

    assert resp.advanced == ["step-1"]
    assert sum(1 for c in item.calls if c[0] == "get_detail") == 3


@pytest.mark.asyncio
async def test_a_failed_step_raises_verify_failed_naming_the_step() -> None:
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [{"Field_a": None}]  # discarded: never landed
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSimulateCase(item=item, flow=flow).execute(_request())

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "step-1" in exc_info.value.message


@pytest.mark.asyncio
async def test_a_failed_step_message_keeps_the_landed_state_findable() -> None:
    """Review fix 1: the item WAS created before the failing step -- a
    caller reading this failure must still be able to find it (`iid`), and
    see exactly how far the walk got (`filled`/`advanced`/`rejected`),
    never just the bare step name (server.py:1702-1713, pre-refactor, kept
    every one of those fields in its `isError: true` dict)."""
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [
        {"Field_a": "a1", "_current_context": _CONTEXT},  # step-1's fill-verify
        {"Field_a": "a1", "_current_context": _CONTEXT},  # step-1's advance
        {"Field_a": None},  # step-2's fill-verify: discarded, never landed
    ]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSimulateCase(item=item, flow=flow).execute(
            _request(
                steps=[
                    {"name": "step-1", "values": {"Field_a": "a1"}},
                    {"name": "step-2", "values": {"Field_a": "a1"}},
                ]
            )
        )

    msg = exc_info.value.message
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "iid=ITEM-1" in msg
    assert "filled=['step-1']" in msg
    assert "advanced=['step-1']" in msg
    assert "rejected=[]" in msg
    assert "step-2" in msg


@pytest.mark.asyncio
async def test_failed_step_message_includes_the_walk_cause() -> None:
    """A failed bucket names the step, while ``error`` explains what failed."""
    item = FakeItemService()
    item.results["create_item"] = [{"_id": "ITEM-1"}]
    item.results["get_detail"] = [{"Field_a": None}]
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_named_draft()]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSimulateCase(item=item, flow=flow).execute(_request())

    msg = exc_info.value.message
    assert "failed=['step-1'" in msg
    assert "step-1: fill not verified" in msg
    assert "discarded=('Field_a',)" in msg


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    item = FakeItemService()
    flow = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSimulateCase(item=item, flow=flow).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert item.calls == [] and flow.calls == []
