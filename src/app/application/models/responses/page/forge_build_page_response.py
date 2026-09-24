"""app.application.models.responses.page.forge_build_page_response — the
`forge_build_page` response DTO.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

_STEPS_ONLY_KEYS = ("applied", "node_counts")
_OP_ONLY_KEYS = ("page_name", "page_created", "built", "skipped", "refused")


class ForgeBuildPageResponse(BaseModel):
    """The output-invariant audit for `forge_build_page`.

    One response type for both old entries (`app.infrastructure.kissflow.
    pages_live.PageBuildReport` for `steps`, `.BuildPageOpReport` for `op`),
    but the dump equals the OLD dict for whichever entry actually ran, never
    a union of both: `entry` records which one, and the wrap serializer
    below drops `entry` itself plus every field the OTHER entry's old
    report never had (correction, 2026-09-23 -- the same
    `@model_serializer(mode="wrap")` technique `ForgeDatasetRecordsResponse`
    uses for its own per-op key set).

    Attributes:
        entry: Which old entry produced this response -- `"steps"` for the
            raw `steps` primitive, `"op"` for the governed `op` executor.
            Never itself in the dump.
        app_id: The application id.
        page_id: The page id (always known on a returned response).
        page_name: The `op` entry's page name. `op`-only.
        page_created: Whether the `op` entry created a new page (`False`
            when it reused an existing one by name). `op`-only.
        applied: The `steps` entry's step labels, in order. `steps`-only.
        built: The `op` entry's built sub-item labels. `op`-only.
        skipped: The `op` entry's skipped sub-item labels (each with its
            Known-Exclusion reason). `op`-only.
        refused: The `op` entry's refused sub-item labels. `op`-only.
        verified: Labels confirmed present on read-back, both entries.
        missing: Labels requested but absent on read-back, both entries.
        node_counts: The `steps` entry's read-back node-count summary.
            `steps`-only.
        meta_version: The page draft's version after the write.
        published: Whether this call published.
        snapshot_version: The pre-write draft version this call snapshotted.
    """

    model_config = ConfigDict(frozen=True)

    entry: Literal["steps", "op"]
    app_id: str
    page_id: str | None
    page_name: str | None = None
    page_created: bool | None = None
    applied: list[str] = []
    built: list[str] = []
    skipped: list[str] = []
    refused: list[str] = []
    verified: list[str]
    missing: list[str]
    node_counts: dict[str, int] | None = None
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None

    @model_serializer(mode="wrap")
    def _drop_the_other_entrys_keys(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Serialize with `entry` itself dropped, and the OTHER entry's
        fields dropped -- the old dict for one entry never carried the other
        entry's keys at all.

        Args:
            handler: The default pydantic-core serializer for this model.

        Returns:
            The serialized dict: exactly `PageBuildReport.as_tool_result()`'s
            keys (minus `isError`, plus `snapshot_version`) for `entry ==
            "steps"`, or exactly `BuildPageOpReport.as_tool_result()`'s keys
            (minus `isError`, plus `snapshot_version`) for `entry == "op"`.
        """
        data = handler(self)
        data.pop("entry", None)
        drop = _OP_ONLY_KEYS if self.entry == "steps" else _STEPS_ONLY_KEYS
        for key in drop:
            data.pop(key, None)
        return data
