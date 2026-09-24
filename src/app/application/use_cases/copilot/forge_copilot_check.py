"""app.application.use_cases.copilot.forge_copilot_check — the
`forge_copilot_check` use case.

Ported from `app.infrastructure.kissflow.client.apply_copilot_check`
(refactor spec, Stage D group `d7_page_data_item_copilot`): read the
copilot thread for `conversation_id`, and diff the app's CURRENT flow
inventory against `baseline_inventory`. Every flow id that showed up since
is `scatter`; each scattered flow's draft is read once for a cheap
top-level node COUNT (`landed_nodes`), never a full semantic diff.
"""

from __future__ import annotations

from app.application.interfaces.copilot import CopilotService
from app.application.interfaces.flow import FlowRepository
from app.application.models.requests.copilot.forge_copilot_check_request import (
    ForgeCopilotCheckRequest,
)
from app.application.models.responses.copilot.forge_copilot_check_response import (
    ForgeCopilotCheckResponse,
)
from app.application.use_cases.copilot import _copilot
from app.application.use_cases.copilot._app_id import require_app_id


class ForgeCopilotCheck:
    """The real verdict for a prior `forge_copilot_ask` call: the thread's
    reply (never trusted alone) plus which flows scattered.
    """

    def __init__(self, copilot: CopilotService, flow: FlowRepository) -> None:
        """Build the use case around its two ports.

        Args:
            copilot: The in-builder AI copilot family port.
            flow: The flow/process/form/case/list family port, for the
                app-scoped flow inventory and each scattered flow's node
                count.
        """
        self._copilot = copilot
        self._flow = flow

    async def execute(
        self, request: ForgeCopilotCheckRequest
    ) -> ForgeCopilotCheckResponse:
        """Read the thread and diff the flow inventory.

        Args:
            request: The validated `forge_copilot_check` request.

        Returns:
            The verdict: the thread's reply (`None` for a still-pending
            ask) plus which flows scattered. The call itself always
            succeeds when it can read the thread -- never a `ToolError`
            for a pending reply (rule 7 exception,
            `brief_stage_d_common.md`).

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`).
            ExternalServiceError: The conversation read failed.
            RepositoryError: The flow inventory read failed.
        """
        require_app_id(request.app_id)

        convs = await self._copilot.copilot_conversations(request.app_id)
        thread = [
            c
            for c in convs
            if isinstance(c, dict)
            and c.get("ConversationId") == request.conversation_id
        ]
        reply = next(
            (c.get("SystemMessage") for c in thread if c.get("SystemMessage")), None
        )

        current = await _copilot.flow_id_inventory(self._flow, request.app_id)
        baseline = request.baseline_inventory or {}
        scatter: dict[str, list[str]] = {}
        landed_nodes: dict[str, dict[str, int]] = {}
        for kind, ids in current.items():
            base_ids = set(baseline.get(kind) or [])
            new_ids = [fid for fid in ids if fid not in base_ids]
            if not new_ids:
                continue
            scatter[kind] = new_ids
            counts: dict[str, int] = {}
            for fid in new_ids:
                counts[fid] = await _copilot.node_count(
                    self._flow, request.app_id, kind, fid
                )
            landed_nodes[kind] = counts

        return ForgeCopilotCheckResponse(
            app_id=request.app_id,
            conversation_id=request.conversation_id,
            reply=reply,
            scatter=scatter,
            landed_nodes=landed_nodes,
        )
