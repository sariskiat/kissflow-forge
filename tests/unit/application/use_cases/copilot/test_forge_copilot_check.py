"""`ForgeCopilotCheck`: ported from `tests/test_p4_surface.py`'s
`test_copilot_check_*` cases (pre-refactor), now against the response DTO or
the raised `ApplicationError` and its code, with
`tests.fakes.copilot.FakeCopilotService` and
`tests.fakes.flow.FakeFlowRepository`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.copilot import FakeCopilotService
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import ApplicationError
from app.application.models.requests.copilot.forge_copilot_check_request import (
    ForgeCopilotCheckRequest,
)
from app.application.use_cases.copilot.forge_copilot_check import ForgeCopilotCheck
from app.domain.entities.flow_draft import FlowDraft

_BASELINE = {"process": ["P1"], "form": [], "case": [], "list": [], "dataset": []}


def _request(**overrides: Any) -> ForgeCopilotCheckRequest:
    fields: dict[str, Any] = {"app_id": "App1", "conversation_id": "C1"}
    fields.update(overrides)
    return ForgeCopilotCheckRequest(**fields)


@pytest.mark.asyncio
async def test_reads_reply_and_reports_no_scatter_when_nothing_new() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [
        [{"ConversationId": "C1", "SystemMessage": "done"}]
    ]
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "P1"}], [], [], [], []]

    resp = await ForgeCopilotCheck(copilot, flow).execute(
        _request(baseline_inventory=_BASELINE)
    )

    assert resp.reply == "done"
    assert resp.scatter == {}
    assert resp.reply_is_proof is False


@pytest.mark.asyncio
async def test_detects_scatter_into_a_new_flow() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [
        [{"ConversationId": "C1", "SystemMessage": "built a list for you"}]
    ]
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "P1"}], [], [], [{"_id": "L_scratch"}], []]
    flow.results["get_draft"] = [
        FlowDraft.from_wire({"Root": "M1", "M1": {"Id": "M1"}, "X": {"Id": "X"}})
    ]

    resp = await ForgeCopilotCheck(copilot, flow).execute(
        _request(baseline_inventory=_BASELINE)
    )

    assert resp.scatter == {"list": ["L_scratch"]}
    assert resp.landed_nodes["list"]["L_scratch"] == 3


@pytest.mark.asyncio
async def test_with_no_baseline_treats_everything_as_scatter() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [[]]
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[{"_id": "P1"}], [], [], [], []]
    flow.results["get_draft"] = [
        FlowDraft.from_wire({"Root": "M1", "M1": {"Id": "M1"}})
    ]

    resp = await ForgeCopilotCheck(copilot, flow).execute(_request())

    assert resp.scatter.get("process") == ["P1"]


@pytest.mark.asyncio
async def test_no_reply_yet_is_a_verdict_not_a_tool_error() -> None:
    """Rule 7's verdict-tool exception: a still-pending ask reports `reply:
    None` here, never a `ToolError`. The reply is never proof either way
    (THE RULE) -- there is no `ok`/verdict field to flip."""
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [[]]
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[], [], [], [], []]

    resp = await ForgeCopilotCheck(copilot, flow).execute(
        _request(baseline_inventory=_BASELINE)
    )

    assert resp.reply is None


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    copilot = FakeCopilotService()
    flow = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeCopilotCheck(copilot, flow).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert copilot.calls == [] and flow.calls == []
