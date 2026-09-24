"""app.application.models.responses.flow.forge_apply_layout_response — the DTO for
`forge_apply_layout`'s result: today's `client.ApplyReport.as_tool_result()`, minus
`isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeApplyLayoutResponse(BaseModel):
    """The output-invariant audit of one `forge_apply_layout` call.

    `added`/`missing`/`changed_ignored` are always empty here — a layout
    write never adds or drops a field, only re-places existing ones — kept
    on the response so its shape matches every other `ApplyReport`-derived
    tool (`kf_apply_field_change`).
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    added: list[str]
    skipped: list[str]
    verified: list[str]
    missing: list[str]
    changed_ignored: list[str]
    collateral: list[str]
    remediation: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
