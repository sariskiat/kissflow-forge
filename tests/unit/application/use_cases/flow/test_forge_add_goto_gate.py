"""`ForgeAddGotoGate`: ported from `tests/test_client.py`'s `apply_goto_gate`
suite (spec G11, Stage D group `d3_flow_workflow`)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.flow.forge_add_goto_gate_request import (
    ForgeAddGotoGateRequest,
)
from app.application.use_cases.flow.forge_add_goto_gate import ForgeAddGotoGate
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def _process_with_boolean_field() -> FlowDraft:
    draft = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Review",))
    return draft.apply_changes([FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])


def _process_with_select_field() -> FlowDraft:
    draft = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Review",))
    return draft.apply_changes(
        [FieldSpec(name="Choice", type=FieldType.SELECT, referred_list="List_Sample01")]
    )


def _process_with_branches(field_type: FieldType = FieldType.SELECT) -> FlowDraft:
    draft = FlowDraft.from_wire(_bare_process_draft()).build_workflow(
        [("Intake", None)],
        parallel=(
            "Route",
            [
                ("Branch A", [("Shared Step", None)]),
                ("Branch B", [("Shared Step", None)]),
            ],
        ),
        parallel_after=0,
    )
    kwargs: dict[str, Any] = {}
    if field_type == FieldType.SELECT:
        kwargs["referred_list"] = "List_Sample01"
    return draft.apply_changes([FieldSpec(name="Track", type=field_type, **kwargs)])


def _fake_after_gate(
    draft: FlowDraft, *, target: str, field: str, branch_name: str | None = None
) -> tuple[FakeFlowRepository, str]:
    branch_pd_id = None
    if branch_name is not None:
        pd = next(
            v["Id"]
            for v in draft.to_wire().values()
            if isinstance(v, dict)
            and v.get("Kind") == "ProcessDef"
            and v.get("Name") == branch_name
        )
        branch_pd_id = pd
    target_id = next(
        k
        for k, v in draft.to_wire().items()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == target
        and (branch_pd_id is None or v.get("ProcessDef") == branch_pd_id)
    )
    field_id = next(
        k
        for k, v in draft.to_wire().items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == field
    )
    with_goto, goto_id = draft.add_goto_task(
        target_activity_id=target_id, branch_process_def_id=branch_pd_id
    )
    after = with_goto.build_goto_gate(goto_activity_id=goto_id, field_id=field_id)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]
    return fake, goto_id


def _request(**overrides: Any) -> ForgeAddGotoGateRequest:
    values: dict[str, Any] = {
        "flow_id": "F1",
        "target_activity_name": "Review",
        "field_name": "Done Flag",
        "app_id": "App1",
    }
    values.update(overrides)
    return ForgeAddGotoGateRequest(**values)


@pytest.mark.asyncio
async def test_wires_and_verifies_the_loop_condition() -> None:
    draft = _process_with_boolean_field()
    fake, goto_id = _fake_after_gate(draft, target="Review", field="Done Flag")

    resp = await ForgeAddGotoGate(fake).execute(_request())
    assert resp.verified is True
    assert resp.goto_activity_id == goto_id
    assert resp.snapshot_version == "v1"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_publish_runs_when_the_gate_verifies() -> None:
    draft = _process_with_boolean_field()
    fake, _goto_id = _fake_after_gate(draft, target="Review", field="Done Flag")

    resp = await ForgeAddGotoGate(fake).execute(_request(publish=True))
    assert resp.published is True
    assert [c[0] for c in fake.calls].count("publish") == 1


@pytest.mark.asyncio
async def test_a_gate_that_does_not_verify_on_read_back_raises() -> None:
    """The offline build succeeds, but the read-back never shows the loop
    condition landing (a fake standing in for a write that silently dropped it) --
    rule 7 says this is a failure, never a success response."""
    draft = _process_with_boolean_field()
    fake = FakeFlowRepository()
    # read-back is the UNCHANGED draft -- the goto id from add_goto_task never
    # actually lands, so `goto_node` resolves to {} and `verified` is False.
    fake.results["get_draft"] = [draft, draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(_request(publish=True))
    assert exc_info.value.code == VERIFY_FAILED
    assert "Review" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("publish") == 0


@pytest.mark.asyncio
async def test_unknown_target_step_rejected_before_any_write() -> None:
    draft = _process_with_boolean_field()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(_request(target_activity_name="Nope"))
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_unknown_field_rejected_before_any_write() -> None:
    draft = _process_with_boolean_field()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(_request(field_name="Nope"))
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_non_boolean_field_rejected_by_gate_polarity() -> None:
    draft = _process_with_select_field()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(
            _request(target_activity_name="Review", field_name="Choice")
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_branch_name_scopes_target_into_that_branch() -> None:
    draft = _process_with_branches().apply_changes(
        [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)]
    )
    fake, goto_id = _fake_after_gate(
        draft, target="Shared Step", field="Done Flag", branch_name="Branch A"
    )

    resp = await ForgeAddGotoGate(fake).execute(
        _request(target_activity_name="Shared Step", branch_name="Branch A")
    )
    assert resp.verified is True
    assert resp.branch_name == "Branch A"
    assert resp.goto_activity_id == goto_id


@pytest.mark.asyncio
async def test_unknown_branch_name_rejected_before_any_write() -> None:
    draft = _process_with_branches().apply_changes(
        [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(
            _request(target_activity_name="Shared Step", branch_name="No Such Branch")
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_branch_name_target_not_in_that_branch_rejected() -> None:
    draft = _process_with_branches().apply_changes(
        [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(
            _request(target_activity_name="Intake", branch_name="Branch A")
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_ambiguous_target_without_branch_name_rejected_before_any_write() -> None:
    """Both branches carry a step literally named "Shared Step" -- resolving with no
    `branch_name` must raise loud, naming both candidate branches, not silently pick
    one."""
    draft = _process_with_branches().apply_changes(
        [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(
            _request(target_activity_name="Shared Step")
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert "ambiguous" in exc_info.value.message
    assert "Branch A" in exc_info.value.message and "Branch B" in exc_info.value.message
    assert "branch_name" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_no_app_selected_refuses_before_any_port_call() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddGotoGate(fake).execute(_request(app_id=""))
    assert exc_info.value.code == REFUSED
    assert fake.calls == []
