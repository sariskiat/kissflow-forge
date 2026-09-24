"""app.application.use_cases.intake.kf_plan_field_change -- preview adding fields
to a flow's draft graph.

Ported from `app.application.tools.plan_field_change` / `app.application.engine.
plan_change` (Stage D group 8).
"""

from __future__ import annotations

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.models.requests.intake.kf_plan_field_change_request import (
    KfPlanFieldChangeRequest,
)
from app.application.models.responses.intake.kf_plan_field_change_response import (
    AddedField,
    EditedField,
    KfPlanFieldChangeResponse,
)
from app.application.use_cases.intake._engine import plan_change
from app.application.use_cases.intake._field_change import to_field_spec
from app.domain.value_objects.field_type import FieldType


class KfPlanFieldChange:
    """Use case behind the `kf_plan_field_change` tool. Offline, no ports."""

    async def execute(
        self, request: KfPlanFieldChangeRequest
    ) -> KfPlanFieldChangeResponse:
        """Run one `kf_plan_field_change` call: dry-run, no writes.

        Args:
            request: The validated request.

        Returns:
            The adds/edits/skipped preview, plus a human-readable summary.

        Raises:
            ApplicationError: The offline plan was rejected -- an
                unsupported edit, or a shape `plan_change` itself refuses
                (`code=VERIFY_FAILED`, the exact `str(exc)` the old
                `Err("verify", str(e))` carried).
        """
        specs = [to_field_spec(entry) for entry in request.changes]
        try:
            diff = plan_change(request.draft, specs)
        except (ValueError, TypeError, KeyError) as exc:
            raise ApplicationError(str(exc), code=VERIFY_FAILED) from exc
        return KfPlanFieldChangeResponse(
            adds=[
                AddedField(
                    name=s.name, type=FieldType(s.type).value, required=s.required
                )
                for s in diff.adds
            ],
            edits=[EditedField(name=s.name) for s in diff.edits],
            skipped=list(diff.skipped),
            human_readable=diff.human_readable,
        )
