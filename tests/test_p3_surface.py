"""P3 acceptance (Node K): the intake + design MCP tool surface.

Fully offline -- NO live credentials, no network (every P3 tool is a wrapper around
kfforge.intake/kfforge.design, both pure/offline packages):
  1. manifest -- every forge_* P3 tool named in the Node K spec exists on the server module AND
     registers on the real FastMCP object with a buildable schema (fastmcp.Client, in-memory
     transport -- same pattern tests/test_p2_server.py already uses).
  2. the gate -- forge_plan_app refuses unless `approval_token` is the exact HMAC only
     forge_approve_spec can mint for this spec's current content (kfforge.server.
     _mint_approval_token, keyed by a per-process secret no tool ever exposes); refuses an
     unapproved spec and refuses one with blocking gaps, naming them (compile_spec's own two
     refusals, kept as a second, weaker check); forge_approve_spec refuses a stale digest and a
     non-"approve" decision; forge_update_spec refuses to set `approved` via a patch and (like
     forge_apply_revisions and now forge_intake_questions) never echoes `approved: true` back.
  3. GATE REGRESSION, round 2 (B1/B3/B4/B5) -- the four bypasses proved live against the
     approved-flag-only gate are each still refused, now against the token: B1 (hand-crafted
     `approved: true`, forge_approve_spec never called), B3 (rewire routing/owner_role AFTER
     approval, replay the OLD token), B4 (smuggle `approved: true` through forge_update_spec's
     patch), B5 (forge_apply_revisions on an approved spec).
  4. GATE REGRESSION, round 3 (N1/N2/N3/N4) -- ONE root cause: a plain content digest
     (kfforge.design.spec_digest) proves only "this content was hashed once," never that an
     approve call happened, and THREE read-only/content-transform tools compute exactly that
     value. N1 (forge_request_confirmation's digest, `approved` hand-set true, no approve call
     anywhere), N2 (mutate an approved spec, RE-confirm the MUTANT for a fresh matching digest,
     plan the mutant with it -- confirmation never mints a token no matter how fresh), N3
     (forge_apply_revisions' own returned digest, `approved` flipped back by hand), N4 (same shape
     chained through forge_update_spec -> forge_request_confirmation). All four, and both round-2
     survivors, are closed by the SAME fix: forge_plan_app accepts only an HMAC only
     forge_approve_spec can mint, never a plain digest, however it was obtained. The honest path
     (approve, then plan with the approval_token IT returns) still works.
  5. a full stateless round: questions -> update -> render -> confirm -> approve -> plan, driven
     ONLY through the tool functions, ending in a plan whose ops are in the proven order.
  6. forge_apply_revisions surfaces (never hides) the documented field-rename defect.
  7. render/confirm tools write real, non-empty files under the GIVEN out_dir (not just
     somewhere) and echo gaps/blocking_gaps so a design rendered from an incomplete spec still
     carries that signal.

No test in this file recomputes the value a gate demands (an earlier round's `_normalized_digest`
helper did exactly that for forge_plan_app's digest check, and one test built on it ended up
PROVING the very bypass it claimed to refute -- a test must never reimplement the thing under
test; every approval_token used below comes from an actual forge_approve_spec call).

Reuses tests/test_intake.py's `_full_spec()`/`_linear_spec()` fixtures directly (imported, same
pattern tests/test_p2_server.py already uses for `FakeClient`) -- no real-app vocabulary anywhere
in this file (CLAUDE.md BLINDNESS).
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import os
from typing import Any

import pytest
from test_intake import (  # tests/ is on sys.path, see conftest.py
    _full_spec,
    _linear_spec,
)

import kfforge.server as srv
from kfforge.intake.compile import OP_ORDER
from kfforge.intake.schema import AppSpec
from kfforge.intake.serde import spec_from_dict, spec_to_dict

P3_TOOLS = {
    "forge_intake_questions", "forge_update_spec", "forge_render_flow_diagram",
    "forge_render_schema_diagram", "forge_render_mockups", "forge_request_confirmation",
    "forge_apply_revisions", "forge_approve_spec", "forge_plan_app",
}

# Minimal dummy args each P3 tool needs to reach its first real statement -- every render/confirm/
# revise/approve/plan tool takes a `spec` first; a fully-populated, compilable, UNAPPROVED wire
# spec (dict, never the dataclass) so tools that inspect spec CONTENT (not just decode it) have
# something realistic to work with, matching DUMMY_ARGS's role in tests/test_p2_server.py.
_FULL_WIRE = spec_to_dict(_full_spec(approved=False))

DUMMY_ARGS: dict[str, dict[str, Any]] = {
    "forge_intake_questions": {},
    "forge_update_spec": {"spec": None, "patch": {}},
    "forge_render_flow_diagram": {"spec": _FULL_WIRE},
    "forge_render_schema_diagram": {"spec": _FULL_WIRE},
    "forge_render_mockups": {"spec": _FULL_WIRE},
    "forge_request_confirmation": {"spec": _FULL_WIRE},
    "forge_apply_revisions": {"spec": _FULL_WIRE, "revisions": {}},
    "forge_approve_spec": {"spec": _FULL_WIRE, "digest": "x", "decision": "no"},
    "forge_plan_app": {"spec": _FULL_WIRE, "approval_token": "x"},
}


def _patch_from(spec: AppSpec) -> dict[str, Any]:
    """A whole spec's wire form, minus `approved` -- the shape a caller must pass to
    forge_update_spec as a "full-shot" patch, since `approved` is no longer a legal patch key
    (the MEDIUM finding: it is the confirmation gate, not a spec dimension)."""
    wire = spec_to_dict(spec)
    del wire["approved"]
    return wire


def test_dummy_args_cover_every_p3_tool() -> None:
    """Fixture-drift guard, matching tests/test_p2_server.py's own: if a new P3 tool is added,
    this file must know how to probe it."""
    assert set(DUMMY_ARGS) == P3_TOOLS


# ---- 1. manifest ------------------------------------------------------------------------------


def test_server_exposes_every_p3_tool_by_name() -> None:
    found = {name for name in dir(srv) if name.startswith("forge_")}
    missing = P3_TOOLS - found
    assert not missing, f"P3 forge_* tools missing from server module: {missing}"


def test_every_p3_tool_registers_on_the_real_mcp_server_with_a_valid_schema() -> None:
    """In-memory FastMCP Client, exactly tests/test_p2_server.py's own pattern -- proves every P3
    tool's type hints actually build a JSON schema `@mcp.tool()` accepts."""
    from fastmcp import Client

    async def _run() -> set[str]:
        async with Client(srv.mcp) as client:
            tools = await client.list_tools()
        for t in tools:
            if t.name in P3_TOOLS:
                assert t.description, f"{t.name} has no description"
                assert t.inputSchema, f"{t.name} has no input schema"
        return {t.name for t in tools}

    names = asyncio.run(_run())
    missing = P3_TOOLS - names
    assert not missing, f"P3 forge_* tools failed to register on the FastMCP server: {missing}"


def test_every_p3_tool_is_callable_with_dummy_args_and_returns_a_dict() -> None:
    """Every P3 tool, called with its dummy args, returns a structured dict -- never raises, never
    returns something else -- regardless of whether the call itself succeeds or is refused."""
    for name in sorted(P3_TOOLS):
        fn = getattr(srv, name)
        got = fn(**DUMMY_ARGS[name])
        assert isinstance(got, dict), f"{name} must return a dict, got {type(got)}"
        assert "isError" in got, f"{name}'s result must carry isError: {got}"


# ---- 2. malformed spec input never crashes a tool, always a structured isError ----------------


@pytest.mark.parametrize("tool_name", sorted(P3_TOOLS - {"forge_intake_questions"}))
def test_p3_tool_rejects_a_non_dict_spec_gracefully(tool_name: str) -> None:
    fn = getattr(srv, tool_name)
    args = dict(DUMMY_ARGS[tool_name])
    args["spec"] = "not a spec"
    got = fn(**args)
    assert got["isError"] is True
    assert "spec" in got["error"]


def test_forge_intake_questions_accepts_no_spec_at_all() -> None:
    """The one P3 tool where `spec=None` is the documented, legal opening move. Pins the FULL
    dimension sequence (not just that the first question is dimension 1) -- a mutant that hard-
    codes `dimension: 1` for every question passed the earlier, weaker version of this test."""
    got = srv.forge_intake_questions()
    assert got["isError"] is False
    assert len(got["gaps"]) == 11
    ids = [q["id"] for q in got["questions"]]
    assert ids == ["1a", "1b", "2a", "3a"]
    dims = [q["dimension"] for q in got["questions"]]
    assert dims == [1, 1, 2, 3]
    names = [q["dimension_name"] for q in got["questions"]]
    assert names == ["problem/goal", "problem/goal", "roles", "stages"]
    assert got["spec"]["approved"] is False


def test_forge_intake_questions_reports_gaps_for_a_given_spec() -> None:
    linear_wire = spec_to_dict(_linear_spec())
    got = srv.forge_intake_questions(spec=linear_wire, limit=10)
    assert got["isError"] is False
    assert [q["id"] for q in got["questions"]] == ["9a"]  # only the advisory dim is a gap
    # dimension 9, not 1 -- the same drift a hardcoded "always dimension 1" mutant would hide
    assert got["questions"][0]["dimension"] == 9
    assert got["questions"][0]["dimension_name"] == "timing"
    expected_gap = (
        "9. timing: need at least the SLA notes (ADVISORY: an empty Timing "
        "does not block compile_spec — see AppSpec.blocking_gaps and "
        "ADVISORY_DIMENSIONS)"
    )
    assert got["gaps"] == [expected_gap]
    assert got["blocking_gaps"] == []


def test_forge_intake_questions_rejects_a_malformed_spec_dict() -> None:
    bad = spec_to_dict(_full_spec())
    del bad["problem_goal"]
    got = srv.forge_intake_questions(spec=bad)
    assert got["isError"] is True
    assert "problem_goal" in got["error"]


def test_forge_intake_questions_never_echoes_approved_true() -> None:
    """LOW finding: forge_intake_questions used to echo `approved: true` verbatim when the CALLER
    passed an already-approved spec -- inconsistent with forge_update_spec/forge_apply_revisions,
    which both force it False, and one more hop a caller could launder the flag through without
    ever calling forge_approve_spec."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approval = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    assert approval["spec"]["approved"] is True
    got = srv.forge_intake_questions(spec=approval["spec"])
    assert got["isError"] is False
    assert got["spec"]["approved"] is False


# ---- 3. forge_update_spec: shallow top-level merge, re-validated, `approved` off-limits --------


def test_forge_update_spec_starting_from_none_applies_a_patch() -> None:
    full = spec_to_dict(_full_spec())
    patch = {"problem_goal": full["problem_goal"], "roles": full["roles"],
             "stages": full["stages"]}
    got = srv.forge_update_spec(spec=None, patch=patch)
    assert got["isError"] is False
    dims_remaining = {int(g.split(".", 1)[0]) for g in got["gaps"]}
    assert dims_remaining == {4, 5, 6, 7, 8, 9, 10, 11}
    assert got["spec"]["problem_goal"] == full["problem_goal"]


def test_forge_update_spec_is_lossless_round_trip_end_to_end() -> None:
    """dict -> AppSpec -> dict via the tool boundary itself: patching with the COMPLETE fixture
    (minus `approved`, no longer a legal patch key) in one shot reproduces it exactly."""
    full = _full_spec(approved=False)
    got = srv.forge_update_spec(spec=None, patch=_patch_from(full))
    assert got["isError"] is False
    assert got["gaps"] == []
    assert spec_from_dict(got["spec"]) == full


def test_forge_update_spec_patch_replaces_a_whole_dimension_not_merge_within_it() -> None:
    full = spec_to_dict(_full_spec())
    base = srv.forge_update_spec(spec=None, patch=_patch_from(_full_spec()))["spec"]
    assert len(full["roles"]["roles"]) > 1  # fixture sanity: there IS something to shrink
    fewer_roles = {"roles": {"roles": [full["roles"]["roles"][0]]}}
    got = srv.forge_update_spec(spec=base, patch=fewer_roles)
    assert got["isError"] is False
    assert len(got["spec"]["roles"]["roles"]) == 1


def test_forge_update_spec_rejects_a_patch_with_an_unknown_key() -> None:
    got = srv.forge_update_spec(spec=None, patch={"not_a_real_dimension": {}})
    assert got["isError"] is True
    assert "not_a_real_dimension" in got["error"]


def test_forge_update_spec_rejects_a_non_dict_patch() -> None:
    got = srv.forge_update_spec(spec=None, patch="oops")  # type: ignore[arg-type]
    assert got["isError"] is True
    assert "patch" in got["error"]


def test_forge_update_spec_rejects_approved_as_a_patch_key() -> None:
    """MEDIUM finding (round 2): `approved` is the confirmation gate, not a dimension -- refused
    outright, even when the value matches what the base spec already has."""
    got = srv.forge_update_spec(spec=_FULL_WIRE, patch={"approved": False})
    assert got["isError"] is True
    assert "approved" in got["error"]
    assert "confirmation gate" in got["error"]


def test_forge_update_spec_always_forces_approved_false_on_output() -> None:
    """Even when `patch` never mentions `approved` at all, updating an ALREADY-approved base spec
    must not silently carry the flag forward -- new content needs new confirmation."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approval = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    assert approval["spec"]["approved"] is True
    got = srv.forge_update_spec(spec=approval["spec"], patch={"app_name": "Touched"})
    assert got["isError"] is False
    assert got["spec"]["approved"] is False


# ---- 4. render tools write real, non-empty files UNDER the given out_dir, echo gaps ------------


def test_render_flow_diagram_writes_a_file_and_returns_its_xml(tmp_path: Any) -> None:
    got = srv.forge_render_flow_diagram(_FULL_WIRE, out_dir=str(tmp_path))
    assert got["isError"] is False
    assert "<mxGraphModel" in got["xml"]
    assert got["path"].startswith(str(tmp_path)), "out_dir must actually be used, not ignored"
    assert got["path"].endswith("flow_diagram.drawio")
    with open(got["path"], encoding="utf-8") as f:
        on_disk = f.read()
    assert on_disk == got["xml"]
    assert len(on_disk) > 0
    assert got["gaps"] == [] and got["blocking_gaps"] == []  # _FULL_WIRE is complete


def test_render_schema_diagram_writes_a_file_and_returns_its_xml(tmp_path: Any) -> None:
    got = srv.forge_render_schema_diagram(_FULL_WIRE, out_dir=str(tmp_path))
    assert got["isError"] is False
    assert "<mxGraphModel" in got["xml"]
    assert got["path"].startswith(str(tmp_path)), "out_dir must actually be used, not ignored"
    assert got["path"].endswith("schema_diagram.drawio")
    with open(got["path"], encoding="utf-8") as f:
        on_disk = f.read()
    assert on_disk == got["xml"]
    assert len(on_disk) > 0
    assert got["gaps"] == [] and got["blocking_gaps"] == []


def test_render_mockups_writes_a_file_and_returns_its_html(tmp_path: Any) -> None:
    got = srv.forge_render_mockups(_FULL_WIRE, out_dir=str(tmp_path))
    assert got["isError"] is False
    assert "<!doctype html>" in got["html"]
    assert got["path"].startswith(str(tmp_path)), "out_dir must actually be used, not ignored"
    assert got["path"].endswith("mockups.html")
    with open(got["path"], encoding="utf-8") as f:
        on_disk = f.read()
    assert on_disk == got["html"]
    assert len(on_disk) > 0
    # summary is a cheap, agent-readable tl;dr -- not the 22KB of HTML an agent cannot itself read
    assert "5 stage(s)" in got["summary"]
    assert "1 table(s)" in got["summary"]
    assert got["gaps"] == [] and got["blocking_gaps"] == []


def test_render_tools_default_out_dir_when_none_given() -> None:
    """No out_dir supplied -- must still succeed and write somewhere real, not silently no-op."""
    got = srv.forge_render_flow_diagram(_FULL_WIRE)
    assert got["isError"] is False
    assert os.path.exists(got["path"])


def test_rendering_the_same_spec_twice_overwrites_not_accumulates(tmp_path: Any) -> None:
    first = srv.forge_render_flow_diagram(_FULL_WIRE, out_dir=str(tmp_path))
    second = srv.forge_render_flow_diagram(_FULL_WIRE, out_dir=str(tmp_path))
    assert first["path"] == second["path"]


def test_rendering_two_different_specs_never_collide(tmp_path: Any) -> None:
    other_wire = spec_to_dict(_linear_spec())
    a = srv.forge_render_flow_diagram(_FULL_WIRE, out_dir=str(tmp_path))
    b = srv.forge_render_flow_diagram(other_wire, out_dir=str(tmp_path))
    assert a["path"] != b["path"]


def test_render_flow_diagram_on_a_blank_spec_still_signals_the_gaps(tmp_path: Any) -> None:
    """LOW finding, render side: this tool never refuses on gaps (a customer may reasonably want
    to see a partial design mid-interview), but it must not render silently -- gaps/blocking_gaps
    ride along even though the diagram itself renders "successfully" (isError=False)."""
    blank_wire = srv.forge_intake_questions()["spec"]
    got = srv.forge_render_flow_diagram(blank_wire, out_dir=str(tmp_path))
    assert got["isError"] is False
    assert len(got["blocking_gaps"]) == 10
    assert len(got["gaps"]) == 11


# ---- 5. forge_request_confirmation -------------------------------------------------------------


def test_request_confirmation_returns_digest_paths_and_questions(tmp_path: Any) -> None:
    got = srv.forge_request_confirmation(_FULL_WIRE, out_dir=str(tmp_path))
    assert got["isError"] is False
    assert len(got["digest"]) == 64  # sha256 hexdigest
    assert set(got["artifact_paths"]) == {
        "flow_diagram.drawio", "schema_diagram.drawio", "design.html",
    }
    for name, path in got["artifact_paths"].items():
        assert path.startswith(str(tmp_path)), f"{name}: out_dir must actually be used"
        with open(path, encoding="utf-8") as f:
            on_disk = f.read()
        assert len(on_disk) > 0, f"{name} was written zero bytes"
    with open(got["artifact_paths"]["design.html"], encoding="utf-8") as f:
        assert "<!doctype html>" in f.read()
    assert len(got["questions"]) > 0
    assert all(isinstance(q, str) for q in got["questions"])
    assert got["gaps"] == [] and got["blocking_gaps"] == []  # _FULL_WIRE is complete


def test_request_confirmation_digest_changes_when_spec_content_changes(tmp_path: Any) -> None:
    a = srv.forge_request_confirmation(_FULL_WIRE, out_dir=str(tmp_path))
    renamed = {**_FULL_WIRE, "app_name": "A Different Name"}
    b = srv.forge_request_confirmation(renamed, out_dir=str(tmp_path))
    assert a["digest"] != b["digest"]


def test_request_confirmation_on_a_blank_spec_still_signals_the_gaps(tmp_path: Any) -> None:
    """The exact scenario the review caught: forge_request_confirmation(blank_spec) used to
    return isError=False with three artifacts on disk and 10 blocking gaps with nothing in the
    result saying so -- a human handed only design.html would be confirming an empty page."""
    blank_wire = srv.forge_intake_questions()["spec"]
    got = srv.forge_request_confirmation(blank_wire, out_dir=str(tmp_path))
    assert got["isError"] is False  # still renders -- this tool never refuses on gaps
    assert len(got["blocking_gaps"]) == 10
    assert len(got["gaps"]) == 11


# ---- 6. GATE: forge_approve_spec mints the token; refuses a stale digest / bad decision --------


def test_approve_spec_refuses_a_stale_digest() -> None:
    got = srv.forge_approve_spec(_FULL_WIRE, digest="0" * 64, decision="approve")
    assert got["isError"] is True
    assert "stale digest" in got["error"]


def test_approve_spec_refuses_a_decision_that_is_not_the_literal_approve() -> None:
    req = srv.forge_request_confirmation(_FULL_WIRE)
    for bad_decision in ("Approve", "approved", "yes", "revise", ""):
        got = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision=bad_decision)
        assert got["isError"] is True, f"decision {bad_decision!r} must be refused"
        assert "not an explicit approval" in got["error"]


def test_approve_spec_succeeds_and_mints_a_usable_approval_token() -> None:
    req = srv.forge_request_confirmation(_FULL_WIRE)
    got = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    assert got["isError"] is False
    assert got["approved"] is True
    assert got["spec"]["approved"] is True
    assert got["digest"] == req["digest"]  # the plain content digest, unchanged by approval
    assert len(got["approval_token"]) == 64  # HMAC-SHA256 hexdigest
    assert got["approval_token"] != got["digest"]  # a token is NOT just the digest again


def test_approve_spec_reapproving_an_already_approved_spec_with_the_original_digest_succeeds() -> None:
    """MEDIUM finding: forge_approve_spec used to digest the spec AS GIVEN while forge_plan_app
    always normalized `approved` away -- so re-approving an already-approved spec (SAME content,
    just already flagged) minted a digest that did not match the ORIGINAL, unapproved-form digest
    the customer was shown, and was refused as "stale" even though nothing had changed. Both sides
    now normalize identically: the original digest still works, and yields the SAME token."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    first = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    assert first["isError"] is False

    second = srv.forge_approve_spec(first["spec"], digest=req["digest"], decision="approve")
    assert second["isError"] is False, f"re-approval wrongly refused: {second.get('error')}"
    assert second["approval_token"] == first["approval_token"]


# ---- 7. GATE: forge_plan_app refuses an invalid token / unapproved / incomplete, naming gaps ---


def test_plan_app_refuses_an_invalid_approval_token() -> None:
    got = srv.forge_plan_app(_FULL_WIRE, approval_token="0" * 64)
    assert got["isError"] is True
    assert "approval_token" in got["error"]


def test_plan_app_refuses_an_unapproved_spec_even_with_a_genuinely_valid_token() -> None:
    """A REAL approval_token from an actual forge_approve_spec call still does not unlock
    forge_plan_app if the presented spec's own `approved` flag reads False -- token verification
    normalizes `approved` away (so the token alone cannot distinguish true from false here), which
    is exactly why compile_spec's OWN "not approved" check is kept as the second, weaker
    condition. Isolates that check specifically, with no recomputed/faked value anywhere."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approval = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    unset = {**approval["spec"], "approved": False}
    got = srv.forge_plan_app(unset, approval_token=approval["approval_token"])
    assert got["isError"] is True
    assert "approved" in got["error"].lower()


def test_plan_app_refuses_a_spec_with_blocking_gaps_and_names_them() -> None:
    """forge_approve_spec does not itself check completeness -- approving an INCOMPLETE (blank)
    spec succeeds (a legitimate token IS minted), and compile_spec's own blocking-gaps refusal is
    what actually stops the plan, naming every dimension still missing."""
    blank_wire = srv.forge_intake_questions()["spec"]
    req = srv.forge_request_confirmation(blank_wire)
    approval = srv.forge_approve_spec(blank_wire, digest=req["digest"], decision="approve")
    assert approval["isError"] is False  # approve doesn't check completeness

    got = srv.forge_plan_app(approval["spec"], approval_token=approval["approval_token"])
    assert got["isError"] is True
    for dim_text in ("1. problem/goal", "2. roles", "3. stages", "6. data model"):
        assert dim_text in got["error"], f"missing gap {dim_text!r} in: {got['error']}"
    assert "9. timing" not in got["error"]  # advisory dimension never blocks


def test_plan_app_succeeds_on_an_approved_complete_spec() -> None:
    """The honest path, end to end: request confirmation, approve with that digest, plan with the
    approval_token forge_approve_spec returns -- must still work after the gate fix."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approved = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    got = srv.forge_plan_app(approved["spec"], approval_token=approved["approval_token"])
    assert got["isError"] is False
    assert got["op_count"] == len(got["ops"]) > 0
    assert set(got["summary"]) <= set(OP_ORDER)


# ---- 7b. GATE REGRESSION round 2: B1/B3/B4/B5 stay refused against the token -------------------


def test_bypass_b1_hand_crafted_approved_flag_without_approve_spec_is_refused() -> None:
    """B1: setting `approved: true` directly on a spec dict, without ever calling
    forge_approve_spec, must not unlock forge_plan_app -- there is no legitimate token for it."""
    forged = {**_FULL_WIRE, "approved": True}
    got = srv.forge_plan_app(forged, approval_token="not-a-real-token")
    assert got["isError"] is True
    assert "approval_token" in got["error"]


def test_bypass_b3_rewiring_after_approval_is_refused() -> None:
    """B3 -- "the one that matters" per round 2's review: approve a spec, then rewire a routing
    target AND a stage's owner_role directly on the ALREADY-APPROVED dict (never through
    forge_apply_revisions), leaving `approved: true` untouched, then try to plan with the
    ORIGINAL approval_token. Refused -- the token was minted for the OLD content digest, which no
    longer matches the mutated content. (A round-2 version of this test went on to hand
    forge_plan_app a digest recomputed for the MUTANT's own content and asserted that succeeded --
    which was true for the digest-only gate of that round, but pinned the exact bypass this HMAC
    fix exists to close as "working as intended." That assertion is gone; see test_bypass_n2 for
    the correct, stronger claim: not even RE-CONFIRMING the mutant to mint a fresh matching digest
    helps, because forge_request_confirmation never mints a token, only forge_approve_spec does.)
    """
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approval = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    assert approval["isError"] is False

    rewired = copy.deepcopy(approval["spec"])
    rewired["routing"]["points"][0]["route_per_option"] = [
        ["Yes", "Return to Customer"], ["No", "Return to Customer"],
    ]
    rewired["stages"]["stages"][0]["owner_role"] = "Technician"  # was "Front Desk"; both real
    assert rewired["approved"] is True  # the flag itself was never touched by this mutation

    got = srv.forge_plan_app(rewired, approval_token=approval["approval_token"])
    assert got["isError"] is True
    assert "approval_token" in got["error"]


def test_bypass_b4_smuggling_approved_via_update_spec_is_refused() -> None:
    """B4: forge_update_spec(spec, {"approved": True}) must be refused outright."""
    got = srv.forge_update_spec(spec=_FULL_WIRE, patch={"approved": True})
    assert got["isError"] is True
    assert "approved" in got["error"]


def test_bypass_b5_revising_an_approved_spec_forces_it_back_to_unapproved() -> None:
    """B5: forge_apply_revisions on an approved spec used to keep `approved: true` riding along.
    Now: the returned spec is ALWAYS forced back to approved=False, AND (round 3) its returned
    "digest" is a plain content hash, never an approval_token -- planning it with that value fails
    on the token check alone, before compile_spec's own approved-check is even reached."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approval = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")
    assert approval["spec"]["approved"] is True

    got = srv.forge_apply_revisions(approval["spec"], {"app_name": "Revised After Approval"})
    assert got["isError"] is False
    assert got["spec"]["approved"] is False

    plan = srv.forge_plan_app(got["spec"], approval_token=got["digest"])
    assert plan["isError"] is True
    assert "approval_token" in plan["error"]


# ---- 7c. GATE REGRESSION round 3: N1/N2/N3/N4 -- a plain digest is never an approval_token -----


def test_bypass_n1_confirmation_digest_alone_is_not_an_approval_token() -> None:
    """N1: forge_request_confirmation is READ-ONLY and requires no approval at all -- calling it,
    then handing its plain digest to forge_plan_app with `approved` hand-set true, must be
    refused. forge_approve_spec was never called; nobody minted a token for this content."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    forged = {**_FULL_WIRE, "approved": True}
    got = srv.forge_plan_app(forged, approval_token=req["digest"])
    assert got["isError"] is True
    assert "approval_token" in got["error"]


def test_bypass_n2_reconfirming_a_mutated_spec_mints_no_usable_token() -> None:
    """N2 -- the sophisticated version of B3: approve a spec, mutate a routing target AND a
    stage's owner_role on the approved dict, RE-CONFIRM the MUTANT (a read-only call with no
    approval gate of its own) to mint a digest matching the mutant's OWN content, flip `approved`
    back to true, and try to plan with that fresh, genuinely-matching digest. Refused --
    forge_request_confirmation never mints an approval_token, no matter how fresh or how exactly
    its plain digest matches the content handed to it. Only an actual forge_approve_spec call for
    THIS content would; the customer approved design A, and nothing here lets a plan for A-prime
    through."""
    req = srv.forge_request_confirmation(_FULL_WIRE)
    approval = srv.forge_approve_spec(_FULL_WIRE, digest=req["digest"], decision="approve")

    mutant = copy.deepcopy(approval["spec"])
    mutant["routing"]["points"][0]["route_per_option"] = [
        ["Yes", "Return to Customer"], ["No", "Return to Customer"],
    ]
    mutant["stages"]["stages"][0]["owner_role"] = "Technician"
    mutant["approved"] = False  # looks like an ordinary pre-approval spec to forge_request_confirmation

    reconfirm = srv.forge_request_confirmation(mutant)
    assert reconfirm["isError"] is False  # confirmation itself never refuses anything -- read-only

    mutant["approved"] = True  # flipped back by hand, exactly as this bypass requires
    got = srv.forge_plan_app(mutant, approval_token=reconfirm["digest"])
    assert got["isError"] is True
    assert "approval_token" in got["error"]


def test_bypass_n3_apply_revisions_digest_is_not_an_approval_token() -> None:
    """N3: forge_apply_revisions forces `approved` False on its own output and returns a plain
    content digest under the key "digest" (never "approval_token" -- confirmed below). Flipping
    `approved` back to true by hand and handing THAT digest to forge_plan_app must be refused."""
    revised = srv.forge_apply_revisions(_FULL_WIRE, {"app_name": "Revised Via N3"})
    assert revised["isError"] is False
    assert revised["spec"]["approved"] is False
    assert "approval_token" not in revised  # apply_revisions never mints one, only approve does

    flipped = {**revised["spec"], "approved": True}
    got = srv.forge_plan_app(flipped, approval_token=revised["digest"])
    assert got["isError"] is True
    assert "approval_token" in got["error"]


def test_bypass_n4_update_spec_content_confirmed_is_not_an_approval_token() -> None:
    """N4: the same shape as N1, but the content comes from forge_update_spec first (which itself
    returns no digest at all -- confirmed below), chained into forge_request_confirmation to mint
    one. Still refused -- the SOURCE of a plain digest never matters, only whether
    forge_approve_spec minted it for this exact content."""
    updated = srv.forge_update_spec(spec=_FULL_WIRE, patch={"app_name": "Updated Via N4"})
    assert updated["isError"] is False
    assert updated["spec"]["approved"] is False
    assert "digest" not in updated

    confirm = srv.forge_request_confirmation(updated["spec"])
    flipped = {**updated["spec"], "approved": True}
    got = srv.forge_plan_app(flipped, approval_token=confirm["digest"])
    assert got["isError"] is True
    assert "approval_token" in got["error"]


# ---- 8. forge_apply_revisions: reports compilability, surfaces the documented defect ----------


def test_apply_revisions_a_clean_revision_still_compiles_and_changes_the_digest() -> None:
    before_digest = srv.forge_request_confirmation(_FULL_WIRE)["digest"]
    got = srv.forge_apply_revisions(_FULL_WIRE, {"app_name": "Renamed"})
    assert got["isError"] is False
    assert got["compiles"] is True
    assert got["compile_error"] is None
    assert got["spec"]["app_name"] == "Renamed"
    assert got["digest"] != before_digest


def test_apply_revisions_surfaces_the_documented_field_rename_defect() -> None:
    """confirm.py's own docstring: `field:<stage>:<name>:rename` cascades nothing, so renaming a
    field referenced elsewhere (here: a routing point's field_name) returns a spec compile_spec()
    rejects -- this must be REPORTED (compiles=False, a real compile_error), never hidden behind
    isError=False with no other signal."""
    got = srv.forge_apply_revisions(_FULL_WIRE, {"field:Diagnose:Repairable:rename": "Renamed Field"})
    assert got["isError"] is False  # the revision itself was applied successfully
    assert got["compiles"] is False  # but the RESULT is a known-bad spec
    assert got["compile_error"]
    assert "Repairable" in got["compile_error"]
    # the returned spec really does carry the rename -- nothing was rolled back silently
    assert not any(f["name"] == "Repairable" for f in got["spec"]["data_model"]["fields"])
    assert any(f["name"] == "Renamed Field" for f in got["spec"]["data_model"]["fields"])


def test_apply_revisions_leaves_an_already_unapproved_spec_unapproved() -> None:
    got = srv.forge_apply_revisions(_FULL_WIRE, {"app_name": "Still Unapproved"})
    assert got["spec"]["approved"] is False


def test_apply_revisions_rejects_an_unknown_revision_key() -> None:
    got = srv.forge_apply_revisions(_FULL_WIRE, {"not:a:real:key": "x"})
    assert got["isError"] is True
    assert "unknown revision key" in got["error"]


def test_apply_revisions_rejects_a_revision_targeting_something_absent_from_this_spec() -> None:
    got = srv.forge_apply_revisions(_FULL_WIRE, {"stage:Nonexistent Stage:owner_role": "X"})
    assert got["isError"] is True
    assert "Nonexistent Stage" in got["error"]


def test_apply_revisions_rejects_a_non_dict_revisions_argument() -> None:
    got = srv.forge_apply_revisions(_FULL_WIRE, revisions="oops")  # type: ignore[arg-type]
    assert got["isError"] is True
    assert "revisions" in got["error"]


# ---- 9. full stateless round: questions -> update -> render -> confirm -> approve -> plan -----


def test_full_stateless_round_driven_only_through_the_tool_functions(tmp_path: Any) -> None:
    """Every step reads/writes ONLY plain dicts across the tool boundary -- no shared Python
    object, no server-side session -- proving the surface really is stateless end to end."""
    full = _full_spec(approved=False)
    full_wire = spec_to_dict(full)

    # 1. opening questions -- dimension 1 first, nothing answered yet
    opening = srv.forge_intake_questions(limit=2)
    assert opening["isError"] is False
    assert [q["dimension"] for q in opening["questions"]] == [1, 1]

    # 2. update, incrementally, in two calls -- proves real merging, not a pass-through
    step_a = srv.forge_update_spec(spec=None, patch={
        "problem_goal": full_wire["problem_goal"], "roles": full_wire["roles"],
        "stages": full_wire["stages"],
    })
    assert step_a["isError"] is False
    assert set(step_a["blocking_gaps"]) != set()

    remaining_patch = {
        k: v for k, v in full_wire.items()
        if k not in ("problem_goal", "roles", "stages", "approved")  # approved: not a patch key
    }
    step_b = srv.forge_update_spec(spec=step_a["spec"], patch=remaining_patch)
    assert step_b["isError"] is False
    assert step_b["gaps"] == []
    complete_spec = step_b["spec"]

    # sanity: what the tools built really does equal the fixture, dict for dict (full_wire's own
    # approved is already False, matching forge_update_spec's forced output)
    assert complete_spec == full_wire

    # 3. render -- real files, on the complete (still unapproved) spec
    flow = srv.forge_render_flow_diagram(complete_spec, out_dir=str(tmp_path))
    schema = srv.forge_render_schema_diagram(complete_spec, out_dir=str(tmp_path))
    mockups = srv.forge_render_mockups(complete_spec, out_dir=str(tmp_path))
    assert flow["isError"] is False and os.path.exists(flow["path"])
    assert schema["isError"] is False and os.path.exists(schema["path"])
    assert mockups["isError"] is False and os.path.exists(mockups["path"])
    assert flow["gaps"] == [] and schema["gaps"] == [] and mockups["gaps"] == []

    # 4. confirm -- gate check: plan_app must refuse BEFORE approval, even offered its own plain
    # digest as if it were a token (no forge_approve_spec call has happened yet)
    confirmation = srv.forge_request_confirmation(complete_spec, out_dir=str(tmp_path))
    assert confirmation["isError"] is False
    still_unapproved_plan = srv.forge_plan_app(
        complete_spec, approval_token=confirmation["digest"],
    )
    assert still_unapproved_plan["isError"] is True

    # 5. approve -- with the real digest just issued
    approval = srv.forge_approve_spec(
        complete_spec, digest=confirmation["digest"], decision="approve",
    )
    assert approval["isError"] is False
    assert approval["approved"] is True

    # 6. plan -- the gate opens ONLY with the approval_token forge_approve_spec minted, ops come
    # back in the proven order
    plan = srv.forge_plan_app(approval["spec"], approval_token=approval["approval_token"])
    assert plan["isError"] is False
    kinds = [op["kind"] for op in plan["ops"]]
    assert set(kinds) == set(OP_ORDER)
    positions = [OP_ORDER.index(k) for k in kinds]
    assert positions == sorted(positions), "ops must appear in OP_ORDER, never out of sequence"
    assert plan["summary"]["create_process"] == 1
    assert plan["op_count"] == len(plan["ops"]) == 37  # pinned, matches test_intake.py's own count


def test_full_round_reconstructs_an_appspec_equal_to_the_original_fixture(tmp_path: Any) -> None:
    """The other half of "stateless": decoding the FINAL wire spec straight back into a real
    AppSpec (bypassing the tools) must reproduce the ORIGINAL fixture object exactly, proving no
    tool in the chain silently mutated or lost anything along the way."""
    full = _full_spec(approved=False)
    step = srv.forge_update_spec(spec=None, patch=_patch_from(full))
    confirmation = srv.forge_request_confirmation(step["spec"], out_dir=str(tmp_path))
    approval = srv.forge_approve_spec(step["spec"], digest=confirmation["digest"], decision="approve")
    reconstructed = spec_from_dict(approval["spec"])
    assert isinstance(reconstructed, AppSpec)
    assert reconstructed == dataclasses.replace(full, approved=True)
