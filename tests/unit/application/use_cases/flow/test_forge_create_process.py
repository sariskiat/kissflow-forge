"""`use_cases.flow.forge_create_process.ForgeCreateProcess`."""

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
from app.application.models.requests.flow.forge_create_process_request import (
    ForgeCreateProcessRequest,
)
from app.application.use_cases.flow.forge_create_process import ForgeCreateProcess
from app.domain.entities.flow_draft import FlowDraft


def _draft(version: str) -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "_meta_version": version,
            "Root": "M1",
            "M1": {"Kind": "Model", "Type": "Root"},
        }
    )


@pytest.mark.asyncio
async def test_creates_a_process_shell_with_empty_fields() -> None:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [_draft("v1"), _draft("v2"), _draft("v2")]
    uc = ForgeCreateProcess(flow, template_path=None)

    resp = await uc.execute(
        ForgeCreateProcessRequest(
            name="N", publish=False, from_template=False, app_id="A1"
        )
    )

    assert resp.flow_id == "F1"
    assert resp.added == []
    assert resp.snapshot_version == "v1"
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_the_template_path_reaches_clone_template_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [_draft("v1"), _draft("v2"), _draft("v2")]
    uc = ForgeCreateProcess(flow, template_path="shapes/tenant_template.json")

    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)

    await uc.execute(
        ForgeCreateProcessRequest(
            name="N", publish=False, from_template=True, app_id="A1"
        )
    )

    assert captured == ["shapes/tenant_template.json"]


def _request(*, from_template: bool = True) -> ForgeCreateProcessRequest:
    return ForgeCreateProcessRequest(
        name="Expense Approval", publish=False, from_template=from_template, app_id="A1"
    )


@pytest.mark.asyncio
async def test_create_process_states_the_sections_the_template_injected() -> None:
    """Ported from tests/test_client.py (S4a): the report names every section the
    DEFAULT shell put on the flow, and its note tells the caller to cover them."""
    uc = ForgeCreateProcess(PersistingFlowRepository(), template_path=None)

    resp = await uc.execute(_request())

    assert resp.from_template is True
    assert resp.template_sections == [
        "In-Kissflow Template",
        "Public Form Template",
        "Request Details",
        "Request Info",
        "System",
    ]
    assert resp.template_steps == ["Completed", "Manager Approve", "Start"]
    assert resp.note is not None
    assert "owners" in resp.note and str(len(resp.template_sections)) in resp.note


@pytest.mark.asyncio
async def test_from_template_false_reports_an_empty_template_inventory() -> None:
    """Ported from tests/test_client.py: the bare scaffold says it brought nothing
    in, and carries no note (the old dict carried no `note` key at all)."""
    uc = ForgeCreateProcess(PersistingFlowRepository(), template_path=None)

    resp = await uc.execute(_request(from_template=False))

    assert resp.template_sections == [] and resp.template_required_fields == []
    assert resp.note is None


@pytest.mark.asyncio
async def test_an_unreadable_scaffold_is_stated_not_reported_as_an_empty_template() -> (
    None
):
    """Ported from tests/test_client.py: a failed inventory read is stated in
    `template_read_error` and the note, never passed off as an empty template, and
    never a failed create."""
    uc = ForgeCreateProcess(
        PersistingFlowRepository(failing_read_from=4), template_path=None
    )

    resp = await uc.execute(_request())

    assert resp.template_sections == [] and resp.template_required_fields == []
    assert resp.template_read_error is not None and "503" in resp.template_read_error
    assert resp.note is not None
    assert "not because the shell brought nothing in" in resp.note


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = ForgeCreateProcess(FakeFlowRepository(), template_path=None)
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            ForgeCreateProcessRequest(
                name="N", publish=False, from_template=True, app_id=""
            )
        )
    assert exc.value.code == "REFUSED"
