"""app.application.use_cases.intake.forge_plan_app -- compile an APPROVED,
COMPLETE spec to its ordered BuildPlan. THE GATE.

Ported from `app.infrastructure.mcp.server`'s `forge_plan_app` tool body
(Stage D group 8). See `_confirm_gate.py` for why the secret is now a plain
config value rather than a module-level global.
"""

from __future__ import annotations

import hmac

from app.application.exceptions import REFUSED, VERIFY_FAILED, ApplicationError
from app.application.models.requests.intake.forge_plan_app_request import (
    ForgePlanAppRequest,
)
from app.application.models.responses.intake.forge_plan_app_response import (
    ForgePlanAppResponse,
)
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.intake._compile import compile_spec
from app.application.use_cases.intake._confirm_gate import mint_approval_token


class ForgePlanApp:
    """Use case behind the `forge_plan_app` tool. Offline, no ports."""

    def __init__(self, approval_secret: bytes) -> None:
        """Build the use case.

        Args:
            approval_secret: The process's one HMAC secret
                (`AppResources.approval_secret`), the SAME value
                `ForgeApproveSpec` signs with -- this use case only ever
                verifies, never mints.
        """
        self._secret = approval_secret

    async def execute(self, request: ForgePlanAppRequest) -> ForgePlanAppResponse:
        """Run one `forge_plan_app` call.

        Refuses UNLESS `approval_token` is the exact HMAC
        `forge_approve_spec` minted for this spec's CURRENT content digest.
        Only past that check does this refuse a spec whose `approved` flag
        is not True, or one with blocking gaps, naming every dimension
        still missing -- `compile_spec`'s own two refusals, unchanged,
        kept as a second (weaker) check.

        Args:
            request: The validated request.

        Returns:
            The compiled `BuildPlan`: every op, a per-kind count, and the
            total.

        Raises:
            ApplicationError: `request.approval_token` is not the exact
                HMAC minted for this content (`code=REFUSED`); or
                `compile_spec` itself refuses -- not approved, or blocking
                gaps remain (`code=VERIFY_FAILED`, naming them).
        """
        current = content_digest(request.spec)
        expected_token = mint_approval_token(self._secret, current)
        # Compare as BYTES: hmac.compare_digest raises TypeError on a str
        # carrying any non-ASCII character (a smart quote from a paste, a
        # Thai-speaking agent), and this use case's contract is to raise a
        # structured refusal, never let a TypeError escape.
        if not hmac.compare_digest(
            request.approval_token.encode("utf-8"), expected_token.encode("utf-8")
        ):
            raise ApplicationError(
                "invalid or stale approval_token — this exact content was "
                "never approved with forge_approve_spec (or was, then "
                "changed afterward); a plain digest from "
                "forge_request_confirmation/forge_apply_revisions/"
                "forge_update_spec is NOT an approval_token, no matter "
                "how it was obtained — re-run forge_request_confirmation, "
                "get an explicit forge_approve_spec call, and plan with "
                "the approval_token IT returns",
                code=REFUSED,
            )
        try:
            plan = compile_spec(request.spec)
        except ValueError as exc:
            raise ApplicationError(str(exc), code=VERIFY_FAILED) from exc
        return ForgePlanAppResponse(
            ops=list(plan.ops),
            summary=plan.summary(),
            op_count=len(plan.ops),
        )
