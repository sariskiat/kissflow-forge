"""app.application.use_cases.intake.forge_intake_questions -- the next
questions to ask a business owner, for a spec's current gaps.

Ported from `app.infrastructure.mcp.server`'s `forge_intake_questions` tool
body (Stage D group 8).
"""

from __future__ import annotations

from app.application.models.requests.intake.app_spec import DIMENSION_NAMES
from app.application.models.requests.intake.forge_intake_questions_request import (
    ForgeIntakeQuestionsRequest,
)
from app.application.models.responses.intake.forge_intake_questions_response import (
    ForgeIntakeQuestionsResponse,
    IntakeQuestion,
)
from app.application.use_cases.intake._decode import spec_or_blank
from app.application.use_cases.intake._questions import QUESTIONS, next_questions

#: Question id -> dimension number (1..11), derived from `QUESTIONS` (a public
#: dict already keyed by dimension) rather than adding a new accessor to
#: `_questions.py` -- `next_questions()` itself returns a flat tuple of
#: `Question` with no dimension attached, so this is the one piece this tool
#: needs that nothing in the module exposes directly.
_QUESTION_DIMENSION: dict[str, int] = {
    q.id: dim for dim, qs in QUESTIONS.items() for q in qs
}


class ForgeIntakeQuestions:
    """Use case behind the `forge_intake_questions` tool. Offline, no ports."""

    async def execute(
        self, request: ForgeIntakeQuestionsRequest
    ) -> ForgeIntakeQuestionsResponse:
        """Run one `forge_intake_questions` call.

        Args:
            request: The validated request.

        Returns:
            The next questions (most-blocking dimension first), the spec's
            gap lists, and the spec echoed back with `approved` forced
            False.
        """
        decoded = spec_or_blank(request.spec)
        questions = next_questions(decoded, limit=request.limit)
        echoed = decoded.model_copy(update={"approved": False})
        return ForgeIntakeQuestionsResponse(
            questions=[
                IntakeQuestion(
                    id=q.id,
                    dimension=_QUESTION_DIMENSION[q.id],
                    dimension_name=DIMENSION_NAMES[_QUESTION_DIMENSION[q.id] - 1],
                    text_th=q.text_th,
                    why=q.why,
                    example=q.example,
                    follow_ups=list(q.follow_ups),
                )
                for q in questions
            ],
            gaps=list(decoded.gaps()),
            blocking_gaps=list(decoded.blocking_gaps()),
            spec=echoed.model_dump(mode="json"),
        )
