"""app.application.use_cases.intake.forge_approve_spec -- record approval and
mint the ONLY value `forge_plan_app` accepts.

Ported from `app.infrastructure.mcp.server`'s `forge_approve_spec` tool body
(Stage D group 8). See `_confirm_gate.py` for why the secret is now a plain
config value rather than a module-level global.
"""

from __future__ import annotations

from app.application.exceptions import REFUSED, ApplicationError
from app.application.models.requests.intake.forge_approve_spec_request import (
    ForgeApproveSpecRequest,
)
from app.application.models.responses.intake.forge_approve_spec_response import (
    ForgeApproveSpecResponse,
)
from app.application.use_cases.design._artifacts import content_digest
from app.application.use_cases.design._confirm import is_approved
from app.application.use_cases.intake._confirm_gate import mint_approval_token


class ForgeApproveSpec:
    """Use case behind the `forge_approve_spec` tool. Offline, no ports."""

    def __init__(self, approval_secret: bytes) -> None:
        """Build the use case.

        Args:
            approval_secret: The process's one HMAC secret
                (`AppResources.approval_secret`), minted once by
                `app_lifespan`. Only this use case ever signs with it.
        """
        self._secret = approval_secret

    async def execute(
        self, request: ForgeApproveSpecRequest
    ) -> ForgeApproveSpecResponse:
        """Run one `forge_approve_spec` call.

        HONEST CEILING: this proves "exactly one explicit
        forge_approve_spec call happened, bound to this exact content, and
        no other route can forge that fact." It does NOT and CANNOT prove
        a HUMAN, rather than the calling agent, made the decision.

        Args:
            request: The validated request.

        Returns:
            The spec with `approved` set True, its plain content digest,
            and the approval_token.

        Raises:
            ApplicationError: `request.digest` does not match the spec's
                CURRENT content digest (`code=REFUSED`), naming both
                digests; or `request.decision` is not an explicit approval
                (`code=REFUSED`).
        """
        current = content_digest(request.spec)
        if request.digest != current:
            raise ApplicationError(
                f"stale digest: given {request.digest!r}, current spec "
                f"digest is {current!r} — the spec changed since this "
                f"digest was shown to the customer; re-run "
                f"forge_request_confirmation and show the NEW digest "
                f"before approving",
                code=REFUSED,
            )
        if not is_approved(request.spec, request.decision):
            raise ApplicationError(
                f"decision {request.decision!r} is not an explicit "
                f"approval — must be exactly 'approve'",
                code=REFUSED,
            )
        approved_spec = request.spec.model_copy(update={"approved": True})
        return ForgeApproveSpecResponse(
            spec=approved_spec.model_dump(mode="json"),
            approved=True,
            digest=current,
            approval_token=mint_approval_token(self._secret, current),
        )
