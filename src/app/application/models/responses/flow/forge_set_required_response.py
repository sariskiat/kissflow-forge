"""app.application.models.responses.flow.forge_set_required_response — the DTO for
`forge_set_required`'s result: today's `client.RequiredReport.as_tool_result()`,
minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeSetRequiredResponse(BaseModel):
    """The output-invariant audit of one `forge_set_required` call.

    `cleared` is the SET semantics' own collateral: a root field that was
    Required before this call and was not named in `required` comes back
    optional, reported here rather than changing silently.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    required: list[str]
    verified: list[str]
    missing: list[str]
    cleared: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
