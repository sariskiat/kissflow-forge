"""app.application.models.responses.flow.forge_rename_fields_response — the DTO for
`forge_rename_fields`'s result: today's `client.RenameFieldsReport.as_tool_result()`,
minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeRenameFieldsResponse(BaseModel):
    """The output-invariant audit of one `forge_rename_fields` call.

    Each requested rename lands in exactly one of `verified` (both halves
    landed), `missing` (the new name never appeared), `stale` (the new name
    landed but the old one also survives — worse than `missing`, a
    half-applied or duplicated rename), or `unchanged` (an honest no-op,
    old == new).
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    renames: list[str]
    verified: list[str]
    missing: list[str]
    stale: list[str]
    unchanged: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
