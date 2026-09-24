"""Tests for `KfPlanStepVisibility`, ported from `tests/test_tools.py`'s
`plan_step_visibility` coverage (Stage D group 8; the tool moved from
`app.application.tools.plan_step_visibility`).
"""

from __future__ import annotations

import copy

import pytest
from synthetic import OWNERS, synthetic_process_draft

from app.application.exceptions import ApplicationError
from app.application.models.requests.intake.kf_plan_step_visibility_request import (
    KfPlanStepVisibilityRequest,
)
from app.application.use_cases.intake.kf_plan_step_visibility import (
    KfPlanStepVisibility,
)
from app.domain.entities.flow_draft import FlowDraft, progressive_matrix


def _written(d: dict) -> int:
    """The REAL Permission-node count `set_step_permissions` would write."""
    flow = FlowDraft.from_wire(d)
    applied = flow.set_step_permissions(progressive_matrix(flow, OWNERS)).to_wire()
    return sum(
        1
        for v in applied.values()
        if isinstance(v, dict) and v.get("Kind") == "Permission"
    )


@pytest.mark.asyncio
async def test_plan_step_visibility_matches_the_writer_on_a_plain_draft() -> None:
    """The preview must report exactly the pair count the writer would emit
    -- a preview that counts permission nodes the writer will skip (or
    misses ones it will write) lies to the human being asked to sign off
    before a DESTRUCTIVE matrix rebuild."""
    use_case = KfPlanStepVisibility()
    base = synthetic_process_draft()
    out = await use_case.execute(KfPlanStepVisibilityRequest(draft=base, owners=OWNERS))
    assert out.root["permission_nodes"] == _written(base)


@pytest.mark.asyncio
async def test_a_sequence_number_column_takes_no_permission() -> None:
    """A SequenceNumber column inside a section takes no Permission (#9) --
    the preview must not count the pairs the writer skips."""
    use_case = KfPlanStepVisibility()
    base = synthetic_process_draft()
    seq = (
        FlowDraft.from_wire(copy.deepcopy(base))
        .add_sequence_number("Running No", "Intake", "TCK-", "0001", "Ticket arrives")
        .to_wire()
    )
    out = await use_case.execute(KfPlanStepVisibilityRequest(draft=seq, owners=OWNERS))
    assert out.root["permission_nodes"] == _written(seq)


@pytest.mark.asyncio
async def test_a_hidden_column_is_skipped_the_same_way() -> None:
    use_case = KfPlanStepVisibility()
    base = synthetic_process_draft()
    hidden = copy.deepcopy(base)
    f = next(
        v
        for v in hidden.values()
        if isinstance(v, dict) and v.get("Name") == "Extra Note"
    )
    hidden[f["Column"]]["IsHidden"] = True
    out = await use_case.execute(
        KfPlanStepVisibilityRequest(draft=hidden, owners=OWNERS)
    )
    assert out.root["permission_nodes"] == _written(hidden)


@pytest.mark.asyncio
async def test_an_unknown_section_or_step_name_is_refused() -> None:
    use_case = KfPlanStepVisibility()
    base = synthetic_process_draft()
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            KfPlanStepVisibilityRequest(
                draft=base, owners={"No Such Section": ["No Such Step"]}
            )
        )
    assert exc_info.value.code == "VERIFY_FAILED"
