"""app.application.models.responses.item.forge_simulate_case_response — the
`forge_simulate_case` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeSimulateCaseResponse(BaseModel):
    """The output-invariant audit for `forge_simulate_case`: every planned
    step lands in exactly one of `advanced` / `rejected` / `failed` (the one
    it stopped at) -- `failed` is always empty on a returned response (rule
    7, `brief_stage_d_common.md`): a walk that stopped partway is a raised
    `ApplicationError`, not a "successful" response the caller has to
    inspect for `failed`.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    iid: str | None
    created: bool
    planned: list[str]
    filled: list[str]
    advanced: list[str]
    rejected: list[str]
    failed: list[str]
    error: str | None
    snapshot_version: str | None = None
