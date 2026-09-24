"""The dataset-family tool module (dataform records).

`register(mcp)` wires every dataset-family tool onto the new, thin server
(spec G12). One work group -- there is no second group in this family to
keep merge-distance from.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from app.application.models.requests.dataset.forge_dataset_records_request import (
    ForgeDatasetRecordsRequest,
)
from app.application.models.responses.dataset.forge_dataset_records_response import (
    ForgeDatasetRecordsResponse,
)
from app.application.use_cases.dataset.forge_dataset_records import (
    ForgeDatasetRecords,
)
from app.domain.value_objects.kinds import DatasetOp
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every dataset-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Dataset tools: create/list/update/delete dataform records.
    Filled by the dataset family writer (Stage D)."""

    @mcp.tool(title="Dataform records", annotations=_shared.LIVE_REPLACE_ONCE)
    async def forge_dataset_records(
        flow_id: str,
        op: DatasetOp,
        record: dict[str, Any] | None = None,
        record_id: str | None = None,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeDatasetRecordsResponse:
        """LIVE (dev only, KF_APP): the THIRD data-plane route family — dataform records (#50, #58).
        Distinct from the process item data plane and the word-list items route. Record KEYS accept a
        field NAME or a field id for `create`/`update` — auto-resolved to ids against the dataform's
        live draft before the write (the raw route 404s FieldNotFound on a name key); the synthetic
        `Name` key (the record's unique key) passes through. A name matching no field fails loud,
        listing every available field name.

        - `op="create"`: writes ONE `record` (must carry the `Name` unique key; a duplicate 409s
          cleanly, named in the error).
        - `op="update"`: partial-patches the record `record_id` (`PUT .../{flow}?_id={rec}`) with
          `record` — only the keys sent change.
        - `op="delete"`: deletes `record_id` (`DELETE .../{flow}?_id={rec}`); `record` must carry the
          mandatory `{"Name": ...}` delete body.
        - `op="list"`: reads back `{Columns, Data}`.

        No membership gate on a dataform (#50) — records work with zero members.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeDatasetRecordsRequest(
                flow_id=flow_id,
                op=op,
                record=record,
                record_id=record_id,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeDatasetRecords(
                dataset=resources.dataset, flow=resources.flow
            ),
        )
