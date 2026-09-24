"""Tests for `ForgeApproveSpec`, ported from `tests/test_p3_surface.py`'s
section 6 (Stage D group 8; the tool moved from
`app.infrastructure.mcp.server.forge_approve_spec`).

No test here recomputes the value the gate demands -- every digest used
below comes from an actual `ForgeRequestConfirmation` call, matching the old
suite's own discipline (`test_p3_surface.py`'s own module docstring).
"""

from __future__ import annotations

import pytest
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.intake_specs import full_spec

from app.application.exceptions import ApplicationError
from app.application.models.requests.intake.forge_approve_spec_request import (
    ForgeApproveSpecRequest,
)
from app.application.models.requests.intake.forge_request_confirmation_request import (  # noqa: E501
    ForgeRequestConfirmationRequest,
)
from app.application.use_cases.intake.forge_approve_spec import ForgeApproveSpec
from app.application.use_cases.intake.forge_request_confirmation import (
    ForgeRequestConfirmation,
)

_FULL_WIRE = full_spec(approved=False).model_dump(mode="json")
_SECRET = b"a" * 32


async def _confirm(spec=None):
    return await ForgeRequestConfirmation(FakeArtifactWriter()).execute(
        ForgeRequestConfirmationRequest(spec=spec if spec is not None else _FULL_WIRE)
    )


@pytest.mark.asyncio
async def test_refuses_a_stale_digest() -> None:
    use_case = ForgeApproveSpec(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeApproveSpecRequest(
                spec=_FULL_WIRE, digest="0" * 64, decision="approve"
            )
        )
    assert exc_info.value.code == "REFUSED"
    assert "stale digest" in exc_info.value.message


@pytest.mark.asyncio
async def test_succeeds_and_mints_a_usable_approval_token() -> None:
    req = await _confirm()
    use_case = ForgeApproveSpec(_SECRET)
    got = await use_case.execute(
        ForgeApproveSpecRequest(spec=_FULL_WIRE, digest=req.digest, decision="approve")
    )
    assert got.approved is True
    assert got.spec["approved"] is True
    assert got.digest == req.digest  # the plain content digest, unchanged
    assert len(got.approval_token) == 64  # HMAC-SHA256 hexdigest
    assert got.approval_token != got.digest  # not just the digest again


@pytest.mark.asyncio
async def test_reapproving_an_already_approved_spec_with_the_original_digest_succeeds() -> (  # noqa: E501
    None
):
    """MEDIUM finding: the old tool used to digest the spec AS GIVEN while
    `forge_plan_app` always normalized `approved` away -- re-approving an
    already-approved spec with the SAME content minted a mismatched
    digest. Both sides now normalize identically: the original digest
    still works, and yields the SAME token."""
    req = await _confirm()
    use_case = ForgeApproveSpec(_SECRET)
    first = await use_case.execute(
        ForgeApproveSpecRequest(spec=_FULL_WIRE, digest=req.digest, decision="approve")
    )
    second = await use_case.execute(
        ForgeApproveSpecRequest(spec=first.spec, digest=req.digest, decision="approve")
    )
    assert second.approval_token == first.approval_token


@pytest.mark.asyncio
async def test_a_different_process_secret_mints_a_different_token() -> None:
    """The approval_token is bound to the PROCESS secret, not just the
    content -- a restart mints a new secret, and any token from a
    previous process is exactly as stale as a spec that changed."""
    req = await _confirm()
    first = await ForgeApproveSpec(_SECRET).execute(
        ForgeApproveSpecRequest(spec=_FULL_WIRE, digest=req.digest, decision="approve")
    )
    second = await ForgeApproveSpec(b"b" * 32).execute(
        ForgeApproveSpecRequest(spec=_FULL_WIRE, digest=req.digest, decision="approve")
    )
    assert first.approval_token != second.approval_token
