"""Tests for `ForgeUpdateSpec`, ported from `tests/test_p3_surface.py`'s
`forge_update_spec` coverage (Stage D group 8; the tool moved from
`app.infrastructure.mcp.server.forge_update_spec`).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.intake_specs import full_spec

from app.application.exceptions import ApplicationError
from app.application.models.requests.intake.app_spec import AppSpec
from app.application.models.requests.intake.forge_update_spec_request import (
    ForgeUpdateSpecRequest,
)
from app.application.use_cases.intake.forge_update_spec import ForgeUpdateSpec


def _patch_from(spec: AppSpec) -> dict[str, Any]:
    """A whole spec's wire form, minus `approved` -- the shape a caller must
    pass as a "full-shot" patch, since `approved` is no longer a legal patch
    key."""
    wire = spec.model_dump(mode="json")
    del wire["approved"]
    return wire


@pytest.mark.asyncio
async def test_starting_from_none_applies_a_patch() -> None:
    full = full_spec().model_dump(mode="json")
    patch = {
        "problem_goal": full["problem_goal"],
        "roles": full["roles"],
        "stages": full["stages"],
    }
    use_case = ForgeUpdateSpec()
    got = await use_case.execute(ForgeUpdateSpecRequest(spec=None, patch=patch))
    dims_remaining = {int(g.split(".", 1)[0]) for g in got.gaps}
    assert dims_remaining == {4, 5, 6, 7, 8, 9, 10, 11}
    assert got.spec["problem_goal"] == full["problem_goal"]


@pytest.mark.asyncio
async def test_is_lossless_round_trip_end_to_end() -> None:
    """dict -> AppSpec -> dict via the use case itself: patching with the
    COMPLETE fixture (minus `approved`) in one shot reproduces it exactly."""
    full = full_spec(approved=False)
    use_case = ForgeUpdateSpec()
    got = await use_case.execute(
        ForgeUpdateSpecRequest(spec=None, patch=_patch_from(full))
    )
    assert got.gaps == []
    assert AppSpec.model_validate(got.spec) == full


@pytest.mark.asyncio
async def test_patch_replaces_a_whole_dimension_not_merge_within_it() -> None:
    full = full_spec().model_dump(mode="json")
    use_case = ForgeUpdateSpec()
    base = (
        await use_case.execute(
            ForgeUpdateSpecRequest(spec=None, patch=_patch_from(full_spec()))
        )
    ).spec
    assert len(full["roles"]["roles"]) > 1  # fixture sanity
    fewer_roles = {"roles": {"roles": [full["roles"]["roles"][0]]}}
    got = await use_case.execute(ForgeUpdateSpecRequest(spec=base, patch=fewer_roles))
    assert len(got.spec["roles"]["roles"]) == 1


@pytest.mark.asyncio
async def test_rejects_a_patch_with_an_unknown_key() -> None:
    use_case = ForgeUpdateSpec()
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeUpdateSpecRequest(spec=None, patch={"not_a_real_dimension": {}})
        )
    assert exc_info.value.code == "REFUSED"
    assert "not_a_real_dimension" in exc_info.value.message


@pytest.mark.asyncio
async def test_rejects_approved_as_a_patch_key() -> None:
    """MEDIUM finding: `approved` is the confirmation gate, not a
    dimension -- refused outright, even when the value matches what the
    base spec already has."""
    full_wire = full_spec(approved=False).model_dump(mode="json")
    use_case = ForgeUpdateSpec()
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeUpdateSpecRequest(spec=full_wire, patch={"approved": False})
        )
    assert exc_info.value.code == "REFUSED"
    assert "approved" in exc_info.value.message
    assert "confirmation gate" in exc_info.value.message


@pytest.mark.asyncio
async def test_always_forces_approved_false_on_output() -> None:
    """Even when `patch` never mentions `approved` at all, updating an
    ALREADY-approved base spec must not silently carry the flag forward."""
    approved_wire = full_spec(approved=True).model_dump(mode="json")
    use_case = ForgeUpdateSpec()
    got = await use_case.execute(
        ForgeUpdateSpecRequest(spec=approved_wire, patch={"app_name": "Touched"})
    )
    assert got.spec["approved"] is False
