"""Spec for app.application.use_cases.meta.forge_playbook.

The use case builds the response from the `DocsReader` port's plain data (spec G13).
`tests/test_playbook.py`'s content assertions run through the port on the real file in
`tests/unit/infrastructure/test_playbook.py`; here the fake port proves the assembly,
and that the port's `NOT_FOUND` for a missing or blank playbook propagates unchanged
(today that was an `isError` payload).
"""

from __future__ import annotations

import pytest
from tests.fakes.docs import FakeDocsReader

from app.application.exceptions import NOT_FOUND, ApplicationError
from app.application.models.requests.meta.forge_playbook_request import (
    ForgePlaybookRequest,
)
from app.application.use_cases.meta.forge_playbook import ForgePlaybook

_SOURCE = "skills/kissflow-forge-builder/SKILL.md"


@pytest.mark.asyncio
async def test_builds_the_response_from_the_port_text_and_source() -> None:
    fake = FakeDocsReader()
    fake.results["playbook"] = [
        {"text": "# THE RULE\nBuild order\n", "source": _SOURCE}
    ]

    resp = await ForgePlaybook(fake).execute(ForgePlaybookRequest())

    assert resp.model_dump(mode="json") == {
        "text": "# THE RULE\nBuild order\n",
        "chars": 23,
        "source": _SOURCE,
    }
    assert fake.calls == [("playbook", (), {"skill": "builder"})]


@pytest.mark.asyncio
async def test_passes_the_requested_skill_name_to_the_port() -> None:
    fake = FakeDocsReader()
    fake.results["playbook"] = [{"text": "# design\n", "source": "s"}]

    await ForgePlaybook(fake).execute(ForgePlaybookRequest(skill="design"))

    assert fake.calls == [("playbook", (), {"skill": "design"})]


@pytest.mark.asyncio
async def test_chars_counts_characters_not_bytes() -> None:
    fake = FakeDocsReader()
    fake.results["playbook"] = [{"text": "ก → ✓\n", "source": _SOURCE}]

    resp = await ForgePlaybook(fake).execute(ForgePlaybookRequest())

    assert resp.chars == 6


@pytest.mark.asyncio
async def test_a_not_found_playbook_propagates_unchanged() -> None:
    class _MissingPlaybook(FakeDocsReader):
        async def playbook(self, skill: str = "builder") -> dict[str, str]:
            raise ApplicationError(
                f"vendored playbook not found at {_SOURCE}", code=NOT_FOUND
            )

    with pytest.raises(ApplicationError) as info:
        await ForgePlaybook(_MissingPlaybook()).execute(ForgePlaybookRequest())

    assert info.value.code == NOT_FOUND
    assert info.value.message == f"vendored playbook not found at {_SOURCE}"
