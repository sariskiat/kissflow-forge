"""The intake-family tool module (the 11-dimension AppSpec grilling script,
the spec-to-plan compiler, and the approval gate).

`register(mcp)` wires every intake-family tool onto the new, thin server
(spec G12). One work group -- there is no second group in this family to
keep merge-distance from. Offline for every tool except
`forge_compare_to_spec` (spec D5), which reads a live draft through the flow
port.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from app.application.models.requests.intake.forge_apply_revisions_request import (
    ForgeApplyRevisionsRequest,
)
from app.application.models.requests.intake.forge_approve_spec_request import (
    ForgeApproveSpecRequest,
)
from app.application.models.requests.intake.forge_compare_to_spec_request import (
    ForgeCompareToSpecRequest,
)
from app.application.models.requests.intake.forge_intake_questions_request import (
    ForgeIntakeQuestionsRequest,
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
from app.application.models.requests.intake.kf_plan_field_change_request import (
    KfPlanFieldChangeRequest,
)
from app.application.models.requests.intake.kf_plan_step_visibility_request import (
    KfPlanStepVisibilityRequest,
)
from app.application.models.responses.intake.forge_apply_revisions_response import (
    ForgeApplyRevisionsResponse,
)
from app.application.models.responses.intake.forge_approve_spec_response import (
    ForgeApproveSpecResponse,
)
from app.application.models.responses.intake.forge_compare_to_spec_response import (
    ForgeCompareToSpecResponse,
)
from app.application.models.responses.intake.forge_intake_questions_response import (
    ForgeIntakeQuestionsResponse,
)
from app.application.models.responses.intake.forge_plan_app_response import (
    ForgePlanAppResponse,
)
from app.application.models.responses.intake.forge_request_confirmation_response import (  # noqa: E501
    ForgeRequestConfirmationResponse,
)
from app.application.models.responses.intake.forge_update_spec_response import (
    ForgeUpdateSpecResponse,
)
from app.application.models.responses.intake.kf_plan_field_change_response import (
    KfPlanFieldChangeResponse,
)
from app.application.models.responses.intake.kf_plan_step_visibility_response import (
    KfPlanStepVisibilityResponse,
)
from app.application.use_cases.intake.forge_apply_revisions import (
    ForgeApplyRevisions,
)
from app.application.use_cases.intake.forge_approve_spec import ForgeApproveSpec
from app.application.use_cases.intake.forge_compare_to_spec import (
    ForgeCompareToSpec,
)
from app.application.use_cases.intake.forge_intake_questions import (
    ForgeIntakeQuestions,
)
from app.application.use_cases.intake.forge_plan_app import ForgePlanApp
from app.application.use_cases.intake.forge_request_confirmation import (
    ForgeRequestConfirmation,
)
from app.application.use_cases.intake.forge_update_spec import ForgeUpdateSpec
from app.application.use_cases.intake.kf_plan_field_change import KfPlanFieldChange
from app.application.use_cases.intake.kf_plan_step_visibility import (
    KfPlanStepVisibility,
)
from app.domain.value_objects.kinds import ApprovalDecision, FlowKindArg
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every intake-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_all(mcp)


def _register_all(mcp: FastMCP) -> None:
    """Intake tools: kf_plan_field_change, kf_plan_step_visibility,
    forge_intake_questions, forge_update_spec, forge_request_confirmation,
    forge_apply_revisions, forge_approve_spec, forge_plan_app,
    forge_compare_to_spec.
    """

    @mcp.tool(title="Plan field change", annotations=_shared.OFFLINE_PURE)
    async def kf_plan_field_change(
        draft: dict[str, Any], changes: list[dict[str, Any]], *, ctx: Context
    ) -> KfPlanFieldChangeResponse:
        """DRY-RUN: preview adding fields to a flow's draft graph. Offline; writes nothing.

        Each entry in `changes` is `{"name": ..., "type": <kf_list_field_types value>, "required":
        bool}`; a malformed entry is refused by index, naming its shape and a correct example.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfPlanFieldChangeRequest(
                draft=draft, changes=changes
            ),
            build_use_case=lambda resources: KfPlanFieldChange(),
            needs_kissflow=False,
        )

    @mcp.tool(title="Plan step visibility", annotations=_shared.OFFLINE_PURE)
    async def kf_plan_step_visibility(
        draft: dict[str, Any], owners: dict[str, list[str]], *, ctx: Context
    ) -> KfPlanStepVisibilityResponse:
        """DRY-RUN: preview per-step section visibility. `owners` maps a section NAME to the step names
        that own it. Offline; writes nothing. Show this to a human before kf_set_step_visibility.

        A section or step name that is not in `draft` is refused as DATA here, the same way
        kf_set_step_visibility and forge_set_visibility refuse it — a preview that raises where the
        writer returns an Err is the one place a caller cannot tell "the plan is wrong" from "the tool
        is broken". The refusal names both the offending names and the ones actually available.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: KfPlanStepVisibilityRequest(
                draft=draft, owners=owners
            ),
            build_use_case=lambda resources: KfPlanStepVisibility(),
            needs_kissflow=False,
        )

    @mcp.tool(title="Next intake questions", annotations=_shared.OFFLINE_PURE)
    async def forge_intake_questions(
        spec: dict[str, Any] | None = None, limit: int = 4, *, ctx: Context
    ) -> ForgeIntakeQuestionsResponse:
        """OFFLINE, stateless: the next questions to ask, most-blocking dimension first, for the gaps
        THIS spec still has (app.application.intake.questions.next_questions). `spec=None` returns the OPENING
        questions (app.application.intake.schema.blank_spec() — every one of the 11 dimensions is a gap). Each
        returned question carries its dimension number/name alongside the Thai text/why/example/
        follow-ups `next_questions` itself returns — a caller restricted to MCP has no other way to
        learn which of the 11 dimensions a given question id belongs to. Also returns the spec's
        current gap list (all 11) and blocking-gap list (excludes the advisory timing dimension —
        app.application.intake.schema.ADVISORY_DIMENSIONS) so a caller can tell how much is left without a
        second round trip.

        The echoed `spec` always carries `approved: false`, regardless of what the input spec's was —
        matching forge_update_spec/forge_apply_revisions (both force it too): this tool is a read
        step, never a place `approved` should survive a round trip unexamined. Without this, asking
        "what's left to answer" on an already-approved spec handed back `approved: true` verbatim —
        one more tool a caller could launder that flag through without ever calling
        forge_approve_spec.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeIntakeQuestionsRequest(spec=spec, limit=limit),
            build_use_case=lambda resources: ForgeIntakeQuestions(),
            needs_kissflow=False,
        )

    @mcp.tool(title="Update app spec", annotations=_shared.OFFLINE_PURE)
    async def forge_update_spec(
        spec: dict[str, Any] | None, patch: dict[str, Any], *, ctx: Context
    ) -> ForgeUpdateSpecResponse:
        """OFFLINE, stateless: merge Q&A answers into a spec and return the new spec plus its
        remaining gaps. `spec=None` starts from app.application.intake.schema.blank_spec(). `patch` is a
        SHALLOW merge at AppSpec's own top-level DIMENSION keys (app_name, problem_goal, roles,
        stages, routing, rework_loops, data_model, master_data, visibility, timing, personas,
        test_cases) — each key given REPLACES that whole dimension wholesale; a key omitted from
        `patch` keeps whatever the base spec already had. This is deliberately NOT a deep merge:
        app.application.intake.schema defines no append/upsert-by-name semantics for e.g. "add one more field
        to data_model.fields", so a caller wanting to change one field reads the whole data_model back
        from the returned spec and supplies it again in full — one unambiguous rule beats a guessed-at
        deep merge. The merged result is re-validated through spec_from_dict, so a structurally bad
        patch (unknown key, wrong shape, bad enum value) is refused naming exactly where, never
        silently applied.

        `approved` is NOT a legal patch key: it is the confirmation gate (forge_approve_spec's own
        job), never a spec dimension a Q&A answer can fill in — a patch naming it is refused outright,
        even to re-assert the same value the base spec already has. A caller round-tripping a WHOLE
        spec back through this tool as its own patch (e.g. `spec_to_dict(...)` verbatim) must strip
        that one key first. The returned spec's `approved` is ALSO always forced to False regardless
        of what the base spec's was — updated content is, by definition, unapproved content, even when
        nothing in `patch` touched `approved` at all (this was a live bypass: update a field on an
        ALREADY-approved spec, and the old `approved: true` rode along untouched into a plan built
        from content nobody actually re-confirmed). Call forge_request_confirmation +
        forge_approve_spec again after any update.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeUpdateSpecRequest(spec=spec, patch=patch),
            build_use_case=lambda resources: ForgeUpdateSpec(),
            needs_kissflow=False,
        )

    @mcp.tool(title="Build confirmation pack", annotations=_shared.OFFLINE_ARTIFACT)
    async def forge_request_confirmation(
        spec: dict[str, Any], out_dir: str | None = None, *, ctx: Context
    ) -> ForgeRequestConfirmationResponse:
        """OFFLINE: build the ConfirmationRequest (app.application.design.request_confirmation) — both draw.io
        diagrams plus the HTML mockup bundle written to disk, a content digest that changes whenever
        the spec's content does, and one Thai confirm/revise question per risky choice the spec makes
        (each routing literal, loop gate polarity, terminal state, required field, master-data list's
        values). THE RULE (CLAUDE.md): nothing downstream may write to Kissflow until a human has read
        these artifacts and forge_approve_spec has been called with THIS digest. Also echoes
        `gaps`/`blocking_gaps` — this tool does NOT refuse to build a confirmation package for an
        incomplete spec (a customer may reasonably want to see a partial design mid-interview), but a
        human handed only `design.html` with no other signal would have no way to tell "empty because
        nobody has answered dimension 6 yet" from "empty because the app genuinely has no fields."
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeRequestConfirmationRequest(
                spec=spec, out_dir=out_dir
            ),
            build_use_case=lambda resources: ForgeRequestConfirmation(
                resources.artifacts
            ),
            needs_kissflow=False,
        )

    @mcp.tool(title="Apply spec revisions", annotations=_shared.OFFLINE_PURE)
    async def forge_apply_revisions(
        spec: dict[str, Any], revisions: dict[str, str], *, ctx: Context
    ) -> ForgeApplyRevisionsResponse:
        """OFFLINE: apply a customer's corrections (app.application.design.apply_revisions — an explicit key
        vocabulary, e.g. "stage:<name>:rename" / "list:<name>:value:<old>", never a general
        dotted-path setter) and return the new spec plus its NEW digest (app.application.design.spec_digest —
        ANY revision changes the spec's content, so the digest a customer must approve next is this
        one, never the one they were shown before the revision). The RETURNED spec's `approved` flag
        is ALWAYS forced to False, regardless of what the input spec's was — a revision is, by
        definition, unapproved content, even one applied to an already-approved spec (this used to be
        a live bypass: approve, then revise routing/fields/anything with `approved: true` riding along
        untouched, then plan clean against content nobody actually confirmed).

        Also reports whether the revised spec still compiles, tested against a TEMPORARILY
        force-approved COPY purely to probe structural validity — that probe never affects the
        returned spec's own (always-False) `approved` flag. A KNOWN DEFECT (app.application.design.confirm's
        own docstring) makes `field:<stage>:<name>:rename` return an uncompilable spec whenever that
        field is referenced elsewhere (a routing point, a loop gate, a computed field, a visibility
        entry, or a test case fill) — this is exactly the case `compiles=False` exists to surface, not
        hide. A revision that fails to APPLY (unknown key, or a key naming something not in this spec)
        is a real tool error (`isError=True`); an applied revision that merely fails to compile is NOT
        an error — the tool did what was asked, and is reporting a true fact about the result.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeApplyRevisionsRequest(
                spec=spec, revisions=revisions
            ),
            build_use_case=lambda resources: ForgeApplyRevisions(),
            needs_kissflow=False,
        )

    @mcp.tool(title="Approve spec", annotations=_shared.OFFLINE_PURE)
    async def forge_approve_spec(
        spec: dict[str, Any],
        digest: str,
        decision: ApprovalDecision,
        *,
        ctx: Context,
    ) -> ForgeApproveSpecResponse:
        """OFFLINE: record approval and mint the ONLY value forge_plan_app accepts.

        Refuses unless `digest` matches THIS spec's content digest (app.application.design.spec_digest, with
        `approved` normalized to False before hashing — see _content_digest. EVERY producer of a
        digest normalizes the same way: this tool, forge_plan_app, forge_request_confirmation and
        _artifact_dir. They must stay in lockstep — when they did not, re-approving an already-approved
        spec was refused as "the spec changed" when nothing had, and the error's own suggested remedy
        returned that same rejected digest forever) and `decision` is the exact literal "approve"
        (app.application.design.is_approved — a typo, "Approve", "approved", or a revise request are all
        refused, never guessed into a yes). A stale digest means the spec changed (e.g. via
        forge_apply_revisions) after the customer looked at the confirmation artifacts — refused,
        naming both digests, rather than silently approving content the customer never actually saw.

        Returns the spec with `approved` set True, its plain content `digest` (harmless to expose —
        kept for a caller that just wants to show/detect drift, same meaning forge_request_confirmation/
        forge_apply_revisions already return under that name), AND `approval_token`: an HMAC of that
        digest under a secret generated once per server process (_APPROVAL_SECRET), never logged,
        never returned by any other tool. forge_plan_app now demands `approval_token`, never a plain
        `digest` — a review round proved that ANY tool willing to hash a spec's content (this one
        included, and forge_request_confirmation/forge_apply_revisions besides) mints a value
        indistinguishable from "approved" once a caller flips `approved: true` by hand, since a bare
        digest proves only "this content was hashed once," never that an explicit approve call
        happened for it. Only this function holds the secret, so only a real call here can produce a
        token forge_plan_app accepts — hashing the same bytes anywhere else, however many times,
        cannot forge one.

        HONEST CEILING: this proves "exactly one explicit forge_approve_spec call happened, bound to
        this exact content, and no other route can forge that fact." It does NOT and CANNOT prove a
        HUMAN, rather than the calling agent, made the decision — no stateless MCP surface with no
        out-of-band channel to a person can prove that; `decision` is still just a string an agent
        could type "approve" into itself. The gate closes every route from "content nobody signed off
        on through this call" to a live build — it is not, and cannot be, human authentication.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeApproveSpecRequest(
                spec=spec, digest=digest, decision=decision
            ),
            build_use_case=lambda resources: ForgeApproveSpec(
                resources.approval_secret
            ),
            needs_kissflow=False,
        )

    @mcp.tool(title="Compile build plan", annotations=_shared.OFFLINE_PURE)
    async def forge_plan_app(
        spec: dict[str, Any], approval_token: str, *, ctx: Context
    ) -> ForgePlanAppResponse:
        """OFFLINE: compile an APPROVED, COMPLETE spec to its ordered BuildPlan
        (app.application.intake.compile.compile_spec) — THE GATE.

        Refuses UNLESS `approval_token` is the exact HMAC forge_approve_spec minted for this spec's
        CURRENT content digest (approved normalized to False before hashing — see _content_digest).
        This is deliberately NOT a plain content digest. A review round proved that a content-digest
        gate is forgeable four ways, because ANY tool that hashes the same content mints a value
        indistinguishable from what the gate wants, with no approve call required at all:
          - call forge_request_confirmation (read-only), hand-set `approved: true`, plan with its digest
          - mutate an approved spec's routing/owner_role, RE-confirm the mutant for a fresh matching
            digest, plan the mutant with THAT — the customer approved design A, the plan is A-prime
          - forge_apply_revisions returns a plain digest for its (approved-forced-False) result — flip
            `approved` back to true by hand, plan with that digest
          - same shape through forge_update_spec chained into forge_request_confirmation
        All four share one root cause (a bare digest proves content-equals-content, never "an approve
        call happened") and one fix: only forge_approve_spec holds `_APPROVAL_SECRET`, so only an
        actual call to it can mint a token this check accepts. A caller who never called
        forge_approve_spec, or whose content changed afterward by so much as one field, has no
        token that verifies — refused here, before `compile_spec` ever runs, naming that the spec was
        never approved (or changed since).

        HONEST CEILING: this proves "exactly one explicit forge_approve_spec call happened, bound to
        this exact content, and nothing else can forge that fact." It does NOT and CANNOT prove a
        HUMAN, rather than the calling agent, approved — see forge_approve_spec's own docstring.

        Only past the token check does this refuse a spec whose `approved` flag is not True (call
        forge_approve_spec first), or one with blocking gaps, NAMING every dimension still missing (so
        a caller can go straight back to forge_intake_questions) — compile_spec's own two refusals,
        unchanged, kept as a second (weaker) check: a valid token only proves the CONTENT was approved,
        since the token verification normalizes `approved` away — a caller could in principle present
        approved content with `approved: false` re-set by hand, which the token alone would not catch,
        but compile_spec's own check does. No build may ever start before an explicit approval bound
        to the EXACT design being built (CLAUDE.md "THE RULE").
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgePlanAppRequest(
                spec=spec, approval_token=approval_token
            ),
            build_use_case=lambda resources: ForgePlanApp(resources.approval_secret),
            needs_kissflow=False,
        )

    @mcp.tool(title="Compare build to spec", annotations=_shared.LIVE_READ)
    async def forge_compare_to_spec(
        flow_id: str,
        spec: dict[str, Any],
        kind: FlowKindArg = "process",
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeCompareToSpecResponse:
        """LIVE read-only (dev only, KF_APP): does the BUILT flow match what the INPUT asked for?
        (#16 — fidelity, not referential integrity: forge_doctor said `ok` on a build with wrong
        field types, a missing event, spurious Permissions and a misordered table host). Fetches the
        live draft (THE RULE: judge the read-back, never the plan) and diffs it against the spec:
        field inventory by (name, type, ReferredList), root Model::Row order INCLUDING table hosts,
        Permissions on no-Permission columns, style-chain completeness, event (source, trigger)
        inventory, stages/gateway-conditions/loop-gates. Wire this as its own build-order step after
        doctor — every mismatch is named, known-benign exclusions are declared in `ignored`.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCompareToSpecRequest(
                flow_id=flow_id,
                spec=spec,
                kind=kind,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeCompareToSpec(resources.flow),
        )
