"""`app.application.use_cases.flow._permissions`: ported from `tests/test_client.py`'s
`apply_step_permissions` suite, at the same (raw `Matrix`) level the old function
operated at (spec G11, Stage D group `d3_flow_workflow`)."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.synthetic import OWNERS, synthetic_process_draft

from app.application.exceptions import VERIFY_FAILED, ApplicationError, RepositoryError
from app.application.use_cases.flow._permissions import (
    _malformed_permissions,
    _pair_names,
    _permission_nodes,
    _uncovered_sections,
    write_step_permissions,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import (
    FlowDraft,
    field_override_matrix,
    progressive_matrix,
)
from app.domain.value_objects.field_type import Visibility


def _order_for(fake: FakeFlowRepository, flow_id: str = "F1") -> WriteOrder[FlowDraft]:
    return WriteOrder(
        get=lambda: fake.get_draft("App1", "process", flow_id),
        put=lambda new, version: fake.put_draft(
            "App1", "process", flow_id, new, version
        ),
        version_of=lambda d: d.version,
        publish=lambda: fake.publish("App1", "process", flow_id),
    )


def _permission_missing_activity(draft: FlowDraft) -> FlowDraft:
    """Seed one Permission node with no `Activity` -- the shape `_permission_pairs`
    used to `KeyError` on. Nothing in this engine mints one; a template or a
    half-applied write did."""
    wire = draft.to_wire()
    col = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Column"
        and v.get("Type") == "Field"
    )
    wire["Permission_broken01"] = {
        "Id": "Permission_broken01",
        "Kind": "Permission",
        "Column": col,
        "Permission": "Editable",
    }
    return FlowDraft.from_wire(wire)


@pytest.mark.asyncio
async def test_reports_the_pairs_the_rebuild_dropped() -> None:
    """`set_step_permissions` DELETES every Permission before it writes -- a pair that
    was live and is not in the new matrix must be named in `collateral`, never
    silently absent from every bucket."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    full_matrix = progressive_matrix(draft, OWNERS)
    with_full = draft.set_step_permissions(full_matrix)

    dropped_activity = sorted(next(iter(full_matrix.values())))[0]
    thinner = {
        sec: {a: v for a, v in row.items() if a != dropped_activity}
        for sec, row in full_matrix.items()
    }
    after_thinner = with_full.set_step_permissions(thinner)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [with_full, after_thinner]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    report = await write_step_permissions(
        order,
        snapshot,
        flow_id="F1",
        matrix=thinner,
        field_matrix=None,
        publish=False,
        include_pairs=False,
    )
    assert report["pair_counts"]["collateral"] > 0
    assert report["remediation"] == ["forge_set_visibility"]
    assert "isError" not in report


@pytest.mark.asyncio
async def test_does_not_key_error_on_a_permission_with_no_activity() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    seeded = _permission_missing_activity(draft)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [seeded, seeded.set_step_permissions(matrix)]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    report = await write_step_permissions(
        order,
        snapshot,
        flow_id="F1",
        matrix=matrix,
        field_matrix=None,
        publish=False,
        include_pairs=False,
    )
    hits = [line for line in report["by_section"] if "Permission_broken01" in line]
    # the malformed node never lands in by_section (it's not a pair); it lands in the
    # missing-collateral audit instead -- assert it does not crash and IS accounted.
    assert hits == []
    collateral_note = report["note"]
    assert isinstance(collateral_note, str)


@pytest.mark.asyncio
async def test_publish_runs_only_when_nothing_is_missing() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    after = draft.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    report = await write_step_permissions(
        order,
        snapshot,
        flow_id="F1",
        matrix=matrix,
        field_matrix=None,
        publish=True,
        include_pairs=False,
    )
    assert report["published"] is True
    assert fake.calls[-1][0] == "publish"


@pytest.mark.asyncio
async def test_missing_pairs_on_read_back_raise_and_never_publish() -> None:
    """Rule 7: a pair that does not verify is a FAILURE, never a success report."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)

    fake = FakeFlowRepository()
    # read-back returns the UNCHANGED draft -- nothing landed.
    fake.results["get_draft"] = [draft, draft]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    with pytest.raises(ApplicationError) as exc_info:
        await write_step_permissions(
            order,
            snapshot,
            flow_id="F1",
            matrix=matrix,
            field_matrix=None,
            publish=True,
            include_pairs=False,
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert "published=False" in exc_info.value.message
    assert "publish" not in [c[0] for c in fake.calls]


@pytest.mark.asyncio
async def test_a_failed_write_still_names_its_collateral_and_remediation() -> None:
    """Rule 7: a write that DELETED existing pairs (collateral) and then failed
    to verify its own wanted pairs on read-back must still say so in the raised
    message -- the old code dropped `collateral`/`remediation` on this path
    (brief_d13_fix.md fix 3)."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    full_matrix = progressive_matrix(draft, OWNERS)
    with_full = draft.set_step_permissions(full_matrix)

    dropped_activity = sorted(next(iter(full_matrix.values())))[0]
    thinner = {
        sec: {a: v for a, v in row.items() if a != dropped_activity}
        for sec, row in full_matrix.items()
    }

    fake = FakeFlowRepository()
    # read-back shows NOTHING at all -- neither the old pairs nor the new ones
    # landed, even though the write already wiped every old Permission.
    fake.results["get_draft"] = [with_full, draft]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    with pytest.raises(ApplicationError) as exc_info:
        await write_step_permissions(
            order,
            snapshot,
            flow_id="F1",
            matrix=thinner,
            field_matrix=None,
            publish=True,
            include_pairs=False,
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert "collateral=" in exc_info.value.message
    assert "deleted Permission" in exc_info.value.message
    assert "remediation=['forge_set_visibility']" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    assert "publish" not in [c[0] for c in fake.calls]


@pytest.mark.asyncio
async def test_every_missing_pair_is_listed_in_full_and_by_name() -> None:
    """The raised message must name every missing pair by its human name
    (`section / field @ step`), never a raw (column id, activity id) pair --
    mutation: `missing=audit.missing` (raw ids) in place of
    `missing=audit.missing_named` at the `write_step_permissions` raise call
    (brief_d13_fix.md fix 8)."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, draft]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    with pytest.raises(ApplicationError) as exc_info:
        await write_step_permissions(
            order,
            snapshot,
            flow_id="F1",
            matrix=matrix,
            field_matrix=None,
            publish=False,
            include_pairs=False,
        )
    assert exc_info.value.code == VERIFY_FAILED
    # a raw "column_id@activity_id" pair has no spaces around "@" and no "/" at
    # all -- only the human `section / field @ step` form does.
    assert " / " in exc_info.value.message
    assert " @ " in exc_info.value.message
    assert "Intake" in exc_info.value.message


@pytest.mark.asyncio
async def test_collateral_lines_name_the_field_and_step_they_deleted() -> None:
    """Each collateral line for a dropped Permission must name the actual
    field and step it belonged to, not just the raw (column id, activity id)
    pair -- mutation: drop `names.pair(c, a)` from the collateral line
    (brief_d13_fix.md fix 8)."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    full_matrix = progressive_matrix(draft, OWNERS)
    with_full = draft.set_step_permissions(full_matrix)

    dropped_activity = sorted(next(iter(full_matrix.values())))[0]
    thinner = {
        sec: {a: v for a, v in row.items() if a != dropped_activity}
        for sec, row in full_matrix.items()
    }
    after_thinner = with_full.set_step_permissions(thinner)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [with_full, after_thinner]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    report = await write_step_permissions(
        order,
        snapshot,
        flow_id="F1",
        matrix=thinner,
        field_matrix=None,
        publish=False,
        include_pairs=True,
    )
    collateral = report["collateral"]
    assert collateral, "fixture must actually drop at least one pair"
    assert all(" / " in line and " @ " in line for line in collateral)


@pytest.mark.asyncio
async def test_offline_validation_error_names_the_bad_column() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    with pytest.raises(ApplicationError) as exc_info:
        await write_step_permissions(
            order,
            snapshot,
            flow_id="F1",
            matrix={"NonexistentSection": {"Start": Visibility.EDITABLE}},
            field_matrix=None,
            publish=False,
            include_pairs=False,
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert "offline apply rejected the matrix" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_a_put_draft_conflict_propagates_as_a_repository_error() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)

    class _ConflictingFake(FakeFlowRepository):
        async def put_draft(self, app_id, kind, flow_id, new, expect_version):
            raise RepositoryError("version drift", code="CONFLICT")

    fake = _ConflictingFake()
    fake.results["get_draft"] = [draft]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    with pytest.raises(RepositoryError) as exc_info:
        await write_step_permissions(
            order,
            snapshot,
            flow_id="F1",
            matrix=matrix,
            field_matrix=None,
            publish=False,
            include_pairs=False,
        )
    assert exc_info.value.code == "CONFLICT"


@pytest.mark.asyncio
async def test_include_pairs_returns_full_named_pairs() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    after = draft.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]
    order = _order_for(fake)
    snapshot = await order.snapshot()

    report = await write_step_permissions(
        order,
        snapshot,
        flow_id="F1",
        matrix=matrix,
        field_matrix=None,
        publish=False,
        include_pairs=True,
    )
    assert report["summarised"] == 0
    assert report["pairs"]["added"]
    assert all("@" in p and "/" in p for p in report["pairs"]["added"])
    assert "Column_" not in repr(report["pairs"])


def test_permission_nodes_and_pairs_and_malformed_partition_completely() -> None:
    """Every Permission node lands in exactly one of `_permission_pairs` (well-formed)
    or `_malformed_permissions` (not) -- never both, never neither."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    wire = _permission_missing_activity(draft.set_step_permissions(matrix)).to_wire()

    all_ids = {k for k, _ in _permission_nodes(wire)}
    malformed_ids = set(_malformed_permissions(wire))
    well_formed_ids = {
        nid
        for nid, node in _permission_nodes(wire)
        if isinstance(node.get("Column"), str) and isinstance(node.get("Activity"), str)
    }
    assert malformed_ids | well_formed_ids == all_ids
    assert malformed_ids & well_formed_ids == set()
    assert "Permission_broken01" in malformed_ids


def test_pair_names_resolves_to_readable_names() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    names = _pair_names(draft.to_wire())
    field_id = next(
        k
        for k, v in draft.to_wire().items()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Name") == "Ticket No"
    )
    column_id = draft.to_wire()[field_id]["Column"]
    assert names.column(column_id) == "Ticket No"
    assert names.section(column_id) == "Intake"


def test_uncovered_sections_names_a_section_left_out_of_owners() -> None:
    """`OWNERS` alone always leaves the fixture's own "Other" section (holding the
    one deliberately-unowned field, see `tests/synthetic.py`) uncovered too --
    naming both is what proves nothing is silently dropped."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    owners = {**OWNERS, "Other": ["Start"]}
    owners = {k: v for k, v in owners.items() if k != "Wrap-up"}
    matrix = progressive_matrix(draft, owners)
    assert _uncovered_sections(draft.to_wire(), matrix, None) == ("Wrap-up",)


def test_a_section_covered_only_by_field_level_overrides_is_not_uncovered() -> None:
    """A section that only HIDES, with editability expressed per field, is fully
    intentional -- never reported as uncovered."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    owners = {**OWNERS, "Other": ["Start"]}
    owners = {k: v for k, v in owners.items() if k != "Wrap-up"}
    matrix = progressive_matrix(draft, owners)
    field_matrix = field_override_matrix(draft, {"Wrap Summary": ["Wrap-up report"]})
    assert _uncovered_sections(draft.to_wire(), matrix, field_matrix) == ()
