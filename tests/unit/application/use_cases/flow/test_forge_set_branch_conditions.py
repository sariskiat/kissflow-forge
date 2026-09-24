"""`ForgeSetBranchConditions`: ported from `tests/test_client.py`'s
`apply_branch_conditions` suite (spec G11, Stage D group `d3_flow_workflow`)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.flow.forge_set_branch_conditions_request import (
    ForgeSetBranchConditionsRequest,
)
from app.application.use_cases.flow.forge_set_branch_conditions import (
    ForgeSetBranchConditions,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


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


def _bare_process_without_parallel() -> FlowDraft:
    draft = FlowDraft.from_wire(_bare_process_draft()).ensure_process_def(("Review",))
    return draft.apply_changes([FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])


def _branch_pd_id(draft: FlowDraft, name: str) -> str:
    return next(
        v["Id"]
        for v in draft.to_wire().values()
        if isinstance(v, dict)
        and v.get("Kind") == "ProcessDef"
        and v.get("Name") == name
    )


def _field_id(draft: FlowDraft, name: str) -> str:
    return next(
        k
        for k, v in draft.to_wire().items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == name
    )


def _fake_with_options(
    draft: FlowDraft, options: list[str] | None = None
) -> FakeFlowRepository:
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]
    if options is not None:
        fake.results["get_list_items"] = [options]
    return fake


def _queue_read_back(fake: FakeFlowRepository, after: FlowDraft) -> None:
    fake.results["get_draft"].append(after)


def _request(**overrides: Any) -> ForgeSetBranchConditionsRequest:
    values: dict[str, Any] = {
        "flow_id": "F1",
        "field_name": "Track",
        "branch_literals": {"Branch A": "Alpha"},
        "app_id": "App1",
    }
    values.update(overrides)
    return ForgeSetBranchConditionsRequest(**values)


@pytest.mark.asyncio
async def test_wires_and_verifies_both_branches() -> None:
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta"])
    field_id = _field_id(draft, "Track")
    after = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    ).build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch B"),
        field_id=field_id,
        literal="Beta",
        options=["Alpha", "Beta"],
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch A": "Alpha", "Branch B": "Beta"})
    )
    assert resp.verified == ["Branch A", "Branch B"]
    assert resp.missing == []
    assert resp.snapshot_version == "v1"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_publish_runs_when_every_branch_verifies() -> None:
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta"])
    field_id = _field_id(draft, "Track")
    after = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(_request(publish=True))
    assert resp.published is True
    assert [c[0] for c in fake.calls].count("publish") == 1


@pytest.mark.asyncio
async def test_is_idempotent_replacing_not_accumulating() -> None:
    """Re-running with a DIFFERENT literal for the same branch must REPLACE the
    condition, never stack a second one on the same ProcessDef.

    Asserted on the `FlowDraft` the use case actually sent to `put_draft`, not
    on a fixture the test built independently -- the earlier version of this
    test only checked its own `after`, which stayed correct even if the use
    case's own `remove_condition` call were deleted (brief_d13_fix.md fix 7)."""
    draft = _process_with_branches()
    field_id = _field_id(draft, "Track")
    pd_id = _branch_pd_id(draft, "Branch A")
    already_alpha = draft.build_branch_condition(
        process_def_id=pd_id,
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    fake = _fake_with_options(already_alpha, ["Alpha", "Beta"])
    existing_eid = already_alpha.to_wire()[pd_id]["ProcessDef::Expression"][0]
    after = already_alpha.remove_condition(
        expression_id=existing_eid
    ).build_branch_condition(
        process_def_id=pd_id,
        field_id=field_id,
        literal="Beta",
        options=["Alpha", "Beta"],
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch A": "Beta"})
    )
    assert resp.verified == ["Branch A"]

    written = next(c for c in fake.calls if c[0] == "put_draft")[1][3]
    written_wire = written.to_wire()
    expr_ids = written_wire[pd_id]["ProcessDef::Expression"]
    assert len(expr_ids) == 1, (
        f"expected exactly one condition on Branch A, got {len(expr_ids)}"
    )
    root_id = written_wire[expr_ids[0]]["Expression::Node"][0]
    _lhs_id, rhs_id = written_wire[root_id]["Node::Node"]
    assert written_wire[rhs_id]["Type"] == "Static"
    assert written_wire[rhs_id]["Value"] == "Beta"


@pytest.mark.asyncio
async def test_a_branch_that_does_not_verify_on_read_back_raises() -> None:
    """The offline build succeeds, but the read-back never shows the condition
    landing -- rule 7 says this is a failure, never a success response."""
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta"])
    # read-back is the UNCHANGED draft -- the condition never actually lands.
    _queue_read_back(fake, draft)

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(_request(publish=True))
    assert exc_info.value.code == VERIFY_FAILED
    assert "Branch A" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("publish") == 0


@pytest.mark.asyncio
async def test_rejects_literal_not_in_real_options_before_any_write() -> None:
    """CLAUDE.md's own war story: a branch that never fires over one mis-cased/unreal
    literal -- caught here, before the write."""
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta"])

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(
            _request(branch_literals={"Branch A": "Not A Real Option"})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_get_list_items_a_dict_body_never_smuggles_a_literal_through() -> None:
    """Restores the old `list(items) if isinstance(items, list) else []` guard
    (brief_d13_fix.md fix 10): a live list endpoint that comes back as a dict
    body (not a bare list) must read as NO real options, never as the list of
    the dict's OWN keys -- `list({"unexpected": "shape"})` is `["unexpected"]`,
    which would otherwise let a literal that merely happens to match a dict
    key sneak past the real-options check the write exists to enforce
    (CLAUDE.md's own war story: a branch that never fires over an unreal
    literal, caught here, before the write, never discovered live)."""
    draft = _process_with_branches()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]
    fake.results["get_list_items"] = [{"unexpected": "shape"}]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(
            _request(branch_literals={"Branch A": "unexpected"})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_get_list_items_none_reads_as_no_real_options() -> None:
    """Same guard, the `None` boundary."""
    draft = _process_with_branches()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]
    fake.results["get_list_items"] = [None]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(
            _request(branch_literals={"Branch A": "Alpha"})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_unknown_branch_name_rejected_before_any_write() -> None:
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta"])

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(
            _request(branch_literals={"No Such Branch": "Alpha"})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0
    assert [c[0] for c in fake.calls].count("get_list_items") == 0


@pytest.mark.asyncio
async def test_unknown_field_rejected_before_any_write() -> None:
    draft = _process_with_branches()
    fake = _fake_with_options(draft)

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(
            _request(field_name="No Such Field")
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_requires_exactly_one_parallel_gateway() -> None:
    draft = _bare_process_without_parallel()  # no Parallel at all
    fake = _fake_with_options(draft)

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(
            _request(field_name="Done Flag", branch_literals={"Branch A": "Alpha"})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_text_field_skips_option_validation() -> None:
    """A Text-typed deciding field has no ReferredList -- the literal is written as
    given, never blocked for lack of a live list."""
    draft = _process_with_branches(field_type=FieldType.TEXT)
    fake = _fake_with_options(draft)
    field_id = _field_id(draft, "Track")
    after = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Anything At All",
        options=None,
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch A": "Anything At All"})
    )
    assert resp.verified == ["Branch A"]
    assert resp.missing == []
    assert resp.uncovered == []
    assert [c[0] for c in fake.calls].count("get_list_items") == 0


@pytest.mark.asyncio
async def test_uncovered_real_options_are_reported() -> None:
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta", "Gamma"])
    field_id = _field_id(draft, "Track")
    after = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta", "Gamma"],
    ).build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch B"),
        field_id=field_id,
        literal="Beta",
        options=["Alpha", "Beta", "Gamma"],
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch A": "Alpha", "Branch B": "Beta"})
    )
    assert resp.uncovered == ["Gamma"]


@pytest.mark.asyncio
async def test_uncovered_never_forces_a_missing_or_published_false_report() -> None:
    """A caller may genuinely want a value to end the case with no work done --
    `uncovered` must never mark `missing`."""
    draft = _process_with_branches()
    fake = _fake_with_options(draft, ["Alpha", "Beta", "Gamma"])
    field_id = _field_id(draft, "Track")
    after = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta", "Gamma"],
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(_request())
    assert resp.uncovered != []
    assert resp.missing == []


@pytest.mark.asyncio
async def test_uncovered_accounts_for_branches_this_call_never_touched() -> None:
    """`uncovered` must reflect the FULL branch set on the gateway, not just
    this call's own `branch_literals` -- otherwise a value an EARLIER call
    already covered on a different branch would false-alarm here every time
    that other branch is left untouched. Ported from
    `test_apply_branch_conditions_uncovered_accounts_for_branches_this_call_never_touched`
    in `tests/test_client.py` (brief_d13_fix.md fix 8)."""
    draft = _process_with_branches()
    field_id = _field_id(draft, "Track")
    already_alpha = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    fake = _fake_with_options(already_alpha, ["Alpha", "Beta"])
    after = already_alpha.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch B"),
        field_id=field_id,
        literal="Beta",
        options=["Alpha", "Beta"],
    )
    _queue_read_back(fake, after)

    resp = await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch B": "Beta"})
    )
    assert resp.uncovered == [], (
        "Branch A's earlier condition still covers Alpha -- must not be "
        "reported as uncovered just because THIS call only touched Branch B"
    )


@pytest.mark.asyncio
async def test_only_touches_the_named_branches() -> None:
    """A branch NOT named in `branch_literals` must be left completely alone.
    Asserted on the `FlowDraft` the use case actually sent to `put_draft`.
    Ported from `test_apply_branch_conditions_only_touches_the_named_branches`
    in `tests/test_client.py` (brief_d13_fix.md fix 8)."""
    draft = _process_with_branches()
    field_id = _field_id(draft, "Track")
    branch_b_pd_id = _branch_pd_id(draft, "Branch B")
    fake = _fake_with_options(draft, ["Alpha", "Beta"])
    after = draft.build_branch_condition(
        process_def_id=_branch_pd_id(draft, "Branch A"),
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    _queue_read_back(fake, after)

    await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch A": "Alpha"})
    )

    written = next(c for c in fake.calls if c[0] == "put_draft")[1][3]
    written_wire = written.to_wire()
    assert "ProcessDef::Expression" not in written_wire[branch_b_pd_id]


@pytest.mark.asyncio
async def test_writes_the_correct_owner_key_and_ast_shape() -> None:
    """The offline `build_branch_condition` must own the Expression with
    `ProcessDef` (a branch condition), never `Activity` (a GotoTask gate) --
    asserted on the `FlowDraft` the use case actually sent to `put_draft`.
    Ported from
    `test_apply_branch_conditions_writes_the_correct_owner_key_and_ast_shape`
    in `tests/test_client.py` (brief_d13_fix.md fix 8)."""
    draft = _process_with_branches()
    field_id = _field_id(draft, "Track")
    branch_a_pd_id = _branch_pd_id(draft, "Branch A")
    fake = _fake_with_options(draft, ["Alpha", "Beta"])
    after = draft.build_branch_condition(
        process_def_id=branch_a_pd_id,
        field_id=field_id,
        literal="Alpha",
        options=["Alpha", "Beta"],
    )
    _queue_read_back(fake, after)

    await ForgeSetBranchConditions(fake).execute(
        _request(branch_literals={"Branch A": "Alpha"})
    )

    written = next(c for c in fake.calls if c[0] == "put_draft")[1][3]
    written_wire = written.to_wire()
    expr_ids = written_wire[branch_a_pd_id]["ProcessDef::Expression"]
    assert len(expr_ids) == 1
    expr = written_wire[expr_ids[0]]
    assert expr["ProcessDef"] == branch_a_pd_id, (
        "owner key must be ProcessDef, a branch condition"
    )
    root_id = expr["Expression::Node"][0]
    root = written_wire[root_id]
    lhs_id, rhs_id = root["Node::Node"]
    assert (
        written_wire[lhs_id]["Type"] == "Field"
        and written_wire[lhs_id]["Field"] == field_id
    )
    assert (
        written_wire[rhs_id]["Type"] == "Static"
        and written_wire[rhs_id]["Value"] == "Alpha"
    )


@pytest.mark.asyncio
async def test_no_app_selected_refuses_before_any_port_call() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetBranchConditions(fake).execute(_request(app_id=""))
    assert exc_info.value.code == REFUSED
    assert fake.calls == []
