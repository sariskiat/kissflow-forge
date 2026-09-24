"""app.application.models.responses.copilot.forge_copilot_check_response —
the `forge_copilot_check` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

_NOTE = (
    "scatter = flow ids present now but absent from baseline_inventory; "
    "landed_nodes is a cheap top-level-key COUNT per new flow, not a "
    "semantic diff — never trust `reply` alone (THE RULE)"
)


class ForgeCopilotCheckResponse(BaseModel):
    """The real verdict for a prior `forge_copilot_ask` call.

    A verdict tool (rule 7 exception, `brief_stage_d_common.md`): the call
    itself always succeeds when it can read the thread, whether or not a
    system reply has landed yet -- `reply` is `None` for a still-pending
    ask, never a `ToolError`. `reply_is_proof` is always `False`: THE RULE
    is that the reply text is never proof a build landed, only `scatter`
    and `landed_nodes` are.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    conversation_id: str
    reply: str | None
    reply_is_proof: bool = False
    scatter: dict[str, list[str]]
    landed_nodes: dict[str, dict[str, int]]
    note: str = _NOTE
