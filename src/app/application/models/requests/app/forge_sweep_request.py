"""app.application.models.requests.app.forge_sweep_request — the DTO for
`forge_sweep` (today's `server.py`, `client.run_sweep`): a read-only,
full-inventory discovery sweep.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import SweepScope


class ForgeSweepRequest(BaseModel):
    """One `forge_sweep` call.

    `scope` is the closed `SweepScope` literal, so an unknown scope fails
    with `ValidationError` before any use case runs -- the old `run_sweep`'s
    own runtime refusal is now this shape check alone (ports
    `tests/test_p4_surface.py::test_sweep_unknown_scope_rejected`). `app_id`
    is already resolved by the tool (see `brief_stage_d_common.md`, "The app
    id").
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: SweepScope
    app_id: str
