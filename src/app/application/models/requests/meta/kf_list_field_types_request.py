"""app.application.models.requests.meta.kf_list_field_types_request — the DTO for
`kf_list_field_types`: OFFLINE, read-only, no parameters.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class KfListFieldTypesRequest(BaseModel):
    """One `kf_list_field_types` call. Takes no parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")
