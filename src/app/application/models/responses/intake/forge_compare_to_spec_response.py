"""app.application.models.responses.intake.forge_compare_to_spec_response --
the DTO for `forge_compare_to_spec`'s result: today's `CompareReport.
as_tool_result()`, minus `isError`.

`forge_compare_to_spec` is a VERDICT tool (like `forge_doctor`/
`forge_copilot_check`/`forge_sweep`): the call itself either worked or
raised, and `ok` reports the FIDELITY verdict inside a successful response --
the old dict already carried `ok`, so this DTO keeps it (shared-brief
correction: never add a verdict key the old dict did not have, but never
drop one it did).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCompareToSpecResponse(BaseModel):
    """The fidelity verdict: every mismatch, a per-rule checked count, and
    declared known-benign exclusions."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    mismatches: list[str]
    checked: dict[str, int]
    ignored: list[str]
