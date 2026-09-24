"""`WriteOrder`: apply() before snapshot() raises; snapshot_version threads
through to apply(); read_back() and publish() call back onto the same port."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository

from app.application.use_cases.flow._write_order import WriteOrder, WriteOrderError
from app.domain.entities.flow_draft import FlowDraft


def _order(
    fake: FakeFlowRepository, *, with_publish: bool = True
) -> WriteOrder[FlowDraft]:
    publish = (lambda: fake.publish("A1", "process", "F1")) if with_publish else None
    return WriteOrder(
        get=lambda: fake.get_draft("A1", "process", "F1"),
        put=lambda new, expect_version: fake.put_draft(
            "A1", "process", "F1", new, expect_version
        ),
        version_of=lambda d: d.version,
        publish=publish,
    )


@pytest.mark.asyncio
async def test_apply_before_snapshot_raises() -> None:
    fake = FakeFlowRepository()
    order = _order(fake)

    with pytest.raises(
        WriteOrderError, match="apply\\(\\) called before snapshot\\(\\)"
    ):
        await order.apply(FlowDraft.from_wire({}))

    assert fake.calls == []


@pytest.mark.asyncio
async def test_snapshot_reads_and_records_the_live_version() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    order = _order(fake)

    snapshot = await order.snapshot()

    assert snapshot.version == "v1"
    assert order.snapshot_version == "v1"
    assert fake.calls == [("get_draft", ("A1", "process", "F1"), {})]


@pytest.mark.asyncio
async def test_apply_writes_with_the_snapshot_version_as_expect_version() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire({"_meta_version": "v1"})]
    order = _order(fake)
    await order.snapshot()

    new_draft = FlowDraft.from_wire({"_meta_version": "v2"})
    written = await order.apply(new_draft)

    assert written is new_draft  # the fake's default put_draft echoes `new`
    assert fake.calls[-1] == (
        "put_draft",
        ("A1", "process", "F1", new_draft),
        {"expect_version": "v1"},
    )


@pytest.mark.asyncio
async def test_read_back_and_publish_call_the_same_port() -> None:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [
        FlowDraft.from_wire({"_meta_version": "v1"}),
        FlowDraft.from_wire({"_meta_version": "v2"}),
    ]
    order = _order(fake)
    await order.snapshot()
    await order.apply(FlowDraft.from_wire({"_meta_version": "v2"}))

    read_back = await order.read_back()
    await order.publish()

    assert read_back.version == "v2"
    assert [c[0] for c in fake.calls] == [
        "get_draft",
        "put_draft",
        "get_draft",
        "publish",
    ]


@pytest.mark.asyncio
async def test_publish_raises_when_this_write_has_no_publish_step() -> None:
    fake = FakeFlowRepository()
    order = _order(fake, with_publish=False)

    with pytest.raises(WriteOrderError, match="no publish step"):
        await order.publish()
