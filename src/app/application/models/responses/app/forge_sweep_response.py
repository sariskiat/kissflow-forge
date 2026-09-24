"""app.application.models.responses.app.forge_sweep_response — the DTO for
`forge_sweep`'s result: today's `client.run_sweep`'s result dict, with
`isError` replaced by its own negation, `ok` (rule 7, `brief_stage_d_common.md`:
`forge_sweep` is a verdict tool -- it reports its verdict IN the response, since
the call itself worked even when one sub-scope's own read failed). No
`snapshot_version`: a pure read.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeSweepResponse(BaseModel):
    """One discovery sweep's per-scope inventory.

    `results` holds one bucket per requested scope (`{"status":
    "read"|"error"|"skipped", "count", "items", "error"}`, except
    `"flows"`, which nests one such bucket per flow kind) -- a free-form
    audit blob, not itself reshaped into a typed DTO.
    """

    model_config = ConfigDict(frozen=True)

    scope: str
    app_id: str
    results: dict[str, Any]
    ok: bool
