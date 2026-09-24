"""app.application.models.requests.copilot.forge_copilot_check_request —
the `forge_copilot_check` request DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCopilotCheckRequest(BaseModel):
    """One `forge_copilot_check` call: the real verdict for a prior
    `forge_copilot_ask`.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    conversation_id: str
    baseline_inventory: dict[str, list[str]] | None = None
