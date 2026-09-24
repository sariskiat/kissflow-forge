"""CopilotService — the port over the Kissflow in-builder AI copilot family.

One abstract method per public `KfClient` method the `copilot` family owns (refactor
spec inventory, section 1). Unlike the builder-API families, copilot raises
`app.application.exceptions.ExternalServiceError`, not `RepositoryError` (spec G7 Part
1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CopilotService(ABC):
    """The in-builder AI copilot: send a message, read the conversation back.

    Every method raises `app.application.exceptions.ExternalServiceError` on
    any failure translated out of infrastructure. No method returns an `Err`.
    """

    @abstractmethod
    async def copilot_send(self, app_id: str, message: str) -> Any:
        """Send a message to the in-builder AI copilot
        (`POST /metadata/2/{account}/ai/application/{app_id}/copilot/send`).

        An ACK response proves nothing about whether anything actually
        landed (THE RULE) — a caller reads the conversation back with
        `copilot_conversations` instead of trusting this reply.

        Args:
            app_id: The application the copilot session belongs to.
            message: The free-text message to send.

        Returns:
            The parsed response body (an ACK, e.g. `{"status": "success"}`).

        Raises:
            ExternalServiceError: The send failed.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def copilot_conversations(self, app_id: str) -> list[dict[str, Any]]:
        """Read the copilot thread for an application
        (`GET /metadata/2/{account}/ai/application/{app_id}/copilot/conversations`).

        Args:
            app_id: The application the copilot session belongs to.

        Returns:
            The conversation, newest-first; pair `UserMessage` with
            `SystemMessage` by `ConversationId`.

        Raises:
            ExternalServiceError: The read failed.
        """
        raise NotImplementedError  # pragma: no cover
