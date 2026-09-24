"""Use case for `forge_create_flow`."""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_create_flow_request import (
    ForgeCreateFlowRequest,
)
from app.application.models.responses.flow.forge_create_flow_response import (
    ForgeCreateFlowResponse,
)
from app.application.use_cases.flow._fields import require_app_id
from app.application.use_cases.flow._lifecycle import create_flow_any, flow_create_note


class ForgeCreateFlow:
    """Unified create for `kind` in process|form|list|dataset|case."""

    def __init__(
        self, flow_repo: FlowRepository, template_path: str | None = None
    ) -> None:
        """Build the use case around its port and its plain config value.

        Args:
            flow_repo: The flow port.
            template_path: `settings.kf_process_template`, used as the
                `kind="process"` default when the caller's own `extra` gives
                none (`brief_stage_d_common.md` review, fix 1) -- `None` for
                the shipped default identity-shell capture.
        """
        self._flow = flow_repo
        self._template_path = template_path

    async def execute(self, request: ForgeCreateFlowRequest) -> ForgeCreateFlowResponse:
        """Create the flow of the requested kind.

        Args:
            request: The resolved arguments.

        Returns:
            The create audit.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`), or
                the create/scaffold step failed, or `kind="case"` is
                missing a required `extra` key.
        """
        require_app_id(request.app_id)
        extra = dict(request.extra or {})
        if request.kind == "process":
            extra.setdefault("template_path", self._template_path)
        result = await create_flow_any(
            self._flow,
            app_id=request.app_id,
            kind=request.kind,
            name=request.name,
            extra=extra,
        )
        note = flow_create_note(
            from_template=result.from_template,
            template_read_error=result.template_read_error,
            sections=len(result.template_sections),
            required=len(result.template_required_fields),
        )
        return ForgeCreateFlowResponse(
            kind=result.kind,
            flow_id=result.flow_id,
            name=result.name,
            status=result.status,
            born_live=result.born_live,
            from_template=result.from_template,
            template_sections=list(result.template_sections),
            template_required_fields=list(result.template_required_fields),
            template_steps=list(result.template_steps),
            template_read_error=result.template_read_error,
            note=note,
            snapshot_version=result.snapshot_version,
        )
