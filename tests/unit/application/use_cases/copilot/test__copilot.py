"""`app.application.use_cases.copilot._copilot`: ported from
`tests/test_p4_surface.py`'s `test_copilot_check_*` cases (pre-refactor,
where this logic lived inline in
`app.infrastructure.kissflow.client._flow_id_inventory` /
`apply_copilot_check`'s per-flow node-count loop), now testing the pure
`flow_id_inventory`/`node_count` functions directly against
`tests.fakes.flow.FakeFlowRepository`.
"""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import RepositoryError
from app.application.use_cases.copilot._copilot import flow_id_inventory, node_count
from app.domain.entities.flow_draft import FlowDraft


@pytest.mark.asyncio
async def test_flow_id_inventory_covers_every_flow_kind() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [
        [{"_id": "P1"}],  # process
        [],  # form
        [],  # case
        [{"_id": "L_scratch"}],  # list
        [],  # dataset
    ]

    out = await flow_id_inventory(flow, "App1")

    assert out == {
        "process": ["P1"],
        "form": [],
        "case": [],
        "list": ["L_scratch"],
        "dataset": [],
    }
    kinds_asked = [c[1][1] for c in flow.calls if c[0] == "list_flows"]
    assert kinds_asked == ["process", "form", "case", "list", "dataset"]


@pytest.mark.asyncio
async def test_flow_id_inventory_ignores_malformed_entries() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [
        [{"_id": "P1"}, {"no_id": True}, "not-a-dict"],
        [],
        [],
        [],
        [],
    ]

    out = await flow_id_inventory(flow, "App1")

    assert out["process"] == ["P1"]


@pytest.mark.asyncio
async def test_node_count_counts_top_level_keys() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [
        FlowDraft.from_wire({"Root": "M1", "M1": {"Id": "M1"}, "X": {"Id": "X"}})
    ]

    count = await node_count(flow, "App1", "list", "L_scratch")

    assert count == 3


@pytest.mark.asyncio
async def test_node_count_reports_minus_one_on_a_read_failure() -> None:
    class _NoDraft(FakeFlowRepository):
        async def get_draft(self, app_id, kind, flow_id):  # type: ignore[override]
            self.calls.append(("get_draft", (app_id, kind, flow_id), {}))
            raise RepositoryError("draft 500")

    count = await node_count(_NoDraft(), "App1", "list", "L_scratch")

    assert count == -1
