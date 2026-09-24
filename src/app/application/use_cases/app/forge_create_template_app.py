"""app.application.use_cases.app.forge_create_template_app — ONE call, create a
fresh Template App carrying the transplanted source template process (ADR-0006,
spec #10), published end to end.

Ported from `app.infrastructure.kissflow.client.create_template_app` (Stage D
group 6, app family). Composed of existing port primitives plus the pure
`FlowDraft.transplant_template` op, in the proven build order (CLAUDE.md > Build
order): create application -> create a BARE process flow -> members FIRST ->
write the transplanted graph (assignees ride in that write) -> publish the
process with a status read-back -> app-level publish with its own read-back ->
doctor. A failed run after the application exists archives+deletes the
half-built app (and its created AppRole) rather than leaving junk in the
tenant.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.app.forge_create_template_app_request import (
    ForgeCreateTemplateAppRequest,
)
from app.application.models.responses.app.forge_create_template_app_response import (
    ForgeCreateTemplateAppResponse,
)
from app.application.use_cases.app._apps import (
    create_application_verified,
    publish_application_verified,
)
from app.application.use_cases.app._members import (
    apply_own_app_roles,
    member_outcome_as_dict,
)
from app.application.use_cases.app._template import (
    abandon,
    doctor_report,
    run_step,
)
from app.domain.value_objects.kinds import FlowKind

_PROCESS: FlowKind = "process"


class ForgeCreateTemplateApp:
    """Use case behind the `forge_create_template_app` tool."""

    def __init__(self, app: AppRepository, flow: FlowRepository, base_url: str) -> None:
        """Build the use case.

        Args:
            app: The application/app-role port.
            flow: The flow/process/form/case/list port.
            base_url: The dev-tenant base URL (`Settings.base_url`) the
                builder URLs in the response are derived from -- a plain
                config value, never the whole `Settings`.
        """
        self._app = app
        self._flow = flow
        self._base_url = base_url

    async def execute(
        self, request: ForgeCreateTemplateAppRequest
    ) -> ForgeCreateTemplateAppResponse:
        """Build a fresh Template App end to end, in the proven build order.

        Account-level: needs no app selected, the same reasoning as
        `forge_create_app`. Runs as the CALLING identity -- every step after
        the first is scoped onto the application it just created via an
        explicit `app_id`, never an ambient one.

        Args:
            request: The validated request.

        Returns:
            The full audit: the created application/role/process ids, the
            member-grant report, the process and app publish read-backs, the
            doctor read-back, and the (unverified) builder URLs.

        Raises:
            ApplicationError: Any step from `create_app_role` onward failed
                (`code=VERIFY_FAILED` for an offline/read-back verification
                failure, or the port's own `code` for a propagated
                `RepositoryError`) -- the message names the half-built
                application's own cleanup outcome. A failure in
                `create_application_verified` itself propagates unchanged,
                with no cleanup attempted (nothing was created yet).
        """
        name = request.name
        app_id = await create_application_verified(self._app, name)

        role_name = f"{name} Role"
        role_id = await run_step(
            self._app, app_id, None, self._app.create_app_role(role_name, app_id)
        )

        # The write-order invariant's own leading read on the FLOW port: this
        # application, and this flow, are both brand new, so there is no
        # natural pre-read of the flow itself -- this call's own result is
        # unused.
        await run_step(
            self._app, app_id, role_id, self._flow.list_flows(app_id, _PROCESS)
        )
        # Bare flow, NOT a template-shell create: the transplant needs a bare
        # draft (no RootProcessDef yet).
        flow_id = await run_step(
            self._app,
            app_id,
            role_id,
            self._flow.create_flow(app_id, _PROCESS, name),
        )

        # Members FIRST (CLAUDE.md > Members first): assignees ride in the
        # graph write below. A fresh app has no sibling flow to harvest from,
        # so this grants the app's own AppRoles -- exactly the role just
        # created.
        members = await run_step(
            self._app,
            app_id,
            role_id,
            apply_own_app_roles(self._flow, self._app, app_id, flow_id, _PROCESS),
        )
        if members.missing or role_id not in members.role_ids:
            raise await abandon(
                self._app,
                app_id,
                role_id,
                f"member grant did not land the created AppRole {role_id!r}: "
                f"missing={list(members.missing)!r} "
                f"role_ids={list(members.role_ids)!r}",
                VERIFY_FAILED,
            )

        pre_draft = await run_step(
            self._app, app_id, role_id, self._flow.get_draft(app_id, _PROCESS, flow_id)
        )
        try:
            grafted = pre_draft.transplant_template(app_role=(role_id, role_name))
        except ValueError as exc:
            raise await abandon(
                self._app, app_id, role_id, str(exc), VERIFY_FAILED
            ) from exc

        await run_step(
            self._app,
            app_id,
            role_id,
            self._flow.put_draft(
                app_id, _PROCESS, flow_id, grafted, expect_version=pre_draft.version
            ),
        )
        # A PUT that 200s proves nothing about what actually persisted (THE
        # RULE) -- read the draft back and confirm every transplanted node is
        # really there before trusting the write. Old (`client.py:5597`): any
        # failure reading this back was reclassified `Err("verify", ...)`,
        # never left as the port's own bare failure code.
        try:
            read_back = await self._flow.get_draft(app_id, _PROCESS, flow_id)
        except ApplicationError as exc:
            raise await abandon(
                self._app,
                app_id,
                role_id,
                f"graph write read-back failed: {exc.message}",
                VERIFY_FAILED,
            ) from exc
        grafted_wire = grafted.to_wire()
        read_back_wire = read_back.to_wire()
        graft_node_ids = [
            nid for nid in grafted_wire if nid not in ("Root", "_meta_version")
        ]
        missing_nodes = [nid for nid in graft_node_ids if nid not in read_back_wire]
        if missing_nodes:
            raise await abandon(
                self._app,
                app_id,
                role_id,
                f"graph write did not land: {len(missing_nodes)} of "
                f"{len(graft_node_ids)} nodes missing from the live draft "
                f"read-back (first few: {missing_nodes[:5]!r})",
                VERIFY_FAILED,
            )

        # Publish the process WITH a status read-back -- THE RULE, not a bare
        # 200.
        await run_step(
            self._app, app_id, role_id, self._flow.publish(app_id, _PROCESS, flow_id)
        )
        # Old (`client.py:5619`): any failure reading this back was likewise
        # reclassified `Err("verify", ...)`.
        try:
            detail = await self._flow.get_flow_detail(app_id, _PROCESS, flow_id)
        except ApplicationError as exc:
            raise await abandon(
                self._app,
                app_id,
                role_id,
                f"publish succeeded but status read-back failed: {exc.message}",
                VERIFY_FAILED,
            ) from exc
        status = detail.get("Status")
        if status != "Live":
            raise await abandon(
                self._app,
                app_id,
                role_id,
                f"process publish read-back status {status!r}, not Live",
                VERIFY_FAILED,
            )

        # Old (`client.py:5633`): `create_template_app` re-wrapped
        # `publish_application_verified`'s OWN read-back failure a second
        # time, with its own "app publish read-back failed: " prefix -- a
        # genuine failure of the publish call itself (never a read-back at
        # all) propagates unprefixed, exactly as the old `Err` did.
        try:
            (
                runtime_id,
                meta_version,
                pub_note,
                _app_snapshot_version,
            ) = await publish_application_verified(self._app, app_id)
        except ApplicationError as exc:
            message = exc.message
            if exc.code == VERIFY_FAILED:
                message = f"app publish read-back failed: {message}"
            raise await abandon(self._app, app_id, role_id, message, exc.code) from exc

        # Doctor read-back rides in the response -- never a separate call the
        # caller must remember. Its own findings do NOT fail this use case:
        # the vendored capture ships known problems (the differential bar) on
        # purpose, reported as data for the caller/test to judge.
        doctor = await run_step(
            self._app, app_id, role_id, doctor_report(self._flow, app_id, flow_id)
        )

        return ForgeCreateTemplateAppResponse(
            app_id=app_id,
            name=name,
            flow_id=flow_id,
            role_id=role_id,
            role_name=role_name,
            members=member_outcome_as_dict(members),
            process_status=status,
            app_publish={
                "app_id": app_id,
                "published": True,
                "runtime_id": runtime_id,
                "meta_version": meta_version,
                "note": pub_note,
            },
            doctor=doctor,
            app_url=f"{self._base_url}/view/app/{app_id}",
            process_url=f"{self._base_url}/view/process/{flow_id}",
            url_verified=False,
            graph_nodes_verified=len(graft_node_ids),
            snapshot_version=pre_draft.version,
        )
