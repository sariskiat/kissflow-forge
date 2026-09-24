"""app.application.models.responses.copilot.forge_copilot_ask_response —
the `forge_copilot_ask` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

_NOTE = (
    "reply text is NEVER proof of success — structural builds land ~70s later, "
    "not immediately; call forge_copilot_check after a real delay and diff the "
    "actual graph before trusting anything landed (THE RULE). A null "
    "conversation_id with status 'pending' is EXPECTED, not a failure."
)


class ForgeCopilotAskResponse(BaseModel):
    """`forge_copilot_ask`'s own report: the ONE immediate read-back, never
    trusted as proof anything landed (THE RULE) -- `forge_copilot_check` is
    the real verdict, after a real delay.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    message: str
    conversation_id: str | None
    immediate_reply: str | None
    expect: list[str]
    reply_is_proof: bool = False
    status: str
    note: str = _NOTE
    snapshot_version: str | None = None
