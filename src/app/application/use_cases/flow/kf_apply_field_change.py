"""app.application.use_cases.flow.kf_apply_field_change — add fields to a flow,
verified by read-back, optionally published.

Ported from `app.infrastructure.kissflow.client.apply_fields` (Stage D group 1).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.kf_apply_field_change_request import (
    KfApplyFieldChangeRequest,
)
from app.application.models.responses.flow.kf_apply_field_change_response import (
    KfApplyFieldChangeResponse,
)
from app.application.use_cases.flow._fields import (
    changed_ignored,
    field_spec_from,
    raise_if_write_failed,
    require_app_id,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class KfApplyFieldChange:
    """Use case behind the `kf_apply_field_change` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: KfApplyFieldChangeRequest
    ) -> KfApplyFieldChangeResponse:
        """Run one `kf_apply_field_change` call: snapshot, apply offline, guarded
        write (only when something was actually added), read-back verify, optional
        publish.

        Args:
            request: The validated request.

        Returns:
            The output-invariant audit of what happened -- only when every
            requested field verified and nothing was ignored (rule 7: a
            write that did not fully land is a failure, never a success
            response with the failure sitting inside a bucket).

        Raises:
            ApplicationError: `request.app_id` is empty (`REFUSED`); the
                offline change set was rejected (`VERIFY_FAILED`); publish
                was requested for a kind with no publish route
                (`VERIFY_FAILED`); a requested field is `missing` on
                read-back, or a requested change was ignored because the
                name already exists under a different spec (`VERIFY_FAILED`,
                naming the bucket, its items and whether anything
                published). A `RepositoryError` from the port (a read, write
                or conflict failure) propagates unchanged.
        """
        require_app_id(request.app_id)
        specs = [field_spec_from(f) for f in request.changes]

        order = WriteOrder[FlowDraft](
            get=lambda: self._flow.get_draft(
                request.app_id, request.flow_kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id,
                request.flow_kind,
                request.flow_id,
                new,
                expect_version,
            ),
            version_of=lambda draft: draft.version,
        )
        snapshot = await order.snapshot()
        before_names = snapshot.field_names()
        requested = [s.name for s in specs]
        ignored = changed_ignored(snapshot.to_wire(), specs)
        skipped = tuple(
            n for n in requested if n in before_names and n not in ignored.names
        )

        try:
            new = snapshot.apply_changes(specs)
        except (ValueError, NotImplementedError) as exc:
            raise ApplicationError(
                f"offline apply rejected the change set: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        added = tuple(n for n in requested if n not in before_names)
        if added:
            await order.apply(new)

        read_back = await order.read_back()
        live_names = read_back.field_names()
        verified = tuple(
            n for n in requested if n in live_names and n not in ignored.names
        )
        missing = tuple(n for n in requested if n not in live_names)

        published = False
        if request.publish and not (missing or ignored.entries):
            if request.flow_kind not in ("form", "process", "case"):
                raise ApplicationError(
                    f"{request.flow_kind!r} has no publish route. Its draft is "
                    "already live. A publish request returns HTTP 404. Call "
                    "this tool again with publish=False.",
                    code=VERIFY_FAILED,
                )
            await self._flow.publish(request.app_id, request.flow_kind, request.flow_id)
            published = True

        raise_if_write_failed(
            published=published,
            missing=missing,
            changed_ignored=ignored.entries,
            remediation=ignored.remediation,
        )

        return KfApplyFieldChangeResponse(
            flow_id=request.flow_id,
            added=list(added),
            skipped=list(skipped),
            verified=list(verified),
            missing=list(missing),
            changed_ignored=list(ignored.entries),
            collateral=[],
            remediation=list(ignored.remediation),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
