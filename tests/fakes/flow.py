"""In-memory `FlowRepository` fake, recording every call in order."""

from __future__ import annotations

from typing import Any

from tests.fakes._recording import RecordingMixin

from app.application.interfaces.flow import FlowRepository
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.kinds import AnyFlowKind, DataKind, FlowKind


class FakeFlowRepository(RecordingMixin, FlowRepository):
    """Records every call; returns a queued or default value (see `RecordingMixin`)."""

    async def get_draft(
        self, app_id: str, kind: AnyFlowKind, flow_id: str
    ) -> FlowDraft:
        return self._record(
            "get_draft", (app_id, kind, flow_id), {}, FlowDraft.from_wire({})
        )

    async def create_flow(self, app_id: str, kind: AnyFlowKind, name: str) -> str:
        return self._record("create_flow", (app_id, kind, name), {}, "")

    async def delete_flow(
        self,
        app_id: str,
        kind: AnyFlowKind,
        flow_id: str,
        archive_first: bool = True,
    ) -> None:
        return self._record(
            "delete_flow",
            (app_id, kind, flow_id),
            {"archive_first": archive_first},
        )

    async def publish(self, app_id: str, kind: FlowKind, flow_id: str) -> None:
        return self._record("publish", (app_id, kind, flow_id), {})

    async def get_flow_detail(
        self, app_id: str, kind: FlowKind, flow_id: str
    ) -> dict[str, Any]:
        return self._record("get_flow_detail", (app_id, kind, flow_id), {}, {})

    async def list_flows(self, app_id: str, kind: AnyFlowKind) -> list[dict[str, Any]]:
        return self._record("list_flows", (app_id, kind), {}, [])

    async def get_members(
        self, app_id: str, kind: FlowKind, flow_id: str
    ) -> list[dict[str, Any]]:
        return self._record("get_members", (app_id, kind, flow_id), {}, [])

    async def delete_member(
        self, app_id: str, kind: FlowKind, flow_id: str, role_id: str
    ) -> Any:
        return self._record("delete_member", (app_id, kind, flow_id, role_id), {})

    async def post_member_batch(
        self,
        app_id: str,
        kind: FlowKind,
        flow_id: str,
        members: list[dict[str, Any]],
    ) -> Any:
        return self._record("post_member_batch", (app_id, kind, flow_id, members), {})

    async def post_report_member_batch(
        self,
        app_id: str,
        flow_id: str,
        report_id: str,
        members: list[dict[str, Any]],
    ) -> Any:
        return self._record(
            "post_report_member_batch", (app_id, flow_id, report_id, members), {}
        )

    async def get_list_items(self, app_id: str, list_id: str) -> list[str]:
        return self._record("get_list_items", (app_id, list_id), {}, [])

    async def list_lists(self, app_id: str) -> list[dict[str, Any]]:
        return self._record("list_lists", (app_id,), {}, [])

    async def create_list(self, app_id: str, name: str) -> dict[str, Any]:
        return self._record("create_list", (app_id, name), {}, {})

    async def set_list_items(self, list_id: str, items: list[str]) -> Any:
        return self._record("set_list_items", (list_id, items), {})

    async def create_dataset(self, app_id: str, name: str) -> dict[str, Any]:
        return self._record("create_dataset", (app_id, name), {}, {})

    async def create_case(
        self, app_id: str, name: str, item_type: str, prefix: str
    ) -> dict[str, Any]:
        return self._record("create_case", (app_id, name, item_type, prefix), {}, {})

    async def put_draft(
        self,
        app_id: str,
        kind: DataKind,
        flow_id: str,
        new: FlowDraft,
        expect_version: str | None,
    ) -> FlowDraft:
        return self._record(
            "put_draft",
            (app_id, kind, flow_id, new),
            {"expect_version": expect_version},
            new,
        )
