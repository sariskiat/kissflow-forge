"""In-memory `CopilotService` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.copilot import CopilotService


class FakeCopilotService(RecordingMixin, CopilotService):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def copilot_send(self, app_id: str, message: str) -> Any:
        return self._record("copilot_send", (app_id, message), {})

    async def copilot_conversations(self, app_id: str) -> list[dict[str, Any]]:
        return self._record("copilot_conversations", (app_id,), {}, [])
