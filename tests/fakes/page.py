"""In-memory `PageRepository` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.page import PageRepository
from app.domain.entities.page_draft import PageDraft


class FakePageRepository(RecordingMixin, PageRepository):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def list_pages(self, app_id: str) -> list[dict[str, Any]]:
        return self._record("list_pages", (app_id,), {}, [])

    async def create_page(self, app_id: str, name: str) -> str:
        return self._record("create_page", (app_id, name), {}, "")

    async def delete_page(self, app_id: str, page_id: str) -> None:
        return self._record("delete_page", (app_id, page_id), {})

    async def get_page_draft(self, app_id: str, page_id: str) -> PageDraft:
        return self._record(
            "get_page_draft", (app_id, page_id), {}, PageDraft.from_wire({})
        )

    async def put_page_draft(
        self,
        app_id: str,
        page_id: str,
        new: PageDraft,
        expect_version: str | None,
    ) -> PageDraft:
        return self._record(
            "put_page_draft",
            (app_id, page_id, new),
            {"expect_version": expect_version},
            new,
        )

    async def publish_page(self, app_id: str, page_id: str) -> None:
        return self._record("publish_page", (app_id, page_id), {})
