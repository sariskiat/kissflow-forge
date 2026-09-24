"""app.application.models.responses.flow.forge_set_events_response — the
`forge_set_events` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeSetEventsResponse(BaseModel):
    """The output-invariant audit for `forge_set_events`: every requested
    field lands in exactly one of `verified` / `missing`. `unverified`
    separately names any trigger whose `(type -> trigger)` pair is
    family-inferred rather than live-confirmed.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    fields: list[str]
    verified: list[str]
    missing: list[str]
    triggers: list[str]
    derived: list[str]
    unverified: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
