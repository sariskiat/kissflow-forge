"""app.application.models.responses.flow.forge_apply_fields_response — the DTO for
`forge_apply_fields`'s result: today's `client.FullFieldsReport.as_tool_result()`,
minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeApplyFieldsResponse(BaseModel):
    """The output-invariant audit of one `forge_apply_fields` call.

    Four independent layers, each its own verified/missing pair: the fields
    themselves, `validation` rules, `computed` formulas and
    `conditional_visibility` rules.
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
    validations_verified: list[str]
    validations_missing: list[str]
    computed_verified: list[str]
    computed_missing: list[str]
    conditional_verified: list[str]
    conditional_missing: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
