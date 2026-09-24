"""Use case for `forge_doctor`."""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_doctor_request import (
    ForgeDoctorRequest,
)
from app.application.models.responses.flow.forge_doctor_response import (
    ForgeDoctorResponse,
)
from app.application.use_cases.flow._doctor import run_doctor
from app.application.use_cases.flow._fields import require_app_id


class ForgeDoctor:
    """Read-only health check: fetch the live draft, harvest real list options, and
    run the domain's rule set for real."""

    def __init__(self, flow_repo: FlowRepository) -> None:
        """Build the use case around its port.

        Args:
            flow_repo: The flow port.
        """
        self._flow = flow_repo

    async def execute(self, request: ForgeDoctorRequest) -> ForgeDoctorResponse:
        """Run the audit.

        Args:
            request: The resolved arguments.

        Returns:
            The full doctor audit.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`), or
                the draft has no valid `Root` key (`code="VERIFY_FAILED"`).
        """
        require_app_id(request.app_id)
        result = await run_doctor(
            self._flow,
            app_id=request.app_id,
            flow_id=request.flow_id,
            kind=request.kind,
            visibility_role_claims=request.visibility_role_claims,
        )
        return ForgeDoctorResponse(
            flow_id=result.flow_id,
            ok=result.ok,
            problems=list(result.problems),
            checked=result.checked,
            unvalidated=list(result.unvalidated),
            unvalidatable_scripts=result.unvalidatable_scripts,
            list_ids_checked=list(result.list_ids_checked),
            list_fetch_errors=result.list_fetch_errors,
            members_found=result.members_found,
            member_fetch_error=result.member_fetch_error,
        )
