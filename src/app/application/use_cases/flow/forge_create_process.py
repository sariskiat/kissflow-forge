"""Use case for `forge_create_process`."""

from __future__ import annotations

from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_create_process_request import (
    ForgeCreateProcessRequest,
)
from app.application.models.responses.flow.forge_create_process_response import (
    ForgeCreateProcessResponse,
)
from app.application.use_cases.flow._fields import require_app_id
from app.application.use_cases.flow._lifecycle import (
    create_process,
    process_create_note,
)


class ForgeCreateProcess:
    """Create a new PROCESS shell -- a scaffolded, publishable draft."""

    def __init__(
        self,
        flow_repo: FlowRepository,
        template_path: str | None,
        app_repo: AppRepository | None = None,
    ) -> None:
        """Build the use case around its ports and its plain config value.

        Args:
            flow_repo: The flow port.
            template_path: `settings.kf_process_template`. When set, that
                identity-shell capture is cloned (the operator's choice wins);
                `None` builds the full template.
            app_repo: The app port. With it, `from_template=True` builds the
                FULL template (shapes/process_template_full.json) and resolves
                its approver AppRole; without it, the identity shell.
        """
        self._flow = flow_repo
        self._template_path = template_path
        self._app = app_repo

    @staticmethod
    async def _template_role(
        app: AppRepository, app_id: str, name: str
    ) -> tuple[str, str]:
        """Reuse the app's AppRole named `<name> Role`, else create it."""
        role_name = f"{name} Role"
        for role in await app.list_app_roles(app_id):
            if (
                isinstance(role, dict)
                and role.get("Name") == role_name
                and role.get("_id")
            ):
                return str(role["_id"]), role_name
        return await app.create_app_role(role_name, app_id), role_name

    async def execute(
        self, request: ForgeCreateProcessRequest
    ) -> ForgeCreateProcessResponse:
        """Create the process shell and scaffold it.

        Args:
            request: The resolved arguments.

        Returns:
            The full create-process audit.

        Raises:
            ApplicationError: No app is resolvable (`code="REFUSED"`), or
                the create/scaffold step failed.
        """
        require_app_id(request.app_id)
        template_role = (
            await self._template_role(self._app, request.app_id, request.name)
            # An operator's own KF_PROCESS_TEMPLATE shell wins over the full template.
            if request.from_template
            and self._app is not None
            and not self._template_path
            else None
        )
        result = await create_process(
            self._flow,
            app_id=request.app_id,
            name=request.name,
            steps=("Draft",),
            specs=[],
            publish=request.publish,
            from_template=request.from_template,
            template_path=self._template_path,
            template_role=template_role,
        )
        note = process_create_note(
            from_template=result.from_template,
            template_read_error=result.template_read_error,
            sections=len(result.template_sections),
            required=len(result.template_required_fields),
        )
        if template_role is not None:
            note = (
                f"built from the full process template; approver AppRole "
                f"{template_role[1]!r} ({template_role[0]}) is a member of the flow "
                f"and assigned to every approval step. Add users to that role "
                f"(forge_add_role_users) before anyone can submit an item."
                + (f" {note}" if note else "")
            )
        return ForgeCreateProcessResponse(
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
