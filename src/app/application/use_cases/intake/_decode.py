"""app.application.use_cases.intake._decode -- the one "spec=None means no
answers yet" rule the two stateless P3 entry points share.

Every OTHER intake tool types its `spec` request field as a real `AppSpec`
directly (Pydantic validates the whole nested shape at request-build time,
replacing the old `app.infrastructure.mcp.server._decode`'s manual
`isinstance`/`AppSpec.model_validate` dance -- the same pattern the design
family's DTOs already use, e.g. `ForgeRenderFlowDiagramRequest.spec:
AppSpec`). `forge_intake_questions`/`forge_update_spec` are the only two P3
tools a caller may legally invoke before any spec exists at all, so their
`spec` field is `AppSpec | None`, and this is the one line that turns that
`None` into the correct starting point.
"""

from __future__ import annotations

from app.application.models.requests.intake.app_spec import AppSpec, blank_spec


def spec_or_blank(spec: AppSpec | None) -> AppSpec:
    """`spec`, or `blank_spec()` when the caller passed none at all.

    Args:
        spec: The request's already-validated spec, or `None`.

    Returns:
        `spec` unchanged, or a fresh `blank_spec()`.
    """
    return blank_spec() if spec is None else spec
