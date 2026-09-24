"""app.application.use_cases.design._artifacts -- the one content digest every P3
tool must agree on.

Moved from `app.infrastructure.mcp.server`'s `_content_digest` (Stage D group 8):
both the design family (`forge_render_flow_diagram`, `forge_render_schema_diagram`,
`forge_render_mockups`) and the intake family (`forge_request_confirmation`,
`forge_approve_spec`, `forge_plan_app`) must hash a spec's content the same way, so
this lives in one place and both families import it (`brief_stage_d_common.md`:
"the intake use cases may import the design private modules").

`content_digest` normalizes `approved` to `False` before hashing
(`spec_digest`, `_confirm.py`) so every producer -- this module, `forge_approve_
spec`, `forge_plan_app`, `forge_request_confirmation` -- agrees on the SAME digest
for the same content regardless of whether the spec handed in happens to carry
`approved: true` already; they must stay in lockstep, or re-approving an
already-approved spec is refused as "the spec changed" when nothing had.

The actual FILE WRITE -- `_artifact_dir`/`_write_artifact` as they used to read --
moved out to the `ArtifactWriter` port (`application/interfaces/artifacts.py`) and
its `FileArtifactWriter` adapter (fix 4, spec G13 Q1): hashing a spec's own content
is pure, but `Path.mkdir`/`Path.write_text` are filesystem access, which belongs in
an adapter, never here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.application.use_cases.design._confirm import spec_digest

if TYPE_CHECKING:
    # A real AppSpec, never intake's own module at runtime (design never imports
    # intake -- see _bundle.py): `.model_copy` is Pydantic-specific, so unlike
    # _diagram.py/_mockup.py/_confirm.py's own duck-typed AppSpecLike functions,
    # this one is typed against the concrete model for `ty check`, exactly as
    # `app.infrastructure.mcp.server`'s own `_content_digest` was.
    from app.application.models.requests.intake.app_spec import AppSpec


def content_digest(spec: AppSpec) -> str:
    """The one content digest every P3 tool must agree on.

    Args:
        spec: The spec to hash.

    Returns:
        `spec_digest` of `spec` with `approved` normalized to `False` first.
    """
    return spec_digest(spec.model_copy(update={"approved": False}))
