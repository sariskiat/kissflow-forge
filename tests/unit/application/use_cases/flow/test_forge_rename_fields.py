"""Spec for app.application.use_cases.flow.forge_rename_fields.

Ports the matching cases of `tests/test_client.py`'s `rename_form_fields` tests
onto the new fake-port architecture, including
`test_rename_form_fields_keeps_the_node_id_so_events_and_permissions_survive`
(brief_d13_fix.md fix 8): `FlowDraft.rename_fields`'s node-id-preserving
invariant is the domain's own (proven again in
`tests/unit/domain/entities/test_flow_draft.py`), but THIS use case's own write
path is what a caller actually depends on, so it is asserted here too, on the
`FlowDraft` the use case actually sent to `put_draft`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_rename_fields_request import (
    ForgeRenameFieldsRequest,
)
from app.application.use_cases.flow.forge_rename_fields import ForgeRenameFields
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_form_draft(version: str = "v1") -> dict[str, Any]:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
    }


def _form_with(*specs: FieldSpec) -> FlowDraft:
    return FlowDraft.from_wire(_bare_form_draft()).apply_changes(list(specs))


def _request(**overrides: object) -> ForgeRenameFieldsRequest:
    base: dict[str, object] = {
        "flow_id": "F1",
        "renames": {"old": "new"},
        "kind": "form",
        "publish": False,
        "app_id": "A1",
    }
    base.update(overrides)
    return ForgeRenameFieldsRequest.model_validate(base)


@pytest.mark.asyncio
async def test_verifies_both_halves_of_the_rename() -> None:
    before = _form_with(FieldSpec(name="Tikcet No", type=FieldType.TEXT))
    after = before.rename_fields({"Tikcet No": "Ticket No"})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeRenameFields(fake).execute(
        _request(renames={"Tikcet No": "Ticket No"})
    )

    assert resp.verified == ["Tikcet No -> Ticket No"]
    assert resp.missing == [] and resp.stale == []
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_rename_keeps_the_node_id_so_events_and_permissions_survive() -> None:
    """The whole reason a rename beats delete-and-recreate. Ported from
    `test_rename_form_fields_keeps_the_node_id_so_events_and_permissions_survive`
    in `tests/test_client.py`, asserted on the `FlowDraft` the use case
    actually sent to `put_draft` (brief_d13_fix.md fix 8)."""
    before = _form_with(FieldSpec(name="old", type=FieldType.TEXT))
    field_id = next(
        k
        for k, v in before.to_wire().items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "old"
    )
    after = before.rename_fields({"old": "new"})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    await ForgeRenameFields(fake).execute(_request(renames={"old": "new"}))

    written = next(c for c in fake.calls if c[0] == "put_draft")[1][3]
    assert written.to_wire()[field_id]["Name"] == "new", "same node id, new label"


@pytest.mark.asyncio
async def test_reports_stale_when_the_old_name_survives() -> None:
    """A half-applied rename (old AND new both present) is worse than one that did
    not happen -- it must not read as success."""
    before = _form_with(FieldSpec(name="old", type=FieldType.TEXT))
    after_wire = before.rename_fields({"old": "new"}).to_wire()
    after_wire["Field_ghost"] = {
        "Id": "Field_ghost",
        "Kind": "Field",
        "Type": "Text",
        "Model": "M1",
        "Name": "old",
    }
    after = FlowDraft.from_wire(after_wire)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenameFields(fake).execute(
            _request(renames={"old": "new"}, publish=True)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "stale=['old -> new']" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == []


@pytest.mark.asyncio
async def test_refuses_a_collision_with_an_existing_name() -> None:
    before = _form_with(
        FieldSpec(name="a", type=FieldType.TEXT),
        FieldSpec(name="b", type=FieldType.TEXT),
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenameFields(fake).execute(_request(renames={"a": "b"}))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "already on this form" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_unknown_name_never_reaches_put() -> None:
    before = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenameFields(fake).execute(_request(renames={"nope": "x"}))

    assert exc_info.value.code == "VERIFY_FAILED"
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_a_no_op_rename_is_unchanged_not_stale() -> None:
    """D9: the collision guard exempts old == new; the read-back classification must
    not call that a `stale`, worst-bucket failure."""
    before = _form_with(FieldSpec(name="Ticket No", type=FieldType.TEXT))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await ForgeRenameFields(fake).execute(
        _request(renames={"Ticket No": "Ticket No"}, publish=True)
    )

    assert resp.unchanged == ["Ticket No -> Ticket No"]
    assert resp.stale == [] and resp.missing == [] and resp.verified == []
    assert resp.published is True
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert len(publish_calls) == 1


@pytest.mark.asyncio
async def test_a_no_op_rename_whose_field_vanished_is_still_missing() -> None:
    """The no-op exemption is on the CLASSIFICATION, never on the audit."""
    before = _form_with(FieldSpec(name="A", type=FieldType.TEXT))
    wire = before.to_wire()
    a_id = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A"
    )
    after = FlowDraft.from_wire({k: v for k, v in wire.items() if k != a_id})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenameFields(fake).execute(
            _request(renames={"A": "A"}, publish=True)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['A -> A']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeRenameFields(fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
