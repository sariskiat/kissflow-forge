"""app.application.models.responses.flow.forge_add_table_response — the
`forge_add_table` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeAddTableResponse(BaseModel):
    """The output-invariant audit for `forge_add_table`: every requested
    child column name lands in exactly one of `verified_columns` /
    `missing_columns`.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    table_name: str
    created: bool
    columns: list[str]
    verified_columns: list[str]
    missing_columns: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
