"""app.application.models.requests.flow.kf_set_step_visibility_request — the
request DTO for `kf_set_step_visibility`."""

from __future__ import annotations

from pydantic import BaseModel


class KfSetStepVisibilityRequest(BaseModel):
    """One `kf_set_step_visibility` call: rebuild a process's per-step section
    visibility.

    Unlike `forge_set_visibility`, this tool has no `field_owners` and no
    `kind` -- it always targets a `"process"` flow (the older, simpler
    surface `forge_set_visibility` superseded).

    Attributes:
        flow_id: The flow to rebuild visibility on.
        owners: Section name -> the step names that own it.
        publish: Publish the flow once the matrix is written and verified.
        include_pairs: Return every (column, activity) pair in full instead
            of the bounded counts + rollups.
        app_id: The resolved application id. Empty means "no app selected".
    """

    flow_id: str
    owners: dict[str, list[str]]
    publish: bool = False
    include_pairs: bool = False
    app_id: str = ""
