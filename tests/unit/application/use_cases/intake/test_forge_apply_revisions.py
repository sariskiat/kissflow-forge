"""Tests for `ForgeApplyRevisions`, ported from `tests/test_p3_surface.py`'s
`forge_apply_revisions` coverage (Stage D group 8; the tool moved from
`app.infrastructure.mcp.server.forge_apply_revisions`).
"""

from __future__ import annotations

import pytest
from tests.fakes.intake_specs import full_spec

from app.application.exceptions import ApplicationError
from app.application.models.requests.intake.forge_apply_revisions_request import (
    ForgeApplyRevisionsRequest,
)
from app.application.use_cases.intake.forge_apply_revisions import (
    ForgeApplyRevisions,
)

_FULL_WIRE = full_spec(approved=False).model_dump(mode="json")


@pytest.mark.asyncio
async def test_a_clean_revision_still_compiles_and_changes_the_digest() -> None:
    use_case = ForgeApplyRevisions()
    before = await use_case.execute(
        ForgeApplyRevisionsRequest(spec=_FULL_WIRE, revisions={})
    )
    got = await use_case.execute(
        ForgeApplyRevisionsRequest(spec=_FULL_WIRE, revisions={"app_name": "Renamed"})
    )
    assert got.compiles is True
    assert got.compile_error is None
    assert got.spec["app_name"] == "Renamed"
    assert got.digest != before.digest


@pytest.mark.asyncio
async def test_surfaces_the_documented_field_rename_defect() -> None:
    """`_confirm.py`'s own docstring: `field:<stage>:<name>:rename` cascades
    nothing, so renaming a field referenced elsewhere (here: a routing
    point's field_name) returns a spec `compile_spec()` rejects -- this
    must be REPORTED (`compiles=False`, a real `compile_error`), never
    hidden."""
    use_case = ForgeApplyRevisions()
    got = await use_case.execute(
        ForgeApplyRevisionsRequest(
            spec=_FULL_WIRE,
            revisions={"field:Diagnose:Repairable:rename": "Renamed Field"},
        )
    )
    assert got.compiles is False
    assert got.compile_error
    assert "Repairable" in got.compile_error
    assert not any(f["name"] == "Repairable" for f in got.spec["data_model"]["fields"])
    assert any(f["name"] == "Renamed Field" for f in got.spec["data_model"]["fields"])


@pytest.mark.asyncio
async def test_leaves_an_already_unapproved_spec_unapproved() -> None:
    use_case = ForgeApplyRevisions()
    got = await use_case.execute(
        ForgeApplyRevisionsRequest(
            spec=_FULL_WIRE, revisions={"app_name": "Still Unapproved"}
        )
    )
    assert got.spec["approved"] is False


@pytest.mark.asyncio
async def test_rejects_an_unknown_revision_key() -> None:
    use_case = ForgeApplyRevisions()
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeApplyRevisionsRequest(
                spec=_FULL_WIRE, revisions={"not:a:real:key": "x"}
            )
        )
    assert exc_info.value.code == "REFUSED"
    assert "unknown revision key" in exc_info.value.message


@pytest.mark.asyncio
async def test_rejects_a_revision_targeting_something_absent_from_this_spec() -> None:
    use_case = ForgeApplyRevisions()
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeApplyRevisionsRequest(
                spec=_FULL_WIRE,
                revisions={"stage:Nonexistent Stage:owner_role": "X"},
            )
        )
    assert exc_info.value.code == "REFUSED"
    assert "Nonexistent Stage" in exc_info.value.message


@pytest.mark.asyncio
async def test_forces_approved_false_even_when_revising_an_approved_spec() -> None:
    """B5: `forge_apply_revisions` on an approved spec used to keep
    `approved: true` riding along."""
    approved_wire = full_spec(approved=True).model_dump(mode="json")
    use_case = ForgeApplyRevisions()
    got = await use_case.execute(
        ForgeApplyRevisionsRequest(
            spec=approved_wire, revisions={"app_name": "Revised After Approval"}
        )
    )
    assert got.spec["approved"] is False
