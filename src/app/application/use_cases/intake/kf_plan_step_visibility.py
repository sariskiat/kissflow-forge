"""app.application.use_cases.intake.kf_plan_step_visibility -- preview which
section is Editable/ReadOnly/Hidden at which step.

Ported from `app.application.tools.plan_step_visibility` (Stage D group 8).
"""

from __future__ import annotations

from collections import Counter

from app.application.exceptions import VERIFY_FAILED, ApplicationError
from app.application.models.requests.intake.kf_plan_step_visibility_request import (
    KfPlanStepVisibilityRequest,
)
from app.application.models.responses.intake.kf_plan_step_visibility_response import (
    KfPlanStepVisibilityResponse,
)
from app.domain.entities.flow_draft import FlowDraft, progressive_matrix
from app.domain.value_objects.field_type import Visibility


class KfPlanStepVisibility:
    """Use case behind the `kf_plan_step_visibility` tool. Offline, no ports."""

    async def execute(
        self, request: KfPlanStepVisibilityRequest
    ) -> KfPlanStepVisibilityResponse:
        """Run one `kf_plan_step_visibility` call: dry-run, no writes.

        Args:
            request: The validated request.

        Returns:
            A per-section tally plus the step name each section is editable
            at, and the total Permission-node count the writer would emit.

        Raises:
            ApplicationError: A section or step name in `owners` is not on
                `draft` (`code=VERIFY_FAILED`, the exact `str(exc)` the old
                `Err("verify", str(e))` carried), naming both the
                offending names and the ones actually available.
        """
        try:
            flow = FlowDraft.from_wire(request.draft)
            matrix = progressive_matrix(flow, request.owners)
        except (ValueError, TypeError, KeyError) as exc:
            raise ApplicationError(str(exc), code=VERIFY_FAILED) from exc

        acts = {
            k: v.get("Name", k)
            for k, v in request.draft.items()
            if isinstance(v, dict) and v.get("Kind") == "Activity"
        }
        sections: dict[str, object] = {}
        for section, row in matrix.items():
            tally = Counter(v.value for v in row.values())
            sections[section] = {
                "editable_at": sorted(
                    acts.get(a, a) for a, v in row.items() if v is Visibility.EDITABLE
                ),
                **{k.lower(): c for k, c in tally.items()},
            }

        # the REAL pair count the writer will emit: per matrix row, the section's
        # member columns minus the columns the writer skips (no-Permission columns
        # and table hosts -- #9, Tables). Field-level overrides would add their own
        # rows, but this preview takes no field_matrix, so nothing is subtracted for
        # them. Sharing section_layout with the writer is what keeps this count
        # truthful (it used to count every member column, silently over-reporting
        # by one column x every step whenever a section held a hidden or
        # SequenceNumber column).
        layout = flow.section_layout()
        permission_nodes = sum(
            len(
                [
                    c
                    for c in layout.members.get(
                        layout.section_id_of_name.get(s, ""), ()
                    )
                    if c not in layout.no_permission_columns
                    and c not in layout.table_host_columns
                ]
            )
            * len(r)
            for s, r in matrix.items()
            if s in layout.section_id_of_name
        )
        return KfPlanStepVisibilityResponse(
            {"sections": sections, "permission_nodes": permission_nodes}
        )
