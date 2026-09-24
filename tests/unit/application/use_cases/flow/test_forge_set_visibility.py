"""`ForgeSetVisibility`: ported from `tests/test_client.py`'s
`apply_step_permissions` suite (spec G11, Stage D group `d3_flow_workflow`)."""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.synthetic import OWNERS, synthetic_process_draft
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.flow.forge_set_visibility_request import (
    ForgeSetVisibilityRequest,
)
from app.application.use_cases.flow.forge_set_visibility import ForgeSetVisibility
from app.domain.entities.flow_draft import (
    FlowDraft,
    field_override_matrix,
    progressive_matrix,
)


def _request(**overrides: Any) -> ForgeSetVisibilityRequest:
    values: dict[str, Any] = {"flow_id": "F1", "owners": OWNERS, "app_id": "App1"}
    values.update(overrides)
    return ForgeSetVisibilityRequest(**values)


def _fake_after_matrix(
    draft: FlowDraft,
    owners: dict[str, list[str]],
    field_owners: dict[str, list[str]] | None = None,
) -> tuple[FakeFlowRepository, FlowDraft]:
    matrix = progressive_matrix(draft, owners)
    field_matrix = field_override_matrix(draft, field_owners) if field_owners else None
    after = draft.set_step_permissions(matrix, field_matrix)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft, after]
    return fake, after


@pytest.mark.asyncio
async def test_happy_path_reports_pair_counts_and_no_missing() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake, _after = _fake_after_matrix(draft, OWNERS)

    resp = await ForgeSetVisibility(fake).execute(_request())
    payload = resp.model_dump(mode="json")
    assert payload["pair_counts"]["missing"] == 0
    assert payload["missing"] == []
    assert payload["snapshot_version"] == draft.version
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_takes_exactly_one_snapshot_read() -> None:
    """Unlike the old tool (which read the draft once to build the matrix and again
    inside `apply_step_permissions`), this use case computes the matrix from its own
    `WriteOrder` snapshot -- one `get_draft`, not two."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake, _after = _fake_after_matrix(draft, OWNERS)

    await ForgeSetVisibility(fake).execute(_request())
    assert [c[0] for c in fake.calls].count("get_draft") == 2  # snapshot + read-back


@pytest.mark.asyncio
async def test_offline_validation_error_names_the_bad_owner() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [draft]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetVisibility(fake).execute(
            _request(owners={"NonexistentSection": ["Start"]})
        )
    assert exc_info.value.code == VERIFY_FAILED
    assert [c[0] for c in fake.calls].count("put_draft") == 0


@pytest.mark.asyncio
async def test_publish_runs_when_nothing_is_missing() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake, _after = _fake_after_matrix(draft, OWNERS)

    resp = await ForgeSetVisibility(fake).execute(_request(publish=True))
    payload = resp.model_dump(mode="json")
    assert payload["published"] is True
    assert [c[0] for c in fake.calls].count("publish") == 1


@pytest.mark.asyncio
async def test_uncovered_sections_names_a_section_left_out_of_owners() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    owners = {k: v for k, v in OWNERS.items() if k != "Wrap-up"}
    fake, _after = _fake_after_matrix(draft, owners)

    resp = await ForgeSetVisibility(fake).execute(_request(owners=owners))
    payload = resp.model_dump(mode="json")
    assert "Wrap-up" in payload["uncovered_sections"]


@pytest.mark.asyncio
async def test_a_fully_covered_matrix_reports_no_uncovered_section() -> None:
    """`OWNERS` alone leaves the fixture's own "Other" section (holding the one
    deliberately-unowned field, see `tests/synthetic.py`) uncovered on purpose --
    naming it here too is what makes this the no-false-positive control."""
    draft = FlowDraft.from_wire(synthetic_process_draft())
    owners = {**OWNERS, "Other": ["Start"]}
    fake, _after = _fake_after_matrix(draft, owners)

    resp = await ForgeSetVisibility(fake).execute(_request(owners=owners))
    assert resp.model_dump(mode="json")["uncovered_sections"] == []


@pytest.mark.asyncio
async def test_include_pairs_returns_the_pairs_and_collateral_keys() -> None:
    draft = FlowDraft.from_wire(synthetic_process_draft())
    fake, _after = _fake_after_matrix(draft, OWNERS)

    resp = await ForgeSetVisibility(fake).execute(_request(include_pairs=True))
    payload = resp.model_dump(mode="json")
    assert "pairs" in payload and "added" in payload["pairs"]
    assert payload["summarised"] == 0


@pytest.mark.asyncio
async def test_no_app_selected_refuses_before_any_port_call() -> None:
    fake = FakeFlowRepository()
    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetVisibility(fake).execute(_request(app_id=""))
    assert exc_info.value.code == REFUSED
    assert fake.calls == []
