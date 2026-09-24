"""`CopilotService`: the ABC refuses instantiation; the fake implements every abstract
method."""

from __future__ import annotations

import pytest
from tests.fakes.copilot import FakeCopilotService

from app.application.interfaces.copilot import CopilotService


def test_copilot_service_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        CopilotService()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakeCopilotService()

    await fake.copilot_send("A1", "hello")
    await fake.copilot_conversations("A1")

    assert [call[0] for call in fake.calls] == [
        "copilot_send",
        "copilot_conversations",
    ]
