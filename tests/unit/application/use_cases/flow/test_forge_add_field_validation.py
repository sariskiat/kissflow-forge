"""`ForgeAddFieldValidation`: ported from `tests/test_client.py`'s
`apply_field_validation` cases (pre-refactor), now against the response DTO
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
from app.application.models.requests.flow.forge_add_field_validation_request import (
    ForgeAddFieldValidationRequest,
)
from app.application.use_cases.flow.forge_add_field_validation import (
    ForgeAddFieldValidation,
)
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _form_with_notes_field() -> FlowDraft:
    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    d = (
        FlowDraft.from_wire(bare)
        .apply_changes([FieldSpec(name="Notes", type=FieldType.TEXT)])
        .to_wire()
    )
    return FlowDraft.from_wire(d)


def _request(**overrides: Any) -> ForgeAddFieldValidationRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "rules": {"Notes": [("CONTAINS", "important"), ("MAX_LENGTH", "200")]},
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeAddFieldValidationRequest(**fields)


@pytest.mark.asyncio
async def test_wires_and_verifies() -> None:
    before = _form_with_notes_field()
    after = before.add_field_validation(
        "Notes", "CONTAINS", "important"
    ).add_field_validation("Notes", "MAX_LENGTH", "200")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeAddFieldValidation(flow=fake).execute(_request())

    assert resp.flow_id == "F1"
    assert resp.field_name == "Notes"
    assert resp.rules == [("CONTAINS", "important"), ("MAX_LENGTH", "200")]
    assert resp.verified == [("CONTAINS", "important"), ("MAX_LENGTH", "200")]
    assert resp.missing == []
    assert resp.published is False
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_with_publish_publishes_when_clean() -> None:
    before = _form_with_notes_field()
    after = before.add_field_validation("Notes", "MAX_LENGTH", "100")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeAddFieldValidation(flow=fake).execute(
        _request(rules={"Notes": [("MAX_LENGTH", "100")]}, publish=True)
    )

    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_draft",
        "put_draft",
        "get_draft",
        "publish",
    ]


@pytest.mark.asyncio
async def test_offline_rejection_never_reaches_put() -> None:
    before = _form_with_notes_field()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddFieldValidation(flow=fake).execute(
            _request(rules={"NoSuchField": [("CONTAINS", "x")]})
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "offline add_field_validation rejected" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_handles_multiple_fields() -> None:
    bare = {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
    }
    before = FlowDraft.from_wire(
        FlowDraft.from_wire(bare)
        .apply_changes(
            [
                FieldSpec(name="A", type=FieldType.TEXT),
                FieldSpec(name="B", type=FieldType.TEXT),
            ]
        )
        .to_wire()
    )
    after = before.add_field_validation("A", "CONTAINS", "1").add_field_validation(
        "B", "MAX_LENGTH", "50"
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeAddFieldValidation(flow=fake).execute(
        _request(rules={"A": [("CONTAINS", "1")], "B": [("MAX_LENGTH", "50")]})
    )

    assert resp.verified == [("CONTAINS", "1"), ("MAX_LENGTH", "50")]
    assert resp.missing == []


@pytest.mark.asyncio
async def test_missing_rule_raises_verify_failed_and_skips_publish() -> None:
    """Rule 7: a write that did not fully land is a failure, never a success
    response."""
    before = _form_with_notes_field()
    fake = FakeFlowRepository()
    # the read-back never reflects the write.
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddFieldValidation(flow=fake).execute(
            _request(rules={"Notes": [("CONTAINS", "xyz")]}, publish=True)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=[('CONTAINS', 'xyz')]" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddFieldValidation(flow=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
