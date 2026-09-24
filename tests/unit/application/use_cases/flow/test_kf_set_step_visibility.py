"""`KfSetStepVisibility`: the section-only predecessor of `ForgeSetVisibility`,
sharing the same `write_step_permissions` orchestration (spec G11, Stage D group
`d3_flow_workflow`)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.synthetic import OWNERS, synthetic_process_draft
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.flow.kf_set_step_visibility_request import (
    KfSetStepVisibilityRequest,
)
from app.application.use_cases.flow.kf_set_step_visibility import KfSetStepVisibility
from app.domain.entities.flow_draft import FlowDraft, progressive_matrix


def _request(**overrides: Any) -> KfSetStepVisibilityRequest:
    values: dict[str, Any] = {"flow_id": "F1", "owners": OWNERS, "app_id": "App1"}
    values.update(overrides)
    return KfSetStepVisibilityRequest(**values)


@pytest.mark.asyncio
async def test_happy_path_always_targets_process() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    after = draft.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]

    resp = await KfSetStepVisibility(fake).execute(_request())
    payload = resp.model_dump(mode="json")
    assert payload["pair_counts"]["missing"] == 0
    assert payload["snapshot_version"] == draft.version
    assert all(
        c[1][1] == "process" for c in fake.calls if c[0] in ("get_draft", "put_draft")
    )
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_offline_validation_error_names_the_bad_owner() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await KfSetStepVisibility(fake).execute(
            _request(owners={"NonexistentSection": ["Start"]})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_publish_runs_when_nothing_is_missing() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    after = draft.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]

    resp = await KfSetStepVisibility(fake).execute(_request(publish=True))
    assert resp.model_dump(mode="json")["published"] is True
    assert [c[0] for c in fake.calls].count("publish") == 1


@pytest.mark.asyncio
async def test_include_pairs_returns_the_pairs_key() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    matrix = progressive_matrix(draft, OWNERS)
    after = draft.set_step_permissions(matrix)

    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]

    resp = await KfSetStepVisibility(fake).execute(_request(include_pairs=True))
    payload = resp.model_dump(mode="json")
    assert "pairs" in payload


@pytest.mark.asyncio
async def test_no_app_selected_refuses_before_any_port_call() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(ApplicationError) as exc_info:
        await KfSetStepVisibility(fake).execute(_request(app_id=""))
    assert exc_info.value.code == REFUSED
    assert fake.calls == []
