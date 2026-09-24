"""app.application.models.responses.flow.kf_set_step_visibility_response —
the response DTO for `kf_set_step_visibility`.

Same free-form-shape reasoning as `forge_set_visibility_response.py`: this
tool shares the exact same `StepPermissionReport`-shaped result, so it gets
the same `RootModel[dict[str, Any]]` treatment, including rule 7: a pair
that does NOT verify on read-back raises `ApplicationError(code=
VERIFY_FAILED)` instead of returning this DTO, so `pair_counts["missing"]`
is always `0` and `missing` is always `[]` in a returned dict.
"""

from __future__ import annotations

from typing import Any

from pydantic import RootModel


class KfSetStepVisibilityResponse(RootModel[dict[str, Any]]):
    """The result of one `kf_set_step_visibility` call, as the exact dict
    `app.application.use_cases.flow._permissions.write_step_permissions` built
    (plus `snapshot_version`)."""
