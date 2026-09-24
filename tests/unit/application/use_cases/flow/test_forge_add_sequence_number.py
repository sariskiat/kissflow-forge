"""`ForgeAddSequenceNumber`: ported from `tests/test_client.py`'s
`apply_sequence_number` cases (pre-refactor), now against the response DTO
or the raised `ApplicationError` and its code, with
`tests.fakes.flow.FakeFlowRepository`."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_add_sequence_number_request import (
    ForgeAddSequenceNumberRequest,
)
from app.application.use_cases.flow.forge_add_sequence_number import (
    ForgeAddSequenceNumber,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _process_with_section_and_step() -> FlowDraft:
    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Process"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="a", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("S", ["a"])]).to_wire()
    d = FlowDraft.from_wire(d).build_workflow([("Log it", None)]).to_wire()
    return FlowDraft.from_wire(d)


def _request(**overrides: Any) -> ForgeAddSequenceNumberRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "field_name": "Case ID",
        "section_name": "S",
        "prefix": "CS-",
        "padding": "0001",
        "step_activity_name": "Start",
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeAddSequenceNumberRequest(**fields)


@pytest.mark.asyncio
async def test_success() -> None:
    before = _process_with_section_and_step()
    after = before.add_sequence_number("Case ID", "S", "CS-", "0001", "Start")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeAddSequenceNumber(flow=fake).execute(_request())

    assert resp.flow_id == "F1"
    assert resp.field_name == "Case ID"
    assert resp.section == "S"
    assert resp.verified is True
    assert resp.missing is False
    assert resp.published is False
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_with_publish() -> None:
    before = _process_with_section_and_step()
    after = before.add_sequence_number("Case ID", "S", "CS-", "0001", "Start")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeAddSequenceNumber(flow=fake).execute(_request(publish=True))

    assert resp.verified is True
    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_draft",
        "put_draft",
        "get_draft",
        "publish",
    ]


@pytest.mark.asyncio
async def test_offline_validation_error() -> None:
    before = _process_with_section_and_step()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddSequenceNumber(flow=fake).execute(
            _request(section_name="NonExistentSection")
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "offline add_sequence_number rejected the spec" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_unverified_raises_verify_failed_and_skips_publish() -> None:
    """Rule 7: a write that did not fully land is a failure, never a success
    response."""
    before = _process_with_section_and_step()
    fake = FakeFlowRepository()
    # the read-back never reflects the write -- verify_sequence_number finds nothing.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddSequenceNumber(flow=fake).execute(_request(publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "'Case ID'" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddSequenceNumber(flow=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
