"""Spec for app.application.use_cases.flow.forge_set_required.

Ports the matching cases of `tests/test_client.py`'s `apply_required` tests onto the
new fake-port architecture. The four old `test_apply_required_*_error_returns_err`
cases (get/put/read-back/publish each returning `Err`) are not ported: the port
contract now guarantees `FlowRepository`'s methods raise `RepositoryError` directly
rather than returning a sentinel (`app.application.interfaces.flow.FlowRepository`'s
own docstring), so there is nothing left for THIS layer to translate --
`test_a_repository_error_propagates_unchanged` below proves the one thing this layer
still owns: it does not swallow or wrap that exception.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.flow.forge_set_required_request import (
    ForgeSetRequiredRequest,
)
from app.application.use_cases.flow.forge_set_required import ForgeSetRequired
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


def _request(**overrides: object) -> ForgeSetRequiredRequest:
    base: dict[str, object] = {
        "flow_id": "F1",
        "required": ["a"],
        "kind": "form",
        "publish": False,
        "app_id": "A1",
    }
    base.update(overrides)
    return ForgeSetRequiredRequest.model_validate(base)


@pytest.mark.asyncio
async def test_sets_verifies_and_reports_what_it_cleared() -> None:
    """SET, not a patch: everything unnamed comes back optional."""
    before = _form_with(
        FieldSpec(name="a", type=FieldType.TEXT, required=True),
        FieldSpec(name="b", type=FieldType.TEXT, required=True),
        FieldSpec(name="c", type=FieldType.TEXT),
    )
    after = before.set_required({"a"})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetRequired(fake).execute(_request(required=["a"]))

    assert resp.missing == []
    assert sorted(resp.verified) == ["a", "b", "c"]
    assert resp.cleared == ["b"], "b silently lost its Required flag -- say so"
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_refuses_a_computed_field() -> None:
    """FlowDraft.set_required's own war story: a computed field marked Required
    blocked step 1 live, because nobody can type the value that would satisfy it."""
    before = _form_with(
        FieldSpec(name="Total", type=FieldType.NUMBER),
        FieldSpec(name="Qty", type=FieldType.NUMBER),
    ).set_field_computed("Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(required=["Total"]))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "computed" in exc_info.value.message
    assert "unsubmittable" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_refuses_a_sequence_number_field() -> None:
    before = _form_with(FieldSpec(name="Case ID", type=FieldType.TEXT))
    wire = before.to_wire()
    fid = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Name") == "Case ID"
    )
    wire[fid]["Type"] = "SequenceNumber"
    before = FlowDraft.from_wire(wire)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(required=["Case ID"]))

    assert "SequenceNumber" in exc_info.value.message
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_unknown_name_never_reaches_put() -> None:
    """An unresolvable name is not "unfillable" (it never reaches the pre-check at
    all) -- `FlowDraft.set_required` itself is what refuses it."""
    before = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(required=["nope"]))

    assert exc_info.value.code == "VERIFY_FAILED"
    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert put_calls == []


@pytest.mark.asyncio
async def test_missing_is_a_loud_failure_on_read_back() -> None:
    before = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(required=["a"], publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['a']" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert publish_calls == []


@pytest.mark.asyncio
async def test_publish_success() -> None:
    before = _form_with(FieldSpec(name="a", type=FieldType.TEXT))
    after = before.set_required({"a"})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetRequired(fake).execute(_request(required=["a"], publish=True))

    assert resp.published is True
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert len(publish_calls) == 1


@pytest.mark.asyncio
async def test_reports_a_requested_field_that_vanished_as_missing() -> None:
    """D4, the output invariant: a requested name present BEFORE the write and
    absent from the read-back must land in `missing`, not in no bucket at all."""
    before = _form_with(
        FieldSpec(name="A", type=FieldType.TEXT),
        FieldSpec(name="B", type=FieldType.TEXT),
    )
    wire = before.to_wire()
    a_id = next(
        k
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A"
    )
    dropped = {k: v for k, v in wire.items() if k != a_id}
    after = FlowDraft.from_wire(dropped)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(required=["A"], publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "'A'" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_still_audits_the_whole_read_back_population() -> None:
    """The control: a field the caller never named that comes back with the wrong
    flag must still be audited (the SET-semantics union, not just the requested
    set)."""
    before = _form_with(
        FieldSpec(name="a", type=FieldType.TEXT),
        FieldSpec(name="b", type=FieldType.TEXT, required=True),
    )
    after = before.set_required({"a"})  # b SHOULD clear, but the read-back disagrees
    wire = after.to_wire()
    for v in wire.values():
        if isinstance(v, dict) and v.get("Name") == "b":
            v["Required"] = True  # refuses to be cleared
    after = FlowDraft.from_wire(wire)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(required=["a"]))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['b']" in exc_info.value.message


@pytest.mark.asyncio
async def test_a_repository_error_propagates_unchanged() -> None:
    class _FailingFlow(FakeFlowRepository):
        async def get_draft(self, app_id, kind, flow_id):  # type: ignore[override]
            raise RepositoryError("500 Internal Server Error")

    with pytest.raises(RepositoryError):
        await ForgeSetRequired(_FailingFlow()).execute(_request())


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetRequired(fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
