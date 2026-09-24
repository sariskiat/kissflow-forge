"""Use case for `kf_create_process`."""

from __future__ import annotations

from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.kf_create_process_request import (
    KfCreateProcessRequest,
)
from app.application.models.responses.flow.kf_create_process_response import (
    KfCreateProcessResponse,
)
from app.application.use_cases.flow._fields import field_spec_from, require_app_id
from app.application.use_cases.flow._lifecycle import (
    create_process,
    process_create_note,
)


class KfCreateProcess:
    """Create a NEW process from zero: workflow steps + fields, verified."""

    def __init__(self, flow_repo: FlowRepository, template_path: str | None) -> None:
        """Build the use case around its port and its plain config value.

        Args:
            flow_repo: The flow port.
            template_path: `settings.kf_process_template`, or `None` for
                the shipped default identity-shell capture.
        """
        self._flow = flow_repo
        self._template_path = template_path

    async def execute(self, request: KfCreateProcessRequest) -> KfCreateProcessResponse:
        """Create the process, scaffold it, apply the requested fields.

        Args:
            request: The resolved arguments.

        Returns:
            The full create-process audit.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`), or
                the create/scaffold/field-apply step failed.
        """
        require_app_id(request.app_id)
        specs = [field_spec_from(f) for f in request.fields]
        result = await create_process(
            self._flow,
            app_id=request.app_id,
            name=request.name,
            steps=tuple(request.steps),
            specs=specs,
            publish=request.publish,
            from_template=request.from_template,
            template_path=self._template_path,
        )
        note = process_create_note(
            from_template=result.from_template,
            template_read_error=result.template_read_error,
            sections=len(result.template_sections),
            required=len(result.template_required_fields),
        )
        return KfCreateProcessResponse(
            flow_id=result.flow_id,
            added=list(result.added),
            skipped=list(result.skipped),
            verified=list(result.verified),
            missing=list(result.missing),
            changed_ignored=list(result.changed_ignored),
            collateral=[],
            remediation=list(result.remediation),
            meta_version=result.meta_version,
            published=result.published,
            from_template=result.from_template,
            template_sections=list(result.template_sections),
            template_required_fields=list(result.template_required_fields),
            template_steps=list(result.template_steps),
            template_read_error=result.template_read_error,
            note=note,
            snapshot_version=result.snapshot_version,
        )
