"""app.application.models.responses.flow.kf_apply_field_change_response — the DTO for
`kf_apply_field_change`'s result: today's `client.ApplyReport.as_tool_result()`,
minus `isError` (that flag never survives into the new architecture — a caller reads
`missing`/`changed_ignored` instead), plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KfApplyFieldChangeResponse(BaseModel):
    """The output-invariant audit of one `kf_apply_field_change` call.

    Every requested field lands in exactly one of `added`/`skipped`/
    `changed_ignored` (what was planned) and, independently, in exactly one
    of `verified`/`missing`/`changed_ignored` (what the read-back saw) — see
    `app.application.use_cases.flow._fields._changed_ignored`.
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
