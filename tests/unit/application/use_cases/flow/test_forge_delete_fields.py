"""Spec for app.application.use_cases.flow.forge_delete_fields.

Ports the matching cases of `tests/test_client.py`'s `delete_fields` tests onto the
new fake-port architecture. Not ported:
`test_delete_fields_deletes_a_user_field_cluster_rather_than_refusing_it`'s own
QueryDefinition-sweep assertion -- that is `FlowDraft.delete_nodes`'s own invariant,
already proven by the domain's own test suite, not observable through a fake port
that records rather than mutates; this file keeps that case's outer shape (a User
field deletes clean, with no blocker refusal).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_delete_fields_request import (
    ForgeDeleteFieldsRequest,
)
from app.application.use_cases.flow.forge_delete_fields import ForgeDeleteFields
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


def _request(**overrides: object) -> ForgeDeleteFieldsRequest:
    base: dict[str, object] = {
        "flow_id": "F1",
        "fields": ["drop"],
        "tables": None,
        "kind": "form",
        "publish": False,
        "app_id": "A1",
    }
    base.update(overrides)
    return ForgeDeleteFieldsRequest.model_validate(base)


@pytest.mark.asyncio
async def test_audits_absence_not_presence() -> None:
    """The delete audit is inverted: success is the name being GONE on read-back."""
    before = _form_with(
        FieldSpec(name="keep", type=FieldType.TEXT),
        FieldSpec(name="drop", type=FieldType.TEXT),
    )
    after = before.delete_nodes(("drop",))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeDeleteFields(fake).execute(_request(fields=["drop"]))

    assert resp.deleted == ["drop"] and resp.surviving == []
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_reports_the_cluster_it_swept() -> None:
    before = _form_with(FieldSpec(name="drop", type=FieldType.TEXT))
    after = before.delete_nodes(("drop",))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeDeleteFields(fake).execute(_request(fields=["drop"]))

    assert "1 Field node(s)" in resp.collateral
    assert "1 Column node(s)" in resp.collateral


@pytest.mark.asyncio
async def test_surviving_field_is_a_loud_failure_not_a_silent_pass() -> None:
    before = _form_with(FieldSpec(name="drop", type=FieldType.TEXT))
    fake = FakeFlowRepository()
    # read-back is queued UNCHANGED: the write was "accepted" but nothing changed.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(fields=["drop"], publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "surviving=['drop']" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == []


@pytest.mark.asyncio
async def test_unknown_name_never_reaches_put() -> None:
    before = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(fields=["a", "nope"]))

    assert exc_info.value.code == "VERIFY_FAILED"
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == [], "one bad name in a batch must delete none of the batch"


@pytest.mark.asyncio
async def test_refuses_when_a_surviving_formula_still_reads_the_field() -> None:
    before = _form_with(
        FieldSpec(name="Total", type=FieldType.NUMBER),
        FieldSpec(name="Qty", type=FieldType.NUMBER),
    ).set_field_computed("Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(fields=["Qty"]))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "left dangling" in exc_info.value.message and "Qty" in exc_info.value.message
    assert "forge_apply_fields" in exc_info.value.message, (
        "a refusal must name the way out"
    )
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_refuses_when_the_field_triggers_another_fields_visibility() -> None:
    before = _form_with(
        FieldSpec(name="Reason", type=FieldType.TEXT),
        FieldSpec(name="Flag", type=FieldType.BOOLEAN),
    ).set_conditional_visibility("Reason", "Flag", "EQUAL_TO", "true")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(fields=["Flag"]))

    assert "TRIGGER" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_refuses_when_a_surviving_event_script_names_the_field_id() -> None:
    before = _form_with(
        FieldSpec(name="Source", type=FieldType.TEXT),
        FieldSpec(name="Target", type=FieldType.TEXT),
    )
    wire = before.to_wire()
    tgt = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Name") == "Target"
    )
    before = FlowDraft.from_wire(wire).set_field_events(
        {"Source": [("onChange", f"kf.set('{tgt}');")]}
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(fields=["Target"]))

    assert "Script" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_deletes_a_user_field_cluster_rather_than_refusing_it() -> None:
    """A User field's QueryDefinition is swept, not refused: the caller has no tool
    that could remove it first, so a refusal there would be a dead end."""
    before = _form_with(FieldSpec(name="Owner", type=FieldType.USER))
    after = before.delete_nodes(("Owner",))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeDeleteFields(fake).execute(_request(fields=["Owner"]))

    assert resp.deleted == ["Owner"]


@pytest.mark.asyncio
async def test_publishes_only_after_the_absence_is_verified() -> None:
    before = _form_with(FieldSpec(name="drop", type=FieldType.TEXT))
    after = before.delete_nodes(("drop",))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeDeleteFields(fake).execute(
        _request(fields=["drop"], publish=True)
    )

    assert resp.published is True
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert len(publish_calls) == 1


@pytest.mark.asyncio
async def test_by_node_id_can_still_fail_its_read_back() -> None:
    """D2 / THE RULE: `fields` accepts a raw node id. The audit must key by node id,
    not by name -- a name-keyed audit can never see an id and would read an
    id-addressed delete as gone whether or not the write landed."""
    before = _form_with(FieldSpec(name="drop", type=FieldType.TEXT))
    wire = before.to_wire()
    fid = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "drop"
    )
    fake = FakeFlowRepository()
    # read-back is queued UNCHANGED: nothing actually landed.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(fields=[fid], publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert f"surviving=['{fid}']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_by_node_id_reports_a_real_delete_as_deleted() -> None:
    """The control: the id path must still report a delete that DID land."""
    before = _form_with(
        FieldSpec(name="keep", type=FieldType.TEXT),
        FieldSpec(name="drop", type=FieldType.TEXT),
    )
    wire = before.to_wire()
    fid = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "drop"
    )
    after = before.delete_nodes((fid,))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeDeleteFields(fake).execute(_request(fields=[fid]))

    assert resp.deleted == [fid] and resp.surviving == []


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDeleteFields(fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
