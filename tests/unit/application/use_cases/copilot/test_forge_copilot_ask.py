"""`ForgeCopilotAsk`: ported from `tests/test_p4_surface.py`'s
`test_copilot_ask_*` cases (pre-refactor), now against the response DTO or
the raised `ApplicationError` and its code, with
`tests.fakes.copilot.FakeCopilotService`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.copilot import FakeCopilotService

from app.application.exceptions import ApplicationError, ExternalServiceError
from app.application.models.requests.copilot.forge_copilot_ask_request import (
    ForgeCopilotAskRequest,
)
from app.application.use_cases.copilot.forge_copilot_ask import ForgeCopilotAsk


def _request(**overrides: Any) -> ForgeCopilotAskRequest:
    fields: dict[str, Any] = {"app_id": "App1", "message": "add a field"}
    fields.update(overrides)
    return ForgeCopilotAskRequest(**fields)


@pytest.mark.asyncio
async def test_sends_and_reads_back_the_paired_reply() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [
        [
            {
                "ConversationId": "C1",
                "UserMessage": "add a field",
                "SystemMessage": "which step?",
            }
        ]
    ]

    resp = await ForgeCopilotAsk(copilot).execute(_request())

    assert resp.conversation_id == "C1"
    assert resp.immediate_reply == "which step?"
    assert resp.reply_is_proof is False
    assert copilot.calls[0] == ("copilot_send", ("App1", "add a field"), {})


@pytest.mark.asyncio
async def test_no_match_yet_is_not_an_error() -> None:
    copilot = FakeCopilotService()
    copilot.results["copilot_conversations"] = [[]]  # reply hasn't landed yet

    resp = await ForgeCopilotAsk(copilot).execute(_request())

    assert resp.conversation_id is None
    assert resp.immediate_reply is None
    # a null id must explain WHY -- "pending" (normal), so a caller doesn't
    # read it as broken
    assert resp.status.startswith("pending")


@pytest.mark.asyncio
async def test_surfaces_a_read_failure_instead_of_a_silent_null() -> None:
    """A `copilot_conversations` READ error must not read back identical to
    'not registered yet' -- both were null/null before, which made a caller
    conclude the tool was broken. Fail loud."""

    class _ReadFails(FakeCopilotService):
        async def copilot_conversations(self, app_id: str) -> list[dict[str, Any]]:
            self.calls.append(("copilot_conversations", (app_id,), {}))
            raise ExternalServiceError("boom", code="EXTERNAL_SERVICE_ERROR")

    resp = await ForgeCopilotAsk(_ReadFails()).execute(_request())

    assert resp.conversation_id is None
    # Byte-for-byte the old `apply_copilot_ask`'s own text
    # (`client.py:6041`, pre-refactor): `Err.kind` was always "http" for a
    # `copilot_conversations` failure, never the new `ApplicationError`
    # subclass's own `.code` ("EXTERNAL_SERVICE_ERROR") -- review fix 6.
    assert resp.status == "read_failed: http: boom"


@pytest.mark.asyncio
async def test_echoes_expect_hint() -> None:
    copilot = FakeCopilotService()

    resp = await ForgeCopilotAsk(copilot).execute(
        _request(message="add a currency field", expect=["Field"])
    )

    assert resp.expect == ["Field"]


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    copilot = FakeCopilotService()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeCopilotAsk(copilot).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert copilot.calls == []
