"""In-memory `ItemService` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.item import ItemService


class FakeItemService(RecordingMixin, ItemService):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def create_item(self, flow_id: str) -> dict[str, Any]:
        return self._record("create_item", (flow_id,), {}, {})

    async def put_fields(
        self, flow_id: str, iid: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record("put_fields", (flow_id, iid, payload), {}, {})

    async def get_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        return self._record("get_detail", (flow_id, iid), {}, {})

    async def submit(self, flow_id: str, iid: str, aiid: str) -> dict[str, Any]:
        return self._record("submit", (flow_id, iid, aiid), {}, {})

    async def reject(
        self, flow_id: str, iid: str, aiid: str, comment: str
    ) -> dict[str, Any]:
        return self._record("reject", (flow_id, iid, aiid, comment), {}, {})
