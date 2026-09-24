"""Tests for `ForgeCompareToSpec`. Ported behavior: `app.application.tools`
had no direct old-server unit test naming this tool by its dict shape (see
`tests/test_mcp_boundary.py`'s dummy-args key-pair sweep for the old
tool's own boundary coverage) -- the fidelity LOGIC itself is already
fully ported in `test__compare.py`; this file is new coverage of the
use case's own orchestration: app-id resolution, reading the draft
through the port, and wrapping `CompareReport` (Stage D group 8).
"""

from __future__ import annotations

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.intake_specs import built_fields, full_spec, fully_valid_draft

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.intake.forge_compare_to_spec_request import (
    ForgeCompareToSpecRequest,
)
from app.application.use_cases.intake.forge_compare_to_spec import (
    ForgeCompareToSpec,
)
from app.domain.entities.flow_draft import FlowDraft


@pytest.mark.asyncio
async def test_a_bare_field_only_draft_still_flags_every_other_mismatch() -> None:
    """Named for what it checks (brief_stage_d_common fix 6): `got.ok is False`,
    not "passes all checks" -- a bare field-only draft still finds every OTHER
    mismatch (layout, workflow, events, ...). This proves the wiring, not that
    the draft is complete; `test_a_fully_valid_draft_gets_ok_true_through_the_
    port` below is the "actually passes" case."""
    spec = full_spec()
    draft = built_fields(spec)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(draft)]
    use_case = ForgeCompareToSpec(fake)

    got = await use_case.execute(
        ForgeCompareToSpecRequest(flow_id="F1", spec=spec, app_id="A1")
    )

    assert fake.calls == [("get_draft", ("A1", "process", "F1"), {})]
    assert got.ok is False
    assert isinstance(got.mismatches, list) and got.mismatches
    assert isinstance(got.checked, dict)
    assert isinstance(got.ignored, list)


@pytest.mark.asyncio
async def test_a_fully_valid_draft_gets_ok_true_through_the_port() -> None:
    """The other half of the above: a draft with every dimension actually
    built right reads back as `ok: True` through the real port, not just
    through `compare_built_to_spec` in isolation (`test__compare.py`'s own
    `test_fully_valid_built_draft_passes_all_checks`)."""
    spec = full_spec()
    draft = fully_valid_draft(spec)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(draft)]
    use_case = ForgeCompareToSpec(fake)

    got = await use_case.execute(
        ForgeCompareToSpecRequest(flow_id="F1", spec=spec, app_id="A1")
    )

    assert got.ok is True
    assert got.mismatches == []


@pytest.mark.asyncio
async def test_wrong_field_type_is_flagged() -> None:
    """One end-to-end slice of the fidelity comparator's own coverage,
    wired through the real port -- the full rule matrix is
    `test__compare.py`'s job."""
    spec = full_spec()
    draft = built_fields(spec)
    urgency = next(
        v for v in draft.values() if isinstance(v, dict) and v.get("Name") == "Urgency"
    )
    urgency["Type"] = "Text"
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [FlowDraft.from_wire(draft)]
    use_case = ForgeCompareToSpec(fake)

    got = await use_case.execute(
        ForgeCompareToSpecRequest(flow_id="F1", spec=spec, app_id="A1")
    )

    assert got.ok is False
    assert any("built as 'Text', input asked 'Select'" in m for m in got.mismatches)


@pytest.mark.asyncio
async def test_an_empty_app_id_is_refused_before_any_read() -> None:
    spec = full_spec()
    fake = FakeFlowRepository()
    use_case = ForgeCompareToSpec(fake)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeCompareToSpecRequest(flow_id="F1", spec=spec, app_id="")
        )
    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_a_repository_error_on_read_propagates_unchanged() -> None:
    class _FailingFlow(FakeFlowRepository):
        async def get_draft(self, app_id, kind, flow_id):  # type: ignore[override]
            raise RepositoryError("500 Internal Server Error")

    spec = full_spec()
    use_case = ForgeCompareToSpec(_FailingFlow())
    with pytest.raises(RepositoryError):
        await use_case.execute(
            ForgeCompareToSpecRequest(flow_id="F1", spec=spec, app_id="A1")
        )
