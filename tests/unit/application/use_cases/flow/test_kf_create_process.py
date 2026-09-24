"""`use_cases.flow.kf_create_process.KfCreateProcess`."""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow._field_spec_in import FieldSpecIn
from app.application.models.requests.flow.kf_create_process_request import (
    KfCreateProcessRequest,
)
from app.application.use_cases.flow.kf_create_process import KfCreateProcess
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
async def test_creates_a_process_with_a_field_bare_scaffold() -> None:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [
        _draft("v1"),
        _draft("v2"),
        FlowDraft.from_wire(
            {
                "_meta_version": "v3",
                "Root": "M1",
                "M1": {"Kind": "Model", "Type": "Root"},
                "FLD": {
                    "Kind": "Field",
                    "Model": "M1",
                    "Name": "Ticket No",
                    "Type": "Text",
                },
            }
        ),
        _draft("v3"),
    ]
    uc = KfCreateProcess(flow, template_path=None)

    resp = await uc.execute(
        KfCreateProcessRequest(
            name="Expense Approval",
            steps=["Review"],
            fields=[FieldSpecIn(name="Ticket No", type="Text")],
            publish=False,
            from_template=False,
            app_id="A1",
        )
    )

    assert resp.flow_id == "F1"
    assert resp.added == ["Ticket No"]
    assert resp.snapshot_version == "v1"
    assert resp.collateral == []
    assert_write_order(flow)


@pytest.mark.asyncio
async def test_the_template_path_reaches_clone_template_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = FakeFlowRepository()
    flow.results["create_flow"] = ["F1"]
    flow.results["get_draft"] = [_draft("v1"), _draft("v2"), _draft("v2")]
    uc = KfCreateProcess(flow, template_path="shapes/tenant_template.json")

    captured: list[str | None] = []

    def _fake_clone(self: FlowDraft, template_path: str | None) -> FlowDraft:
        captured.append(template_path)
        return self

    monkeypatch.setattr(FlowDraft, "clone_template_shell", _fake_clone)

    await uc.execute(
        KfCreateProcessRequest(
            name="N",
            steps=[],
            fields=[],
            publish=False,
            from_template=True,
            app_id="A1",
        )
    )

    assert captured == ["shapes/tenant_template.json"]


@pytest.mark.asyncio
async def test_no_app_selected_is_refused() -> None:
    uc = KfCreateProcess(FakeFlowRepository(), template_path=None)
    with pytest.raises(ApplicationError) as exc:
        await uc.execute(
            KfCreateProcessRequest(
                name="N",
                steps=[],
                fields=[],
                publish=False,
                from_template=True,
                app_id="",
            )
        )
    assert exc.value.code == "REFUSED"


def test_field_spec_input_refuses_a_blank_name() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FieldSpecIn(name="   ", type="Text")


def test_field_spec_input_refuses_an_unknown_type() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FieldSpecIn(name="X", type="NotARealType")
