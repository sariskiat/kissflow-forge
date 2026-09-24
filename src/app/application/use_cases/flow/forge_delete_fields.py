"""app.application.use_cases.flow.forge_delete_fields — delete form fields and/or
child tables by name, with the whole cluster swept.

Ported from `app.infrastructure.kissflow.client.delete_fields` (Stage D group 1).
"""

from __future__ import annotations

from collections import Counter

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_delete_fields_request import (
    ForgeDeleteFieldsRequest,
)
from app.application.models.responses.flow.forge_delete_fields_response import (
    ForgeDeleteFieldsResponse,
)
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeDeleteFields:
    """Use case behind the `forge_delete_fields` tool."""

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case.

        Args:
            flow: The flow/process/form/case/list port.
        """
        self._flow = flow

    async def execute(
        self, request: ForgeDeleteFieldsRequest
    ) -> ForgeDeleteFieldsResponse:
        """Run one `forge_delete_fields` call: snapshot, refuse a dangling
        reference, delete offline, guarded write, read-back verify every
        requested name is ABSENT, optional publish.

        Args:
            request: The validated request.

        Returns:
            The output-invariant audit of what happened. INVERTED unit:
            `deleted` (not `verified`) is the success bucket -- returned
            only when nothing survived (rule 7: a write that did not fully
            land is a failure, never a success response with the failure
            sitting inside a bucket).

        Raises:
            ApplicationError: `request.app_id` is empty (`REFUSED`); a
                surviving node would be left with a dangling reference, or
                the offline delete was rejected (`VERIFY_FAILED`); a
                requested name is `surviving` on read-back (`VERIFY_FAILED`,
                naming the bucket, its items and whether anything
                published). A `RepositoryError` from the port (a read,
                write or conflict failure) propagates unchanged.
        """
        require_app_id(request.app_id)
        fields = tuple(request.fields or ())
        tables = tuple(request.tables or ())

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
        before_draft = snapshot.to_wire()

        try:
            blockers = snapshot.field_delete_blockers(fields, tables)
            if blockers:
                raise ApplicationError(
                    "refusing to delete — these references would be left "
                    "dangling: " + "; ".join(blockers),
                    code=VERIFY_FAILED,
                )
            doomed = snapshot.delete_closure(fields, tables)
            new = snapshot.delete_nodes(fields, tables)
        except ValueError as exc:
            raise ApplicationError(
                f"offline delete_nodes rejected the request: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        collateral = tuple(
            sorted(
                f"{n} {kind_name} node(s)"
                for kind_name, n in Counter(
                    (before_draft.get(nid) or {}).get("Kind", "?") for nid in doomed
                ).items()
            )
        )

        await order.apply(new)
        read_back = await order.read_back()
        after_draft = read_back.to_wire()

        requested = fields + tables
        targets = [(n, (n,), ()) for n in fields] + [(n, (), (n,)) for n in tables]
        surviving = tuple(
            token
            for token, f_arg, t_arg in targets
            if any(nid in after_draft for nid in snapshot.delete_closure(f_arg, t_arg))
        )
        deleted = tuple(token for token in requested if token not in surviving)

        published = False
        if request.publish and not surviving:
            await self._flow.publish(request.app_id, request.kind, request.flow_id)
            published = True

        raise_if_write_failed(published=published, surviving=surviving)

        return ForgeDeleteFieldsResponse(
            flow_id=request.flow_id,
            fields=list(fields),
            tables=list(tables),
            deleted=list(deleted),
            surviving=list(surviving),
            collateral=list(collateral),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
