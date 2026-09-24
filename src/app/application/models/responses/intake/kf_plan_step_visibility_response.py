"""app.application.models.responses.intake.kf_plan_step_visibility_response --
the DTO for `kf_plan_step_visibility`'s result.

Today's success dict is free-form: `sections` maps each section name to an
`editable_at` list plus a lowercased tally whose KEY SET varies with which
`Visibility` values actually appear in that section's row (`editable`/
`readonly`/`hidden`, any subset). A fixed-field model cannot reproduce that
without inventing zero-valued keys the old dict never had, so this follows
`brief_stage_d_common.md`'s free-form-result rule (`kf_get_flow_schema`'s own
`RootModel[dict[str, Any]]`) instead.
"""

from __future__ import annotations

from typing import Any

from pydantic import RootModel

KfPlanStepVisibilityResponse = RootModel[dict[str, Any]]
