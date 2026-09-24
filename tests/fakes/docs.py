"""In-memory `DocsReader` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.docs import DocsReader
from app.domain.value_objects.kinds import PlaybookName


class FakeDocsReader(RecordingMixin, DocsReader):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def playbook(self, skill: PlaybookName = "builder") -> dict[str, Any]:
        return self._record(
            "playbook", (), {"skill": skill}, {"text": "", "source": ""}
        )

    async def capabilities(self, query: str = "") -> dict[str, Any]:
        return self._record(
            "capabilities", (), {"query": query}, {"docs": [], "errors": []}
        )
