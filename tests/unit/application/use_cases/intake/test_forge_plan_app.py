"""Tests for `ForgePlanApp`, ported from `tests/test_p3_surface.py`'s
sections 7/7b/7c (Stage D group 8; the tool moved from
`app.infrastructure.mcp.server.forge_plan_app`). This is THE GATE: no build
may start before an explicit approval bound to the exact design being built.

GATE REGRESSION round 2 (B1/B3/B4/B5) -- the four bypasses proved live
against the approved-flag-only gate are each still refused, now against the
token. GATE REGRESSION round 3 (N1/N2/N3/N4) -- ONE root cause: a plain
content digest proves only "this content was hashed once," never that an
approve call happened, and three read-only/content-transform tools compute
exactly that value.

No test here recomputes the value the gate demands -- every approval_token
used below comes from an actual `ForgeApproveSpec` call.
"""

from __future__ import annotations

import copy

import pytest
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.intake_specs import full_spec

from app.application.exceptions import ApplicationError
from app.application.models.requests.intake.forge_apply_revisions_request import (
    ForgeApplyRevisionsRequest,
)
from app.application.models.requests.intake.forge_approve_spec_request import (
    ForgeApproveSpecRequest,
)
from app.application.models.requests.intake.forge_plan_app_request import (
    ForgePlanAppRequest,
)
from app.application.models.requests.intake.forge_request_confirmation_request import (  # noqa: E501
    ForgeRequestConfirmationRequest,
)
from app.application.models.requests.intake.forge_update_spec_request import (
    ForgeUpdateSpecRequest,
)
from app.application.use_cases.intake._compile import OP_ORDER
from app.application.use_cases.intake.forge_apply_revisions import (
    ForgeApplyRevisions,
)
from app.application.use_cases.intake.forge_approve_spec import ForgeApproveSpec
from app.application.use_cases.intake.forge_plan_app import ForgePlanApp
from app.application.use_cases.intake.forge_request_confirmation import (
    ForgeRequestConfirmation,
)
from app.application.use_cases.intake.forge_update_spec import ForgeUpdateSpec

_FULL_WIRE = full_spec(approved=False).model_dump(mode="json")
_SECRET = b"a" * 32


async def _confirm(spec: dict | None = None):
    return await ForgeRequestConfirmation(FakeArtifactWriter()).execute(
        ForgeRequestConfirmationRequest(spec=spec if spec is not None else _FULL_WIRE)
    )


async def _approve(spec: dict, digest: str):
    return await ForgeApproveSpec(_SECRET).execute(
        ForgeApproveSpecRequest(spec=spec, digest=digest, decision="approve")
    )


# ---- 7. GATE: refuses an invalid token / unapproved / incomplete, naming gaps --------


@pytest.mark.asyncio
async def test_refuses_an_invalid_approval_token() -> None:
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=_FULL_WIRE, approval_token="0" * 64)
        )
    assert exc_info.value.code == "REFUSED"
    assert "approval_token" in exc_info.value.message


@pytest.mark.asyncio
async def test_refuses_an_unapproved_spec_even_with_a_genuinely_valid_token() -> None:
    """A REAL approval_token from an actual approve call still does not
    unlock `forge_plan_app` if the presented spec's own `approved` flag
    reads False -- token verification normalizes `approved` away, which is
    exactly why `compile_spec`'s OWN "not approved" check is kept as the
    second, weaker condition."""
    req = await _confirm()
    approval = await _approve(_FULL_WIRE, req.digest)
    unset = {**approval.spec, "approved": False}
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=unset, approval_token=approval.approval_token)
        )
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "approved" in exc_info.value.message.lower()


@pytest.mark.asyncio
async def test_refuses_a_spec_with_blocking_gaps_and_names_them() -> None:
    """`forge_approve_spec` does not itself check completeness -- approving
    an INCOMPLETE (blank) spec succeeds, and `compile_spec`'s own
    blocking-gaps refusal is what actually stops the plan."""
    blank_result = await ForgeUpdateSpec().execute(
        ForgeUpdateSpecRequest(spec=None, patch={})
    )
    blank = blank_result.spec
    req = await _confirm(blank)
    approval = await _approve(blank, req.digest)

    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(
                spec=approval.spec, approval_token=approval.approval_token
            )
        )
    assert exc_info.value.code == "VERIFY_FAILED"
    for dim_text in ("1. problem/goal", "2. roles", "3. stages", "6. data model"):
        assert dim_text in exc_info.value.message
    assert "9. timing" not in exc_info.value.message  # advisory, never blocks


@pytest.mark.asyncio
async def test_succeeds_on_an_approved_complete_spec() -> None:
    """The honest path, end to end."""
    req = await _confirm()
    approved = await _approve(_FULL_WIRE, req.digest)
    use_case = ForgePlanApp(_SECRET)
    got = await use_case.execute(
        ForgePlanAppRequest(spec=approved.spec, approval_token=approved.approval_token)
    )
    kinds = [op.kind for op in got.ops]
    assert set(kinds) == set(OP_ORDER)
    positions = [OP_ORDER.index(k) for k in kinds]
    assert positions == sorted(positions), (
        "ops must appear in OP_ORDER, never out of sequence"
    )
    # pinned, matches test__compile.py's own count
    assert got.op_count == len(got.ops) == 39
    assert set(got.summary) <= set(OP_ORDER)


# ---- 7b. GATE REGRESSION round 2: B1/B3/B4/B5 stay refused against the token ---------


@pytest.mark.asyncio
async def test_bypass_b1_hand_crafted_approved_flag_without_approve_is_refused() -> (
    None
):
    """B1: setting `approved: true` directly on a spec dict, without ever
    calling `forge_approve_spec`, must not unlock `forge_plan_app` -- there
    is no legitimate token for it."""
    forged = {**_FULL_WIRE, "approved": True}
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=forged, approval_token="not-a-real-token")
        )
    assert "approval_token" in exc_info.value.message


@pytest.mark.asyncio
async def test_bypass_b3_rewiring_after_approval_is_refused() -> None:
    """B3: approve a spec, then rewire a routing target AND a stage's
    owner_role directly on the ALREADY-APPROVED dict, leaving `approved:
    true` untouched, then try to plan with the ORIGINAL approval_token.
    Refused -- the token was minted for the OLD content digest, which no
    longer matches the mutated content."""
    req = await _confirm()
    approval = await _approve(_FULL_WIRE, req.digest)

    rewired = copy.deepcopy(approval.spec)
    rewired["routing"]["points"][0]["route_per_option"] = [
        ["Yes", ["Return to Customer"]],
        ["No", ["Return to Customer"]],
    ]
    rewired["stages"]["stages"][0]["owner_role"] = "Technician"  # was "Front Desk"
    assert rewired["approved"] is True  # the flag itself was never touched

    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=rewired, approval_token=approval.approval_token)
        )
    assert "approval_token" in exc_info.value.message


@pytest.mark.asyncio
async def test_bypass_b4_smuggling_approved_via_update_spec_is_refused() -> None:
    """B4: `forge_update_spec(spec, {"approved": True})` must be refused
    outright (ported at DTO/use-case level of `forge_update_spec` itself --
    see `test_forge_update_spec.py::test_rejects_approved_as_a_patch_key`).
    This test proves the CONSEQUENCE for `forge_plan_app`: since that patch
    is refused before it ever lands, no spec smuggled through it exists."""
    use_case = ForgeUpdateSpec()
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgeUpdateSpecRequest(spec=_FULL_WIRE, patch={"approved": True})
        )
    assert "approved" in exc_info.value.message


@pytest.mark.asyncio
async def test_bypass_b5_revising_an_approved_spec_forces_it_back_to_unapproved() -> (
    None
):
    """B5: `forge_apply_revisions` on an approved spec used to keep
    `approved: true` riding along. Now: the returned spec is ALWAYS forced
    back to `approved=False`, and its returned "digest" is a plain content
    hash, never an approval_token -- planning it with that value fails on
    the token check alone, before `compile_spec`'s own approved-check is
    even reached."""
    req = await _confirm()
    approval = await _approve(_FULL_WIRE, req.digest)
    assert approval.spec["approved"] is True

    revised = await ForgeApplyRevisions().execute(
        ForgeApplyRevisionsRequest(
            spec=approval.spec, revisions={"app_name": "Revised After Approval"}
        )
    )
    assert revised.spec["approved"] is False

    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=revised.spec, approval_token=revised.digest)
        )
    assert "approval_token" in exc_info.value.message


# ---- 7c. GATE REGRESSION round 3: N1/N2/N3/N4 -- a plain digest is never a token -----


@pytest.mark.asyncio
async def test_bypass_n1_confirmation_digest_alone_is_not_an_approval_token() -> None:
    """N1: `forge_request_confirmation` is READ-ONLY and requires no
    approval at all -- calling it, then handing its plain digest to
    `forge_plan_app` with `approved` hand-set true, must be refused."""
    req = await _confirm()
    forged = {**_FULL_WIRE, "approved": True}
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=forged, approval_token=req.digest)
        )
    assert "approval_token" in exc_info.value.message


@pytest.mark.asyncio
async def test_bypass_n2_reconfirming_a_mutated_spec_mints_no_usable_token() -> None:
    """N2 -- the sophisticated version of B3: approve a spec, mutate a
    routing target AND a stage's owner_role on the approved dict,
    RE-CONFIRM the MUTANT (a read-only call with no approval gate of its
    own) to mint a digest matching the mutant's OWN content, flip
    `approved` back to true, and try to plan with that fresh,
    genuinely-matching digest. Refused -- `forge_request_confirmation`
    never mints an approval_token, no matter how fresh or how exactly its
    plain digest matches the content handed to it."""
    req = await _confirm()
    approval = await _approve(_FULL_WIRE, req.digest)

    mutant = copy.deepcopy(approval.spec)
    mutant["routing"]["points"][0]["route_per_option"] = [
        ["Yes", ["Return to Customer"]],
        ["No", ["Return to Customer"]],
    ]
    mutant["stages"]["stages"][0]["owner_role"] = "Technician"
    mutant["approved"] = False  # looks like an ordinary pre-approval spec

    reconfirm = await _confirm(mutant)

    mutant["approved"] = True  # flipped back by hand
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=mutant, approval_token=reconfirm.digest)
        )
    assert "approval_token" in exc_info.value.message


@pytest.mark.asyncio
async def test_bypass_n3_apply_revisions_digest_is_not_an_approval_token() -> None:
    """N3: `forge_apply_revisions` forces `approved` False on its own
    output and returns a plain content digest under the key "digest"
    (never an approval_token). Flipping `approved` back to true by hand and
    handing THAT digest to `forge_plan_app` must be refused."""
    revised = await ForgeApplyRevisions().execute(
        ForgeApplyRevisionsRequest(
            spec=_FULL_WIRE, revisions={"app_name": "Revised Via N3"}
        )
    )
    assert revised.spec["approved"] is False

    flipped = {**revised.spec, "approved": True}
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=flipped, approval_token=revised.digest)
        )
    assert "approval_token" in exc_info.value.message


@pytest.mark.asyncio
async def test_bypass_n4_update_spec_content_confirmed_is_not_an_approval_token() -> (
    None
):
    """N4: the same shape as N1, but the content comes from
    `forge_update_spec` first (which itself returns no digest at all),
    chained into `forge_request_confirmation` to mint one. Still refused --
    the SOURCE of a plain digest never matters, only whether
    `forge_approve_spec` minted it for this exact content."""
    updated = await ForgeUpdateSpec().execute(
        ForgeUpdateSpecRequest(spec=_FULL_WIRE, patch={"app_name": "Updated Via N4"})
    )
    assert updated.spec["approved"] is False

    confirm = await _confirm(updated.spec)
    flipped = {**updated.spec, "approved": True}
    use_case = ForgePlanApp(_SECRET)
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(
            ForgePlanAppRequest(spec=flipped, approval_token=confirm.digest)
        )
    assert "approval_token" in exc_info.value.message
