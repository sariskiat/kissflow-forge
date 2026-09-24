"""app.application.models.requests.copilot.forge_copilot_ask_request — the
`forge_copilot_ask` request DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCopilotAskRequest(BaseModel):
    """One `forge_copilot_ask` call: send one message to the app's copilot
    thread.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    message: str
    expect: list[str] | None = None
