"""`ForgeSetEvents`: ported from `tests/test_client.py`'s
`apply_field_events` cases (pre-refactor), now against the response DTO or
the raised `ApplicationError` and its code, with
`tests.fakes.flow.FakeFlowRepository`."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_set_events_request import (
    ForgeSetEventsRequest,
)
from app.application.use_cases.flow.forge_set_events import ForgeSetEvents
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType

_BARE = {
    "Root": "M1",
    "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
}


def _form_with_text_field(name: str = "Source") -> FlowDraft:
    d = (
        FlowDraft.from_wire(_BARE)
        .apply_changes([FieldSpec(name=name, type=FieldType.TEXT)])
        .to_wire()
    )
    return FlowDraft.from_wire(d)


def _request(**overrides: Any) -> ForgeSetEventsRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "events": {"Source": [("onChange", "kf.x();")]},
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeSetEventsRequest(**fields)


@pytest.mark.asyncio
async def test_wires_and_verifies() -> None:
    before = _form_with_text_field()
    after = before.set_field_events({"Source": [("onChange", "kf.x();")]})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetEvents(flow=fake).execute(_request())

    assert resp.fields == ["Source"]
    assert resp.verified == ["Source"]
    assert resp.missing == []
    assert resp.triggers == ["Source (Text) -> onChange"]
    assert resp.derived == []
    assert resp.published is False
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_publishes_when_requested_and_verified() -> None:
    before = _form_with_text_field()
    after = before.set_field_events({"Source": [("onChange", "kf.x();")]})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetEvents(flow=fake).execute(_request(publish=True))

    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_draft",
        "put_draft",
        "get_draft",
        "publish",
    ]


@pytest.mark.asyncio
async def test_derives_the_trigger_when_none_is_given() -> None:
    before = _form_with_text_field("Source")
    after = before.set_field_events({"Source": [("onChange", "kf.x();")]})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetEvents(flow=fake).execute(
        _request(events={"Source": [(None, "kf.x();")]})
    )

    assert resp.derived == ["Source"]
    assert resp.triggers == ["Source (Text) -> onChange"]


@pytest.mark.asyncio
async def test_trigger_check_refusal_never_reaches_put() -> None:
    before = _form_with_text_field()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetEvents(flow=fake).execute(
            _request(events={"Source": [("onSelect", "kf.x();")]})
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "field-event trigger check refused the spec" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_offline_rejection_of_an_unknown_field_never_reaches_put() -> None:
    """An unknown field NAME with a stated trigger passes the trigger check
    (nothing to derive, nothing to contradict) but `FlowDraft.set_field_events`
    itself refuses it -- the second, distinct offline-rejection door."""
    before = _form_with_text_field()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetEvents(flow=fake).execute(
            _request(events={"Ghost": [("onChange", "1;")]})
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "offline set_field_events rejected the spec" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_missing_field_raises_verify_failed_and_skips_publish() -> None:
    """Rule 7: a write that did not fully land is a failure, never a success
    response."""
    before = _form_with_text_field()
    fake = FakeFlowRepository()
    # the read-back never reflects the write.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetEvents(flow=fake).execute(_request(publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['Source']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_a_family_inferred_trigger_still_verifies_as_success() -> None:
    """CLAUDE.md Field events: uncertainty about the trigger is not a
    failure -- only `missing` drives the raise."""
    before = _form_with_text_field("Who")
    # User -> onSelect is family-inferred, not live-confirmed (unverified,
    # but not missing).
    wire = before.to_wire()
    field_id = next(
        k for k, v in wire.items() if isinstance(v, dict) and v.get("Name") == "Who"
    )
    wire[field_id]["Type"] = "User"
    before_user = FlowDraft.from_wire(wire)
    after = before_user.set_field_events({"Who": [("onSelect", "kf.x();")]})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before_user, after]

    resp = await ForgeSetEvents(flow=fake).execute(
        _request(events={"Who": [(None, "kf.x();")]})
    )

    assert resp.missing == []
    assert resp.verified == ["Who"]
    assert len(resp.unverified) == 1


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetEvents(flow=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
