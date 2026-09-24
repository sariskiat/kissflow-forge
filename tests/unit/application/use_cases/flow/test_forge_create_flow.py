"""`use_cases.flow.forge_create_flow.ForgeCreateFlow`."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.flow_lifecycle import (
    PersistingFlowRepository,
)
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_create_flow_request import (
    ForgeCreateFlowRequest,
)
from app.application.use_cases.flow.forge_create_flow import ForgeCreateFlow


@pytest.mark.asyncio
async def test_creates_a_born_live_dataset() -> None:
    flow = FakeFlowRepository()
    flow.results["create_dataset"] = [{"_id": "D1", "Status": "Live"}]
    uc = ForgeCreateFlow(flow)

    resp = await uc.execute(
        ForgeCreateFlowRequest(kind="dataset", name="Orders", extra=None, app_id="A1")
    )

    assert resp.kind == "dataset"
    assert resp.flow_id == "D1"
    assert resp.born_live is True
    assert resp.note is None
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_case_requires_item_type_and_prefix() -> None:
    uc = ForgeCreateFlow(FakeFlowRepository())

    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgeCreateFlowRequest(kind="case", name="Support", extra=None, app_id="A1")
        )
    assert exc.value.code == "VERIFY_FAILED"


@pytest.mark.asyncio
async def test_create_flow_any_process_states_the_template_note() -> None:
    """Ported from tests/test_client.py: forge_create_flow's own note wording (it
    closes with `extra={'from_template': False}`, not `from_template=False`)."""
    uc = ForgeCreateFlow(PersistingFlowRepository())

    resp = await uc.execute(
        ForgeCreateFlowRequest(kind="process", name="Expense Approval", app_id="A1")
    )

    assert resp.from_template is True
    assert resp.note is not None
    assert "extra={'from_template': False}" in resp.note
    assert str(len(resp.template_sections)) in resp.note


@pytest.mark.asyncio
async def test_create_flow_any_states_an_unreadable_template_read() -> None:
    """Ported from tests/test_client.py: the flow exists, the inventory read died --
    stated, never an empty template, never a failed create."""
    uc = ForgeCreateFlow(PersistingFlowRepository(failing_read_from=2))

    resp = await uc.execute(
        ForgeCreateFlowRequest(kind="process", name="Expense Approval", app_id="A1")
    )

    assert resp.flow_id == "F1"
    assert resp.template_sections == [] and resp.template_required_fields == []
    assert resp.template_read_error is not None and "503" in resp.template_read_error
    assert resp.note is not None
    assert "not because the shell brought nothing in" in resp.note


@pytest.mark.asyncio
async def test_create_flow_any_born_live_kinds_carry_no_template_inventory() -> None:
    """Ported from tests/test_client.py: a list has no scaffold, so no inventory
    and no note (the old dict carried no `note` key at all)."""
    uc = ForgeCreateFlow(PersistingFlowRepository())

    resp = await uc.execute(
        ForgeCreateFlowRequest(kind="list", name="Urgency Levels", app_id="A1")
    )

    assert resp.from_template is False and resp.template_sections == []
    assert resp.note is None


@pytest.mark.asyncio
async def test_process_kind_uses_the_configured_template_path_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`brief_stage_d_common.md` review fix 1: the constructor's own config value
    fills `extra["template_path"]` for `kind="process"` when the caller gave
    none -- mirrors kf_create_process/forge_create_process's own wiring."""
    from app.domain.entities.flow_draft import FlowDraft

    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)
    uc = ForgeCreateFlow(
        PersistingFlowRepository(), template_path="shapes/tenant_template.json"
    )

    await uc.execute(
        ForgeCreateFlowRequest(kind="process", name="N", extra=None, app_id="A1")
    )

    assert captured == ["shapes/tenant_template.json"]


@pytest.mark.asyncio
async def test_process_kind_leaves_a_caller_supplied_template_path_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.entities.flow_draft import FlowDraft

    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)
    uc = ForgeCreateFlow(
        PersistingFlowRepository(), template_path="shapes/tenant_template.json"
    )

    await uc.execute(
        ForgeCreateFlowRequest(
            kind="process",
            name="N",
            extra={"template_path": "shapes/caller_template.json"},
            app_id="A1",
        )
    )

    assert captured == ["shapes/caller_template.json"]


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = ForgeCreateFlow(FakeFlowRepository())
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgeCreateFlowRequest(kind="form", name="X", extra=None, app_id="")
        )
    assert exc.value.code == "REFUSED"
