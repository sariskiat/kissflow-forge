"""app.application.use_cases.copilot.forge_copilot_ask — the
`forge_copilot_ask` use case.

Ported from `app.infrastructure.kissflow.client.apply_copilot_ask`
(refactor spec, Stage D group `d7_page_data_item_copilot`): SEND one message
to the app's copilot thread, then ONE immediate read of the conversation
list -- deliberately not a long poll (an MCP tool call has a budget).
"""

from __future__ import annotations

from app.application.exceptions import ExternalServiceError
from app.application.interfaces.copilot import CopilotService
from app.application.models.requests.copilot.forge_copilot_ask_request import (
    ForgeCopilotAskRequest,
)
from app.application.models.responses.copilot.forge_copilot_ask_response import (
    ForgeCopilotAskResponse,
)
from app.application.use_cases.copilot._app_id import require_app_id

_PENDING = (
    "pending: your message is not in the thread yet — this is NORMAL, the "
    "copilot lags ~70s; call forge_copilot_check after a real delay, do "
    "not retry the ask"
)


class ForgeCopilotAsk:
    """Send one message to the app's copilot thread and do one immediate
    read-back.
    """

    def __init__(self, copilot: CopilotService) -> None:
        """Build the use case around its one port.

        Args:
            copilot: The in-builder AI copilot family port.
        """
        self._copilot = copilot

    async def execute(self, request: ForgeCopilotAskRequest) -> ForgeCopilotAskResponse:
        """Send `request.message` and read the thread back once.

        Args:
            request: The validated `forge_copilot_ask` request.

        Returns:
            The immediate read-back report -- never proof anything landed;
            see `forge_copilot_check` for the real verdict.

        Raises:
            ApplicationError: `request.app_id` is empty (`code=REFUSED`).
            ExternalServiceError: The send failed.
        """
        require_app_id(request.app_id)

        await self._copilot.copilot_send(request.app_id, request.message)

        conversation_id: str | None = None
        reply: str | None = None
        try:
            convs = await self._copilot.copilot_conversations(request.app_id)
        except ExternalServiceError as exc:
            # Fail loud, never a silent null: a READ failure must not read
            # back identical to "message not registered yet" (Cowork bug
            # report 2026-08-13). "http" (not `exc.code`, always the generic
            # "EXTERNAL_SERVICE_ERROR" here) matches the old `Err.kind` this
            # ported from (`client.py:6041`, pre-refactor) -- a
            # `copilot_conversations` failure is always the HTTP layer.
            status = f"read_failed: http: {exc.message}"
        else:
            for c in convs:
                if isinstance(c, dict) and c.get("UserMessage") == request.message:
                    conversation_id = c.get("ConversationId")
                    reply = c.get("SystemMessage")
                    break
            status = "matched" if conversation_id else _PENDING

        return ForgeCopilotAskResponse(
            app_id=request.app_id,
            message=request.message,
            conversation_id=conversation_id,
            immediate_reply=reply,
            expect=list(request.expect or ()),
            status=status,
        )
