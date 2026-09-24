"""Spec for app.application.use_cases.flow.forge_apply_fields.

Ports the matching cases of `tests/test_client.py`'s `apply_fields_full` tests and
`tests/test_p4_surface.py`'s "forge_apply_fields extension" tests onto the new
fake-port architecture (see `test_kf_apply_field_change.py`'s own module docstring
for why a stateless fake reaches an "already exists" scenario differently than the
old stateful `FakeClient` did).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.flow.forge_apply_fields_request import (
    ForgeApplyFieldsRequest,
)
from app.application.use_cases.flow.forge_apply_fields import ForgeApplyFields
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_process_draft(version: str = "v1") -> dict[str, Any]:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


def _request(**overrides: object) -> ForgeApplyFieldsRequest:
    base: dict[str, object] = {
        "flow_id": "F1",
        "fields": [{"name": "alpha", "type": "Text"}],
        "kind": "process",
        "publish": False,
        "app_id": "A1",
    }
    base.update(overrides)
    return ForgeApplyFieldsRequest.model_validate(base)


@pytest.mark.asyncio
async def test_lands_field_validation_computed_and_conditional_together() -> None:
    before = FlowDraft.from_wire(_bare_process_draft())
    fields = [
        {"name": "Notes", "type": "Text", "default_value": "N/A"},
        {"name": "Source Number", "type": "Number"},
        {"name": "Computed Sample", "type": "Text"},
        {"name": "Show Details", "type": "Boolean"},
        {"name": "Details", "type": "Text"},
    ]
    validation = {
        "Notes": [{"operator": "MAX_LENGTH", "rhs": "10", "error_message": "Too long"}]
    }
    computed = {
        "Computed Sample": {
            "fn": "concatenate",
            "args": [{"static": "BR-"}, {"field": "Source Number"}],
        }
    }
    conditional_visibility = {
        "Details": {
            "trigger_field": "Show Details",
            "operator": "EQUAL_TO",
            "rhs": "true",
        }
    }

    # Compute the SAME offline transform the use case will run, so the queued
    # read-back genuinely reflects it (WriteOrder.apply() only writes through the
    # fake port, which records rather than mutates).
    specs = [
        FieldSpec(name="Notes", type=FieldType.TEXT, options={"DefaultValue": "N/A"}),
        FieldSpec(name="Source Number", type=FieldType.NUMBER),
        FieldSpec(name="Computed Sample", type=FieldType.TEXT),
        FieldSpec(name="Show Details", type=FieldType.BOOLEAN),
        FieldSpec(name="Details", type=FieldType.TEXT),
    ]
    formula = {
        "fn": "concatenate",
        "args": [{"static": "BR-"}, {"field": "Source Number"}],
    }
    after = (
        before.apply_changes(specs)
        .add_field_validation("Notes", "MAX_LENGTH", "10", error_message="Too long")
        .set_field_computed("Computed Sample", formula)
        .set_conditional_visibility("Details", "Show Details", "EQUAL_TO", "true")
    )

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeApplyFields(fake).execute(
        _request(
            fields=fields,
            validation=validation,
            computed=computed,
            conditional_visibility=conditional_visibility,
        )
    )

    assert set(resp.verified) == {f["name"] for f in fields}
    assert resp.missing == []
    assert resp.validations_verified == ["Notes:MAX_LENGTH:10"]
    assert resp.validations_missing == []
    assert resp.computed_verified == ["Computed Sample"]
    assert resp.computed_missing == []
    assert resp.conditional_verified == ["Details"]
    assert resp.conditional_missing == []
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_offline_rejection_never_reaches_put() -> None:
    before = FlowDraft.from_wire(_bare_process_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyFields(fake).execute(
            _request(
                fields=[{"name": "Details", "type": "Text"}],
                conditional_visibility={
                    "Details": {
                        "trigger_field": "Nope",
                        "operator": "EQUAL_TO",
                        "rhs": "true",
                    }
                },
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_conflict_when_draft_moved_under_us() -> None:
    """The fake port raises the conflict error when the version passed does
    not match; the use case lets it through unchanged, `code=CONFLICT`.
    Ported from `test_conflict_when_draft_moved_under_us` in
    `tests/test_client.py` (brief_d13_fix.md fix 8 -- group 1's report
    skipped this one)."""
    before = FlowDraft.from_wire(_bare_process_draft())

    class _ConflictingFake(FakeFlowRepository):
        async def put_draft(self, app_id, kind, flow_id, new, expect_version):
            raise RepositoryError("version drift", code="CONFLICT")

    fake = _ConflictingFake()
    fake.results["get_draft"] = [before]

    with pytest.raises(RepositoryError) as exc_info:
        await ForgeApplyFields(fake).execute(
            _request(fields=[{"name": "alpha", "type": "Text"}])
        )
    assert exc_info.value.code == "CONFLICT"


@pytest.mark.asyncio
async def test_a_missing_layer_is_a_failure_not_a_partial_success() -> None:
    """Rule 7: the read-back is queued as the UNCHANGED before-draft (the PUT was
    "accepted" but nothing actually landed) -- that is a failed write, never a
    success response with the problem sitting in `missing`/`validations_missing`."""
    before = FlowDraft.from_wire(_bare_process_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyFields(fake).execute(
            _request(
                fields=[{"name": "Notes", "type": "Text"}],
                validation={"Notes": [{"operator": "MAX_LENGTH", "rhs": "10"}]},
            )
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['Notes']" in exc_info.value.message
    assert "validations_missing=['Notes:MAX_LENGTH:10']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_reports_an_ignored_change_too() -> None:
    before = FlowDraft.from_wire(_bare_process_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyFields(fake).execute(
            _request(fields=[{"name": "alpha", "type": "Number"}])
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "changed_ignored=" in exc_info.value.message
    assert "remediation=['forge_delete_fields', 'forge_apply_fields']" in (
        exc_info.value.message
    )


@pytest.mark.asyncio
async def test_collateral_and_remediation_are_wired_from_the_before_after_diff() -> (
    None
):
    """Proves the use case wires `_fields.layout_collateral`'s output into the
    response (the helper's own moved/dropped-field logic is unit-tested directly in
    `test__fields.py`; the tiling algorithm that makes a real regroup move a field is
    the domain's own, tested there)."""
    placed_before = {
        **_bare_process_draft(),
        "S1": {
            "Id": "S1",
            "Kind": "Column",
            "Type": "Section",
            "Name": "Sec",
            "Column::Row": ["R1"],
        },
        "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["C1"]},
        "C1": {"Id": "C1", "Kind": "Column", "Type": "Text", "Start": 0, "End": 3},
        "Field_1": {
            "Id": "Field_1",
            "Kind": "Field",
            "Name": "existing",
            "Type": "Text",
            "Model": "M1",
            "Column": "C1",
        },
    }
    placed_after = {
        **placed_before,
        "C1": {"Id": "C1", "Kind": "Column", "Type": "Text", "Start": 3, "End": 6},
    }
    before = FlowDraft.from_wire(placed_before)
    after = FlowDraft.from_wire(placed_after)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeApplyFields(fake).execute(_request(fields=[]))

    assert len(resp.collateral) == 1 and "existing" in resp.collateral[0]
    assert resp.remediation == ["forge_apply_layout"]


@pytest.mark.asyncio
async def test_a_failed_write_still_names_its_layout_collateral() -> None:
    """Rule 7: a rebuild that moved a field's grid placement (collateral) and also
    failed to land a requested field must still say so in the raised message --
    the old code dropped `collateral` on this path (brief_d13_fix.md fix 3)."""
    placed_before = {
        **_bare_process_draft(),
        "S1": {
            "Id": "S1",
            "Kind": "Column",
            "Type": "Section",
            "Name": "Sec",
            "Column::Row": ["R1"],
        },
        "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["C1"]},
        "C1": {"Id": "C1", "Kind": "Column", "Type": "Text", "Start": 0, "End": 3},
        "Field_1": {
            "Id": "Field_1",
            "Kind": "Field",
            "Name": "existing",
            "Type": "Text",
            "Model": "M1",
            "Column": "C1",
        },
    }
    placed_after = {
        **placed_before,
        "C1": {"Id": "C1", "Kind": "Column", "Type": "Text", "Start": 3, "End": 6},
    }
    before = FlowDraft.from_wire(placed_before)
    after = FlowDraft.from_wire(placed_after)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyFields(fake).execute(
            _request(fields=[{"name": "Ghost", "type": "Text"}])
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['Ghost']" in exc_info.value.message
    assert "collateral=" in exc_info.value.message
    assert "existing" in exc_info.value.message
    assert "remediation=['forge_apply_layout']" in exc_info.value.message


@pytest.mark.asyncio
async def test_born_live_kind_refuses_a_publish_request() -> None:
    """A `dataset` draft is already live -- `publish=True` on it must be
    refused with a clear message, never silently accepted (ported intent of
    the old `apply_fields_full`'s born-live check; brief_d13_fix.md fix 8,
    mutation: `if False:` in place of the kind check)."""
    before = FlowDraft.from_wire(_bare_process_draft())
    after = before.apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyFields(fake).execute(
            _request(
                fields=[{"name": "Notes", "type": "Text"}],
                kind="dataset",
                publish=True,
            )
        )
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "has no publish route" in exc_info.value.message
    assert [c[0] for c in fake.calls].count("publish") == 0


@pytest.mark.asyncio
async def test_sections_only_still_writes_with_no_new_field() -> None:
    """A `sections` regroup with no field actually being added must still PUT
    -- the write gate (`added or groups or validations or computed or
    conditional`) must not skip the write just because nothing NEW landed
    (brief_d13_fix.md fix 8)."""
    before = FlowDraft.from_wire(_bare_process_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    after = before.regroup_into_sections(before.merge_groups([("Sec", ["alpha"])]))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeApplyFields(fake).execute(
        _request(
            fields=[{"name": "alpha", "type": "Text"}],
            sections={"Sec": ["alpha"]},
        )
    )
    assert resp.added == []
    assert [c[0] for c in fake.calls].count("put_draft") == 1


@pytest.mark.asyncio
async def test_a_true_no_op_never_calls_put_draft() -> None:
    """No new field, no sections, no validation/computed/conditional -- the
    write gate must skip PUT entirely, never write a no-op (brief_d13_fix.md
    fix 8)."""
    before = FlowDraft.from_wire(_bare_process_draft()).apply_changes(
        [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await ForgeApplyFields(fake).execute(
        _request(fields=[{"name": "alpha", "type": "Text"}])
    )
    assert resp.added == []
    assert resp.skipped == ["alpha"]
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyFields(fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
