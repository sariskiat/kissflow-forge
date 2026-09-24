"""app.application.models.responses.flow.forge_delete_fields_response — the DTO for
`forge_delete_fields`'s result: today's `client.DeleteFieldsReport.as_tool_result()`,
minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeDeleteFieldsResponse(BaseModel):
    """The output-invariant audit of one `forge_delete_fields` call. INVERTED unit:
    success is a requested name being ABSENT on read-back, so `deleted` (not
    `verified`) is the success bucket and `surviving` is the loud failure.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    fields: list[str]
    tables: list[str]
    deleted: list[str]
    surviving: list[str]
    collateral: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
