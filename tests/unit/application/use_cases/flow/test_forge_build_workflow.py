"""`ForgeBuildWorkflow`: ported from `tests/test_client.py`'s `apply_workflow`
suite (spec G11, Stage D group `d3_flow_workflow`)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.synthetic import OWNERS, synthetic_process_draft
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.flow.forge_build_workflow_request import (
    ForgeBuildWorkflowRequest,
)
from app.application.use_cases.flow.forge_build_workflow import ForgeBuildWorkflow
from app.domain.entities.flow_draft import FlowDraft, progressive_matrix


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def _fake_after_build(draft: dict, steps: list, **kwargs: Any) -> FakeFlowRepository:
    """A fake whose `get_draft` returns `draft` first, then the SAME transform
    `FlowDraft.build_workflow` would produce -- simulating a write that landed
    exactly as planned."""
    before = FlowDraft.from_wire(draft)
    after = before.build_workflow(steps, **kwargs)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]
    return fake


def _request(**overrides: Any) -> ForgeBuildWorkflowRequest:
    values: dict[str, Any] = {
        "flow_id": "F1",
        "steps": [("Draft", "Role_A"), ("Review", None)],
        "app_id": "App1",
    }
    values.update(overrides)
    return ForgeBuildWorkflowRequest(**values)


@pytest.mark.asyncio
async def test_reports_assigned_vs_unassigned_and_verifies_step_names() -> None:
    steps = [("Draft", "Role_A"), ("Review", None)]
    fake = _fake_after_build(_bare_process_draft(), steps)
    resp = await ForgeBuildWorkflow(fake).execute(_request(steps=steps))

    assert resp.verified_steps == ["Draft", "Review"]
    assert resp.missing_steps == []
    assert resp.assigned == ["Draft"]
    assert resp.unassigned == ["Review"]
    assert resp.snapshot_version == "v1"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_offline_rejection_never_reaches_put() -> None:
    """`build_workflow([])` is legal offline (Start -> End only) -- assert it does
    NOT raise and DOES reach put_draft, as the write-order invariant on a legal
    empty workflow."""
    fake = _fake_after_build(_bare_process_draft(), [])
    resp = await ForgeBuildWorkflow(fake).execute(_request(steps=[]))
    assert resp.steps == []
    assert [c[0] for c in fake.calls].count("put_draft") == 1


@pytest.mark.asyncio
async def test_an_invalid_spec_is_rejected_offline_with_no_write() -> None:
    """Two branches on the same gateway sharing a name is the one `build_workflow`
    `ValueError` reachable through this DTO's own fields (see
    `FlowDraft.build_workflow`'s own docstring)."""
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(_bare_process_draft())]

    req = _request(
        steps=[("Intake", None)],
        parallel=(
            "Route",
            [("Same", [("S1", None)]), ("Same", [("S2", None)])],
        ),
        parallel_after=0,
    )
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildWorkflow(fake).execute(req)
    assert exc_info.value.code == VERIFY_FAILED
    assert "offline build_workflow rejected the spec" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_reports_the_permission_matrix_it_destroyed() -> None:
    """A4: build_workflow DELETES every Permission and the report says so."""
    draft = synthetic_process_draft()
    before_matrix = progressive_matrix(FlowDraft.from_wire(draft), OWNERS)
    with_permissions = FlowDraft.from_wire(draft).set_step_permissions(before_matrix)
    permissions_before = sum(
        1
        for v in with_permissions.to_wire().values()
        if isinstance(v, dict) and v.get("Kind") == "Permission"
    )
    assert permissions_before > 0, (
        "fixture must actually carry a live visibility matrix"
    )

    fake = _fake_after_build(
        with_permissions.to_wire(), [("Draft", None), ("Review", None)]
    )
    resp = await ForgeBuildWorkflow(fake).execute(
        _request(steps=[("Draft", None), ("Review", None)])
    )

    assert resp.permissions_deleted == permissions_before
    assert any("Permission node(s) deleted" in s for s in resp.collateral)
    assert resp.remediation == ["forge_set_visibility"]


@pytest.mark.asyncio
async def test_counts_the_damage_on_the_read_back_not_on_the_plan() -> None:
    """THE RULE: what we hoped to write proves nothing. A read-back that still shows
    the OLD draft (the write silently failed to land) must NOT report a wiped
    matrix, because the live matrix is still there. Requests a step NAME that
    already exists on the unwritten draft ("Ticket arrives", a real
    `synthetic_process_draft` step) so it still verifies on read-back and this
    stays a normal return, not the rule-7 raise `test_publish_is_skipped_when_a_
    step_is_missing` covers."""
    draft = synthetic_process_draft()
    before_matrix = progressive_matrix(FlowDraft.from_wire(draft), OWNERS)
    with_permissions = FlowDraft.from_wire(draft).set_step_permissions(before_matrix)

    fake = FakeFlowRepository()
    # get_draft returns the SAME (unwritten) draft both times -- the put never
    # actually landed as far as any reader can tell.
    fake.results["get_draft"] = [with_permissions, with_permissions]

    resp = await ForgeBuildWorkflow(fake).execute(
        _request(steps=[("Ticket arrives", None)])
    )
    assert resp.missing_steps == []
    assert resp.permissions_deleted == 0
    assert resp.collateral == []


@pytest.mark.asyncio
async def test_reports_a_relocated_sequence_number_step_stamp() -> None:
    """#18: the Step stamp is a SCALAR activity ref the list-only sweep never
    touches. A rebuild that drops its step silently repoints it at StartEvent --
    correct, and previously invisible."""
    draft = synthetic_process_draft()
    step = next(
        v["Name"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("NodeType") == "UserTask"
    )
    section = next(
        v["Name"]
        for v in draft.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Section"
        and v.get("Name")
    )
    with_seq = (
        FlowDraft.from_wire(draft)
        .add_sequence_number("Case ID", section, "CS-", "0001", step)
        .to_wire()
    )

    steps = [("Totally Different Step", None)]
    fake = _fake_after_build(with_seq, steps)
    resp = await ForgeBuildWorkflow(fake).execute(_request(steps=steps))

    assert any("Case ID" in s and "Step stamp relocated" in s for s in resp.collateral)
    assert "forge_add_sequence_number" in resp.remediation


def _permission_missing_activity(draft: dict) -> dict:
    """Seed one Permission node with no `Activity` -- the shape `_permission_pairs`
    used to `KeyError` on."""
    new = dict(draft)
    col = next(
        k
        for k, v in new.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Field"
    )
    new["Permission_broken01"] = {
        "Id": "Permission_broken01",
        "Kind": "Permission",
        "Column": col,
        "Permission": "Editable",
    }
    return new


@pytest.mark.asyncio
async def test_counts_the_malformed_permission_it_destroyed() -> None:
    """A node the pair walk SKIPS must still land in a bucket, or the guard has
    just traded a crash for a silent loss."""
    draft = _permission_missing_activity(synthetic_process_draft())
    steps = [("Only step", None)]
    fake = _fake_after_build(draft, steps)
    resp = await ForgeBuildWorkflow(fake).execute(_request(steps=steps))

    assert resp.verified_steps == ["Only step"]
    hits = [line for line in resp.collateral if "Permission_broken01" in line]
    assert len(hits) == 1, resp.collateral
    assert "malformed" in hits[0]
    assert "forge_set_visibility" in resp.remediation
    assert resp.remediation.count("forge_set_visibility") == 1


@pytest.mark.asyncio
async def test_reports_no_collateral_on_a_flow_that_had_none() -> None:
    fake = _fake_after_build(_bare_process_draft(), [("Draft", "Role_A")])
    resp = await ForgeBuildWorkflow(fake).execute(_request(steps=[("Draft", "Role_A")]))
    assert resp.permissions_deleted == 0
    assert resp.collateral == []
    assert resp.remediation == []


@pytest.mark.asyncio
async def test_a_missing_step_raises_and_never_publishes() -> None:
    """A read-back that never shows the requested step (a broken fake, standing in
    for a write that silently dropped it) must never publish, and (rule 7) is a
    FAILURE, never a success response."""
    fake = FakeFlowRepository()
    before = FlowDraft.from_wire(_bare_process_draft())
    # read-back shows NOTHING built -- "Draft" never lands.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildWorkflow(fake).execute(
            _request(steps=[("Draft", None)], publish=True)
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert "Draft" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("publish") == 0


@pytest.mark.asyncio
async def test_a_failed_write_still_names_its_collateral_and_remediation() -> None:
    """Rule 7: the write already landed, and already did its damage (deleted
    every Permission), even though one requested step never verified -- the
    raised message must say so too, not just report `missing` (brief_d13_fix.md
    fix 3: the old code dropped `collateral`/`remediation` on this path)."""
    draft = synthetic_process_draft()
    before_matrix = progressive_matrix(FlowDraft.from_wire(draft), OWNERS)
    with_permissions = FlowDraft.from_wire(draft).set_step_permissions(before_matrix)

    before = with_permissions
    # the read-back only ever shows "Draft" landing -- "Ghost Step" silently
    # never made it, even though the write already wiped every Permission.
    after = before.build_workflow([("Draft", None)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildWorkflow(fake).execute(
            _request(steps=[("Draft", None), ("Ghost Step", None)])
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert "missing=['Ghost Step']" in exc_info.value.message
    assert "Permission node(s) deleted" in exc_info.value.message
    assert "remediation=['forge_set_visibility']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_publish_runs_when_every_step_verified() -> None:
    steps = [("Draft", None)]
    fake = _fake_after_build(_bare_process_draft(), steps)
    resp = await ForgeBuildWorkflow(fake).execute(_request(steps=steps, publish=True))
    assert resp.missing_steps == []
    assert resp.published is True
    assert [c[0] for c in fake.calls].count("publish") == 1


@pytest.mark.asyncio
async def test_no_app_selected_refuses_before_any_port_call() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeBuildWorkflow(fake).execute(_request(app_id=""))
    assert exc_info.value.code == REFUSED
    assert "no app selected" in exc_info.value.message
    assert fake.calls == []
