"""app.application.use_cases.flow.forge_rename_fields — rename form fields,
`{current name: new name}`.

Ported from `app.infrastructure.kissflow.client.rename_form_fields` (Stage D group 1).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_rename_fields_request import (
    ForgeRenameFieldsRequest,
)
from app.application.models.responses.flow.forge_rename_fields_response import (
    ForgeRenameFieldsResponse,
)
from app.application.use_cases.flow._fields import (
    live_names,
    raise_if_write_failed,
    require_app_id,
)
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeRenameFields:
    """Use case behind the `forge_rename_fields` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeRenameFieldsRequest
    ) -> ForgeRenameFieldsResponse:
        """Run one `forge_rename_fields` call: snapshot, refuse a name collision,
        rename offline, guarded write, read-back verify both halves of every
        rename, optional publish.

        Args:
            request: The validated request.

        Returns:
            The output-invariant audit of what happened -- only when every
            rename verified clean (rule 7: a write that did not fully land
            is a failure, never a success response with the failure sitting
            inside a bucket).

        Raises:
            ApplicationError: `request.app_id` is empty (`REFUSED`); a new
                name collides with one already on the form, or the offline
                rename was rejected (`VERIFY_FAILED`); a rename is `missing`
                or `stale` on read-back (`VERIFY_FAILED`, naming the
                bucket, its items and whether anything published). A
                `RepositoryError` from the port (a read, write or conflict
                failure) propagates unchanged.
        """
        require_app_id(request.app_id)

        order = WriteOrder[FlowDraft](
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, expect_version
            ),
            version_of=lambda draft: draft.version,
        )
        snapshot = await order.snapshot()
        live_before, _tables_before = live_names(snapshot.to_wire())

        clashes = sorted(
            {
                new_name
                for old, new_name in request.renames.items()
                if new_name in live_before and new_name != old
            }
        )
        if clashes:
            raise ApplicationError(
                "refusing to rename onto name(s) already on this form: "
                f"{clashes} — two fields sharing a name make every "
                "name-keyed op resolve to an arbitrary one of them",
                code=VERIFY_FAILED,
            )

        try:
            new = snapshot.rename_fields(request.renames)
        except ValueError as exc:
            raise ApplicationError(
                f"offline rename_fields rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        await order.apply(new)
        read_back = await order.read_back()
        live_after, _tables_after = live_names(read_back.to_wire())

        unchanged = tuple(
            f"{old} -> {n}"
            for old, n in request.renames.items()
            if old == n and n in live_after
        )
        real = {old: n for old, n in request.renames.items() if old != n}
        verified = tuple(
            f"{old} -> {n}"
            for old, n in real.items()
            if n in live_after and old not in live_after
        )
        missing = tuple(
            f"{old} -> {n}" for old, n in request.renames.items() if n not in live_after
        )
        stale = tuple(
            f"{old} -> {n}"
            for old, n in real.items()
            if n in live_after and old in live_after
        )

        published = False
        if request.publish and not (missing or stale):
            await self._flow.publish(request.app_id, request.kind, request.flow_id)
            published = True

        raise_if_write_failed(published=published, missing=missing, stale=stale)

        wanted = tuple(f"{old} -> {n}" for old, n in request.renames.items())
        return ForgeRenameFieldsResponse(
            flow_id=request.flow_id,
            renames=list(wanted),
            verified=list(verified),
            missing=list(missing),
            stale=list(stale),
            unchanged=list(unchanged),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
