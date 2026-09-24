"""`FlowRepository`: the ABC refuses instantiation; the fake implements every abstract
method."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository

from app.application.interfaces.flow import FlowRepository
from app.domain.entities.flow_draft import FlowDraft


def test_flow_repository_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        FlowRepository()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakeFlowRepository()
    draft = FlowDraft.from_wire({"_meta_version": "v1"})

    await fake.get_draft("A1", "process", "F1")
    await fake.create_flow("A1", "process", "New flow")
    await fake.delete_flow("A1", "process", "F1", archive_first=False)
    await fake.publish("A1", "process", "F1")
    await fake.get_flow_detail("A1", "process", "F1")
    await fake.list_flows("A1", "process")
    await fake.get_members("A1", "process", "F1")
    await fake.delete_member("A1", "process", "F1", "Ro1")
    await fake.post_member_batch("A1", "process", "F1", [{"_id": "Ro1"}])
    await fake.post_report_member_batch("A1", "F1", "Rp1", [{"_id": "Ro1"}])
    await fake.get_list_items("A1", "L1")
    await fake.list_lists("A1")
    await fake.create_list("A1", "Colors")
    await fake.set_list_items("L1", ["Red", "Blue"])
    await fake.create_dataset("A1", "Orders")
    await fake.create_case("A1", "Cases", "Case", "CS")
    await fake.put_draft("A1", "process", "F1", draft, "v1")

    assert [call[0] for call in fake.calls] == [
        "get_draft",
        "create_flow",
        "delete_flow",
        "publish",
        "get_flow_detail",
        "list_flows",
        "get_members",
        "delete_member",
        "post_member_batch",
        "post_report_member_batch",
        "get_list_items",
        "list_lists",
        "create_list",
        "set_list_items",
        "create_dataset",
        "create_case",
        "put_draft",
    ]


@pytest.mark.asyncio
async def test_get_draft_returns_a_flow_draft_by_default() -> None:
    fake = FakeFlowRepository()
    result = await fake.get_draft("A1", "process", "F1")
    assert isinstance(result, FlowDraft)


@pytest.mark.asyncio
async def test_results_queue_lets_a_test_script_a_specific_return_value() -> None:
    fake = FakeFlowRepository()
    wanted = FlowDraft.from_wire({"_meta_version": "v2"})
    fake.results["get_draft"] = [wanted]

    result = await fake.get_draft("A1", "process", "F1")

    assert result is wanted
