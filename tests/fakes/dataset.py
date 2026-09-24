"""In-memory `DatasetRepository` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.dataset import DatasetRepository


class FakeDatasetRepository(RecordingMixin, DatasetRepository):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def create_dataset_record(
        self, app_id: str, flow_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record("create_dataset_record", (app_id, flow_id, record), {}, {})

    async def list_dataset_records(self, app_id: str, flow_id: str) -> dict[str, Any]:
        return self._record("list_dataset_records", (app_id, flow_id), {}, {})

    async def update_dataset_record(
        self, app_id: str, flow_id: str, record_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        return self._record(
            "update_dataset_record",
            (app_id, flow_id, record_id, record),
            {},
            {},
        )

    async def delete_dataset_record(
        self, app_id: str, flow_id: str, record_id: str, name: str
    ) -> dict[str, Any]:
        return self._record(
            "delete_dataset_record", (app_id, flow_id, record_id, name), {}, {}
        )
