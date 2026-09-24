"""app.application.use_cases.flow.forge_set_events — the `forge_set_events`
use case.
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.flow.forge_set_events_request import (
    ForgeSetEventsRequest,
)
from app.application.models.responses.flow.forge_set_events_response import (
    ForgeSetEventsResponse,
)
from app.application.use_cases.flow._events import resolve_event_triggers
from app.application.use_cases.flow._fields import raise_if_write_failed, require_app_id
from app.application.use_cases.flow._write_order import WriteOrder
from app.domain.entities.flow_draft import FlowDraft


class ForgeSetEvents:
    """Attach SDK field events: GET draft -> derive each source field's
    trigger from its live type -> `FlowDraft.set_field_events` offline
    (rejects a top-level `await` or a `KFSDK` reference before any write) ->
    guarded PUT -> read-back verify each named field carries a Field::Event
    -> optional publish.
    """

    def __init__(self, flow: FlowRepository) -> None:
        """Build the use case around its one port.

        Args:
            flow: The flow/process/form/case/list family port.
        """
        self._flow = flow

    async def execute(self, request: ForgeSetEventsRequest) -> ForgeSetEventsResponse:
        """Run the set-events write order and return its audit.

        Args:
            request: The validated `forge_set_events` request.

        Returns:
            The output-invariant audit, plus the resolved trigger list and
            any unverified (family-inferred) triggers, only when every
            requested field verified: `missing` is always empty on a
            returned response. A field carrying only an unverified
            (family-inferred) trigger still counts as verified -- CLAUDE.md
            Field events: uncertainty about the trigger is not a failure.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`); a
                trigger could not be resolved; the offline
                `set_field_events` rejected the spec (`code=VERIFY_FAILED`);
                or one or more fields did not verify on read-back
                (`code=VERIFY_FAILED`, naming the missing fields and
                whether anything published).
        """
        require_app_id(request.app_id)

        order: WriteOrder[FlowDraft] = WriteOrder(
            get=lambda: self._flow.get_draft(
                request.app_id, request.kind, request.flow_id
            ),
            put=lambda new, expect_version: self._flow.put_draft(
                request.app_id, request.kind, request.flow_id, new, expect_version
            ),
            version_of=lambda d: d.version,
            publish=lambda: self._flow.publish(
                request.app_id, request.kind, request.flow_id
            ),
        )

        draft = await order.snapshot()
        wire = draft.to_wire()
        try:
            plan = resolve_event_triggers(wire, request.events)
        except ValueError as exc:
            raise ApplicationError(
                f"field-event trigger check refused the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc

        try:
            new_draft = draft.set_field_events(plan.events)
        except ValueError as exc:
            raise ApplicationError(
                f"offline set_field_events rejected the spec: {exc}",
                code=VERIFY_FAILED,
            ) from exc
        await order.apply(new_draft)

        read_back = await order.read_back()
        by_name = {
            v.get("Name"): v
            for v in read_back.to_wire().values()
            if isinstance(v, dict) and v.get("Kind") == "Field"
        }
        wanted = tuple(request.events)
        verified = tuple(n for n in wanted if by_name.get(n, {}).get("Field::Event"))
        missing = tuple(n for n in wanted if n not in verified)

        published = False
        if request.publish and not missing:
            await order.publish()
            published = True

        raise_if_write_failed(published=published, missing=missing)

        return ForgeSetEventsResponse(
            flow_id=request.flow_id,
            fields=list(wanted),
            verified=list(verified),
            missing=list(missing),
            triggers=list(plan.triggers),
            derived=list(plan.derived),
            unverified=list(plan.unverified),
            meta_version=read_back.version,
            published=published,
            snapshot_version=order.snapshot_version,
        )
