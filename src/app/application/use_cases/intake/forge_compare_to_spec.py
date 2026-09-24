"""app.application.use_cases.intake.forge_compare_to_spec -- does the BUILT
flow match what the INPUT asked for? (#16 -- fidelity, not referential
integrity: `forge_doctor` can say `ok` on a build with wrong field types, a
missing event, spurious Permissions and a misordered table host.)

Ported from `app.infrastructure.mcp.server`'s `forge_compare_to_spec` tool
body (Stage D group 8).
"""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.intake.forge_compare_to_spec_request import (
    ForgeCompareToSpecRequest,
)
from app.application.models.responses.intake.forge_compare_to_spec_response import (
    ForgeCompareToSpecResponse,
)
from app.application.use_cases.intake._app_id import require_app_id
from app.application.use_cases.intake._compare import compare_built_to_spec


class ForgeCompareToSpec:
    """Use case behind the `forge_compare_to_spec` tool. LIVE read-only."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeCompareToSpecRequest
    ) -> ForgeCompareToSpecResponse:
        """Fetch the live draft (THE RULE: judge the read-back, never the
        plan) and diff it against the spec.

        A VERDICT tool: the call itself either works or raises: a fidelity
        mismatch is reported as `ok=False` in a successful response, never
        an `ApplicationError` (`brief_stage_d_common.md` rule 7's own
        exception for `forge_doctor`/`forge_copilot_check`/`forge_sweep`/
        this tool).

        Args:
            request: The validated request.

        Returns:
            The fidelity verdict: every mismatch, a per-rule checked
            count, and declared known-benign exclusions.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`).
            RepositoryError: The draft read failed. Propagates unchanged.
        """
        require_app_id(request.app_id)
        draft = await self._flow.get_draft(
            request.app_id, request.kind, request.flow_id
        )
        report = compare_built_to_spec(draft.to_wire(), request.spec)
        return ForgeCompareToSpecResponse(
            ok=report.ok(),
            mismatches=list(report.mismatches),
            checked=report.checked,
            ignored=list(report.ignored),
        )
