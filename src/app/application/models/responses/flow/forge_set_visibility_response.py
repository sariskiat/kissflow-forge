"""app.application.models.responses.flow.forge_set_visibility_response — the
response DTO for `forge_set_visibility`.

`StepPermissionReport.as_tool_result()` returns a shape that varies with the
`include_pairs` argument: the `pairs` and `collateral` keys only appear when
`include_pairs=True`, and the `note` key is always present but its text
depends on `include_pairs`. A fixed-field `BaseModel` cannot
represent "this key is sometimes absent" without also changing the shape (a
`None` field still dumps as a present `null` key), so this DTO is a
`RootModel[dict[str, Any]]`, per the shared brief's rule for a free-form
result whose shape must not change. `snapshot_version` is folded into the
dict itself before it reaches this model (see
`app.application.use_cases.flow.forge_set_visibility`), not added as a
separate field. A pair that does NOT verify on read-back is a failure (the
shared brief's rule 7): the use case raises `ApplicationError(code=
VERIFY_FAILED)` instead of returning this DTO, so `pair_counts["missing"]`
is always `0` and `missing` is always `[]` in a returned dict.
"""

from __future__ import annotations

from typing import Any

from pydantic import RootModel


class ForgeSetVisibilityResponse(RootModel[dict[str, Any]]):
    """The result of one `forge_set_visibility` call, as the exact dict
    `app.application.use_cases.flow._permissions.write_step_permissions` built
    (plus `snapshot_version`)."""
