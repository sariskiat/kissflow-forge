"""`ForgeSetStyles`: ported from `tests/test_client.py`'s
`apply_section_style` cases (pre-refactor), now against the response DTO or
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
from app.application.models.requests.flow.forge_set_styles_request import (
    ForgeSetStylesRequest,
)
from app.application.use_cases.flow.forge_set_styles import ForgeSetStyles
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType

_BARE = {
    "Root": "M1",
    "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
}


def _form_with_section_m() -> FlowDraft:
    d = (
        FlowDraft.from_wire(_BARE)
        .apply_changes([FieldSpec(name="A", type=FieldType.TEXT)])
        .to_wire()
    )
    d = FlowDraft.from_wire(d).regroup_into_sections([("M", ["A"])]).to_wire()
    return FlowDraft.from_wire(d)


def _request(**overrides: Any) -> ForgeSetStylesRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "styles": {"M": {"Section.Bg.Color": "Color.Info.300"}},
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeSetStylesRequest(**fields)


@pytest.mark.asyncio
async def test_wires_and_verifies() -> None:
    before = _form_with_section_m()
    after = before.set_section_style({"M": {"Section.Bg.Color": "Color.Info.300"}})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetStyles(flow=fake).execute(_request())

    assert resp.sections == ["M"]
    assert resp.verified == ["M"]
    assert resp.missing == []
    assert resp.published is False
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_publishes_when_requested_and_verified() -> None:
    before = _form_with_section_m()
    after = before.set_section_style({"M": {"Section.Bg.Color": "Color.Info.300"}})
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetStyles(flow=fake).execute(_request(publish=True))

    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_draft",
        "put_draft",
        "get_draft",
        "publish",
    ]


@pytest.mark.asyncio
async def test_root_chain_verified() -> None:
    before = FlowDraft.from_wire(_BARE)
    root_style = {
        "Form.Field.Color": "Color.Primary.500",
        "Form.Bg.Color": {"ref": "Color.Transparent"},
    }
    after = before.set_section_style(
        {}, root_style=root_style, hint_text_position="Icon"
    )
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, after]

    resp = await ForgeSetStyles(flow=fake).execute(
        _request(styles={}, root_style=root_style, hint_text_position="Icon")
    )

    assert resp.sections == ["<root>"]
    assert resp.verified == ["<root>"]
    assert resp.missing == []


@pytest.mark.asyncio
async def test_unknown_section_rejected_before_any_write() -> None:
    before = _form_with_section_m()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetStyles(flow=fake).execute(
            _request(styles={"NoSuchSection": {"Section.Bg.Color": "Color.Info.300"}})
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_missing_section_raises_verify_failed_and_skips_publish() -> None:
    """Rule 7: a write that did not fully land is a failure, never a success
    response."""
    before = _form_with_section_m()
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetStyles(flow=fake).execute(_request(publish=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing=['M']" in exc_info.value.message
    assert "published=False" in exc_info.value.message


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetStyles(flow=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
