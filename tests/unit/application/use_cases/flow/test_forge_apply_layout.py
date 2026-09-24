"""Spec for app.application.use_cases.flow.forge_apply_layout.

Ports the matching cases of `tests/test_client.py`'s `apply_layout` tests onto the
new fake-port architecture.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_apply_layout_request import (
    ForgeApplyLayoutRequest,
)
from app.application.use_cases.flow.forge_apply_layout import ForgeApplyLayout
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType


def _bare_form_draft(version: str = "v1") -> dict[str, Any]:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
    }


def _request(**overrides: object) -> ForgeApplyLayoutRequest:
    base: dict[str, object] = {
        "flow_id": "F1",
        "layout": {"G": [[["a", 0, 6]]]},
        "kind": "form",
        "publish": False,
        "app_id": "A1",
    }
    base.update(overrides)
    return ForgeApplyLayoutRequest.model_validate(base)


def _laid_out_draft(*names: str) -> FlowDraft:
    """A form with `names` created and grouped together into section "G" -- the same
    two-step offline transform `apply_fields_and_layout` used to run (not itself
    ported, see `d1_flow_fields.md`), rebuilt here from `FlowDraft`'s own public
    methods purely as test setup."""
    draft = FlowDraft.from_wire(_bare_form_draft()).apply_changes(
        [FieldSpec(name=n, type=FieldType.TEXT) for n in names]
    )
    groups = [("G", list(names))]
    return draft.regroup_into_sections(draft.merge_groups(groups))


@pytest.mark.asyncio
async def test_refuses_an_invalid_span_before_paying_for_the_get() -> None:
    """E3: the pure span check runs before the live GET."""
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyLayout(fake).execute(_request(layout={"S": [[["a", 0, 99]]]}))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_reports_the_fields_it_retiled() -> None:
    """apply_exact_layout rebuilds a whole section's rows, so a field the PARTIAL
    spec does not name is MOVED into a trailing row."""
    before = _laid_out_draft("a", "b", "c")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await ForgeApplyLayout(fake).execute(_request(layout={"G": [[["a", 0, 6]]]}))

    assert len(resp.collateral) == 2
    assert all("re-tiled into a trailing row" in s for s in resp.collateral)
    assert any("'b'" in s for s in resp.collateral)
    assert any("'c'" in s for s in resp.collateral)
    assert resp.remediation == ["forge_apply_layout"]
    assert resp.verified == ["G"]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_reports_no_collateral_when_the_spec_names_every_field() -> None:
    before = _laid_out_draft("a", "b")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await ForgeApplyLayout(fake).execute(
        _request(layout={"G": [[["a", 0, 3], ["b", 3, 6]]]})
    )

    assert resp.collateral == [] and resp.remediation == []


@pytest.mark.asyncio
async def test_always_writes_even_with_no_field_change() -> None:
    before = _laid_out_draft("a")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    await ForgeApplyLayout(fake).execute(_request(layout={"G": [[["a", 0, 6]]]}))

    put_calls = [c for c in fake.calls if c[0] == "put_draft"]
    assert len(put_calls) == 1


@pytest.mark.asyncio
async def test_publish_true_publishes() -> None:
    before = _laid_out_draft("a")
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [before, before]

    resp = await ForgeApplyLayout(fake).execute(
        _request(layout={"G": [[["a", 0, 6]]]}, publish=True)
    )

    assert resp.published is True
    publish_calls = [c for c in fake.calls if c[0] == "publish"]
    assert len(publish_calls) == 1


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeApplyLayout(fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
