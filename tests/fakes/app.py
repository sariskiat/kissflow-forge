"""In-memory `AppRepository` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.app import AppRepository
from app.domain.entities.navigation import Navigation


class FakeAppRepository(RecordingMixin, AppRepository):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def list_app_roles(self, app_id: str | None = None) -> list[dict[str, Any]]:
        return self._record("list_app_roles", (), {"app_id": app_id}, [])

    async def get_app_role(self, role_id: str) -> dict[str, Any]:
        return self._record("get_app_role", (role_id,), {}, {})

    async def put_app_role(
        self, app_id: str, role_id: str, body: dict[str, Any]
    ) -> Any:
        return self._record("put_app_role", (app_id, role_id, body), {})

    async def get_assignee(self, query: str) -> list[dict[str, Any]]:
        return self._record("get_assignee", (query,), {}, [])

    async def create_app_role(self, name: str, app_id: str | None = None) -> str:
        return self._record("create_app_role", (name,), {"app_id": app_id}, "")

    async def delete_app_role(self, role_id: str) -> Any:
        return self._record("delete_app_role", (role_id,), {})

    async def list_applications(self) -> list[dict[str, Any]]:
        return self._record("list_applications", (), {}, [])

    async def create_application(self, name: str) -> str:
        return self._record("create_application", (name,), {}, "")

    async def delete_application(self, app_id: str, archive_first: bool = True) -> None:
        return self._record(
            "delete_application", (app_id,), {"archive_first": archive_first}
        )

    async def get_app_draft(self, app_id: str) -> Navigation:
        return self._record("get_app_draft", (app_id,), {}, Navigation.from_wire({}))

    async def put_app_draft(
        self, app_id: str, new: Navigation, expect_version: str | None
    ) -> Navigation:
        return self._record(
            "put_app_draft",
            (app_id, new),
            {"expect_version": expect_version},
            new,
        )

    async def publish_app(self, app_id: str) -> None:
        return self._record("publish_app", (app_id,), {})
