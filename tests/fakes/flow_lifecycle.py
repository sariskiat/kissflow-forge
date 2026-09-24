"""A persisting flow-port fake for the lifecycle use-case tests.

The port form of the old suites' `_CreateProcessClient` (`tests/test_client.py`) and
`CreateFlowClient` (`tests/test_p4_surface.py`): one draft held in memory, every
`put_draft` applied to it, so a ported test can read back what the scaffold actually
wrote -- the shared `tests.fakes.flow.FakeFlowRepository` only records calls and
returns queued values, it never persists a write. Word lists persist the same way
(the old `FakeClient.lists`/`list_items`/`drop_list_values`).

Not collected by pytest (no `test_` prefix), and it lives under `tests/`, so the
mirror rule does not apply to it.
"""

from __future__ import annotations

from typing import Any

from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import RepositoryError
from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.kinds import AnyFlowKind, DataKind


def bare_process_wire(version: str = "v1") -> dict[str, Any]:
    """A freshly created process's draft: only `{Root, Model}` (the old suites'
    `_bare_process_draft`)."""
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


class PersistingFlowRepository(FakeFlowRepository):
    """Holds one draft and applies every `put_draft` to it; still records every call.

    Args to `__init__`:
        draft: The starting draft (default: a bare process).
        failing_read_from: The 1-based `get_draft` call from which every read
            raises `RepositoryError("GET draft -> 503")`; `None` never fails.
        ack_put: Answer `put_draft` with an ack, never the graph (the old
            `_AckOnlyPutClient`), while still persisting the write.
    """

    def __init__(
        self,
        draft: dict[str, Any] | None = None,
        *,
        failing_read_from: int | None = None,
        ack_put: bool = False,
    ) -> None:
        super().__init__()
        self.draft = FlowDraft.from_wire(draft or bare_process_wire())
        self.puts = 0
        self.list_ids: dict[str, str] = {}
        self.list_items: dict[str, list[str]] = {}
        self.drop_list_values: set[str] = set()
        self._reads = 0
        self._ids = 0
        self._failing_read_from = failing_read_from
        self._ack_put = ack_put

    def _next_id(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}_{self._ids}"

    async def create_flow(self, app_id: str, kind: AnyFlowKind, name: str) -> str:
        self._record("create_flow", (app_id, kind, name), {})
        return "F1"

    async def get_draft(
        self, app_id: str, kind: AnyFlowKind, flow_id: str
    ) -> FlowDraft:
        self._record("get_draft", (app_id, kind, flow_id), {})
        self._reads += 1
        if (
            self._failing_read_from is not None
            and self._reads >= self._failing_read_from
        ):
            raise RepositoryError("GET draft -> 503")
        return self.draft

    async def put_draft(
        self,
        app_id: str,
        kind: DataKind,
        flow_id: str,
        new: FlowDraft,
        expect_version: str | None,
    ) -> FlowDraft:
        self._record(
            "put_draft",
            (app_id, kind, flow_id, new),
            {"expect_version": expect_version},
        )
        self.puts += 1
        self.draft = new
        if self._ack_put:
            return FlowDraft.from_wire({"_id": flow_id, "success": True})
        return new

    async def list_lists(self, app_id: str) -> list[dict[str, Any]]:
        self._record("list_lists", (app_id,), {})
        return [{"Name": name, "_id": lid} for name, lid in self.list_ids.items()]

    async def create_list(self, app_id: str, name: str) -> dict[str, Any]:
        self._record("create_list", (app_id, name), {})
        list_id = self._next_id("List")
        self.list_ids[name] = list_id
        return {"_id": list_id, "Type": "List", "Status": "Live", "Name": name}

    async def set_list_items(self, list_id: str, items: list[str]) -> Any:
        self._record("set_list_items", (list_id, items), {})
        self.list_items[list_id] = list(items)

    async def get_list_items(self, app_id: str, list_id: str) -> list[str]:
        self._record("get_list_items", (app_id, list_id), {})
        return [
            v
            for v in self.list_items.get(list_id, [])
            if v not in self.drop_list_values
        ]

    async def create_dataset(self, app_id: str, name: str) -> dict[str, Any]:
        self._record("create_dataset", (app_id, name), {})
        return {
            "_id": self._next_id("Dataset"),
            "Type": "Dataset",
            "Status": "Live",
            "Name": name,
        }

    async def create_case(
        self, app_id: str, name: str, item_type: str, prefix: str
    ) -> dict[str, Any]:
        self._record("create_case", (app_id, name, item_type, prefix), {})
        return {
            "_id": self._next_id("Case"),
            "Type": "Case",
            "Status": "Live",
            "Name": name,
            "ItemType": item_type,
            "Prefix": prefix,
        }
