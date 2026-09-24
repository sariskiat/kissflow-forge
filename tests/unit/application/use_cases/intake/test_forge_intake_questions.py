"""Tests for `ForgeIntakeQuestions`, ported from `tests/test_p3_surface.py`'s
`forge_intake_questions` coverage (Stage D group 8; the tool moved from
`app.infrastructure.mcp.server.forge_intake_questions`).
"""

from __future__ import annotations

import pytest
from tests.fakes.intake_specs import linear_spec

from app.application.models.requests.intake.forge_intake_questions_request import (
    ForgeIntakeQuestionsRequest,
)
from app.application.use_cases.intake.forge_intake_questions import (
    ForgeIntakeQuestions,
)


@pytest.mark.asyncio
async def test_accepts_no_spec_at_all() -> None:
    """The one P3 tool where `spec=None` is the documented, legal opening
    move. Pins the FULL dimension sequence (not just that the first question
    is dimension 1)."""
    use_case = ForgeIntakeQuestions()
    got = await use_case.execute(ForgeIntakeQuestionsRequest())
    assert len(got.gaps) == 11
    assert [q.id for q in got.questions] == ["1a", "1b", "2a", "3a"]
    assert [q.dimension for q in got.questions] == [1, 1, 2, 3]
    assert [q.dimension_name for q in got.questions] == [
        "problem/goal",
        "problem/goal",
        "roles",
        "stages",
    ]
    assert got.spec["approved"] is False


@pytest.mark.asyncio
async def test_reports_gaps_for_a_given_spec() -> None:
    linear_wire = linear_spec().model_dump(mode="json")
    use_case = ForgeIntakeQuestions()
    got = await use_case.execute(
        ForgeIntakeQuestionsRequest(spec=linear_wire, limit=10)
    )
    assert [q.id for q in got.questions] == ["9a"]  # only the advisory dim is a gap
    assert got.questions[0].dimension == 9
    assert got.questions[0].dimension_name == "timing"
    expected_gap = (
        "9. timing: need at least the SLA notes (ADVISORY: an empty Timing "
        "does not block compile_spec — see AppSpec.blocking_gaps and "
        "ADVISORY_DIMENSIONS)"
    )
    assert got.gaps == [expected_gap]
    assert got.blocking_gaps == []


@pytest.mark.asyncio
async def test_never_echoes_approved_true() -> None:
    """LOW finding: this tool used to echo `approved: true` verbatim when
    the CALLER passed an already-approved spec."""
    approved_wire = linear_spec(approved=True).model_dump(mode="json")
    use_case = ForgeIntakeQuestions()
    got = await use_case.execute(ForgeIntakeQuestionsRequest(spec=approved_wire))
    assert got.spec["approved"] is False
