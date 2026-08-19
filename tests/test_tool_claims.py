"""Every "X is refused" in a tool DESCRIPTION must be backed by a refusal you can trigger (D10).

A description is the only thing a remote agent reads before it calls a live write tool. Three of
them asserted behavior the code did not have:

  * `kf_plan_step_visibility` / `kf_set_step_visibility` — "a section or step name that is not in
    `draft` is refused as DATA here". `graph.progressive_matrix` SILENTLY DROPPED it: an unknown
    section key matched no Section and never appeared, an unknown step name matched no Activity
    and read as "nobody owns this section", quietly emitting ReadOnly everywhere — on a rebuild
    that deletes every Permission first. FIXED IN THE CODE, not the text: the name feeds a
    DESTRUCTIVE write, so dropping one the caller supplied is a doctrine-2 hole, and a preview
    that silently disagrees with the writer is worse than either.
  * `forge_set_events` — promised SIX refused field types; `types.NO_EVENT_FIELD_TYPES` has FIVE,
    deliberately (Rich text's shape is uncaptured and its inferred shape is Textarea +
    AllowFormatting, which legitimately fires onChange). The CODE is right; the description and
    the client's own refusal message were wrong, and both now name the five and say why the sixth
    is absent.
  * `forge_create_list` — "the spec path refuses to compile them into this tool" for a
    `personal_data` list. `kfforge.intake.compile._op_create_list` emits a `create_list` op for it
    like any other, gated only by prose in that op's own `why`. The gate is real but it is the
    PLAN's, not this tool's, and the description now says so — an agent that believed the old
    sentence would have executed exactly the op the plan gated.

The tests below are the standing guard. `CLAIMS` pairs a description PHRASE with an argument set
that must actually produce the refusal, and `test_every_refusal_claiming_tool_is_accounted_for`
makes sure no future tool can add a refusal claim and stay out of the table.

Everything here is OFFLINE: `_client` is monkeypatched to a FakeClient over the engine's own
synthetic draft, so every refusal is proven to fire BEFORE any PUT (`puts == 0`), which is what
"refused" means in this codebase's voice.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest

import kfforge.server as srv
from synthetic import synthetic_process_draft
from test_client import FakeClient

# --------------------------------------------------------------------------------------------
# The table. Each row: tool -> (a phrase that must appear in the LIVE description,
#                               kwargs that must trigger the refusal,
#                               a fragment the refusal message must name).
# The phrase is load-bearing in both directions: it stops the table drifting away from the text
# it claims to check, and it stops the text quietly losing a promise the code still keeps.
# --------------------------------------------------------------------------------------------
CLAIMS: dict[str, tuple[str, dict[str, Any], str]] = {
    "kf_plan_step_visibility": (
        "is refused as DATA here",
        {"draft": None, "owners": {"NoSuchSection": ["Start"]}},
        "section(s) not on this form",
    ),
    "kf_set_step_visibility": (
        "is refused before any write",
        {"flow_id": "F1", "owners": {"NoSuchSection": ["Start"]}},
        "section(s) not on this form",
    ),
    "forge_set_visibility": (
        "is refused before any write",
        {"flow_id": "F1", "owners": {"Intake": ["No Such Step"]}},
        "step(s) not on this workflow",
    ),
    "forge_set_required": (
        "Unknown names are refused too",
        {"flow_id": "F1", "required": ["NoSuchField"]},
        "no such field(s)",
    ),
    "forge_delete_fields": (
        "Refuses the whole batch if any one name is unknown",
        {"flow_id": "F1", "fields": ["NoSuchField"]},
        "no field named",
    ),
    "forge_rename_fields": (
        "is refused before any write",
        {"flow_id": "F1", "renames": {"Ticket No": "Problem"}},
        "already on this form",
    ),
    "forge_apply_fields": (
        "it is refused here instead, before any write",
        {"flow_id": "F1", "fields": [{"name": "Tier", "type": "Select"}]},
        "referred_list",
    ),
    "forge_add_goto_gate": (
        "rejected offline, before any write",
        {"flow_id": "F1", "target_activity_name": "Assess unit", "field_name": "Ticket No"},
        "not Boolean",
    ),
    "forge_set_events": (
        "the FIVE types this engine refuses outright",
        {"flow_id": "F1", "events": {"Self-help Doc": [[None, "kf.x();"]]}},
        "can never carry an event",
    ),
    "forge_create_flow": (
        "refused loudly before any write",
        {"kind": "case", "name": "Board"},
        "requires extra",
    ),
    "forge_grant_tier": (
        "is refused loudly",
        {"kind": "process", "flow_id": "F1", "role_id": "R1", "tier": "Read-only"},
        "valid",
    ),
    "kf_plan_field_change": (
        "a malformed entry is refused by index",
        {"draft": {}, "changes": [{"name": "x", "type": "Nope"}]},
        "changes[0]['type']",
    ),
    "kf_list_field_types": (
        "a wrong type is refused offline",
        # the claim is ABOUT the four tools whose `type` key it backstops — triggered on one of
        # them, since kf_list_field_types itself takes no arguments to get wrong
        {"__via__": "forge_add_table",
         "flow_id": "F1", "name": "T", "columns": [["SKU", "Nope"]]},
        "columns[0][1]",
    ),
    "forge_update_spec": (
        "a patch naming it is refused outright",
        {"spec": None, "patch": {"approved": True}},
        "approved",
    ),
    "forge_approve_spec": (
        "refused, naming both digests",
        {"spec": "__full__", "digest": "not-the-digest", "decision": "approve"},
        "digest",
    ),
    "forge_plan_app": (
        "refused here, before `compile_spec` ever runs",
        {"spec": "__full__", "approval_token": "forged"},
        "token",
    ),
}

# Tools whose description contains a refusal WORD that is not a claim about this tool's own
# behavior. Each entry states which, because "it's fine" is not a reason.
NOT_A_CLAIM_ABOUT_THIS_TOOL: dict[str, str] = {
    "forge_member_batch":
        "'still leaves the initiator refused' — the PLATFORM refusing a submit, not this tool "
        "refusing an argument",
    "forge_add_member_roles":
        "'member/batch rejects any role NOT scoped to KF_APP' — the write API's own rejection, "
        "which is exactly what this tool exists to avoid provoking",
    "forge_playbook":
        "names the playbook's 'refuse-loudly table' as a document section",
    "forge_render_flow_diagram":
        "a NEGATIVE claim: 'this tool never refuses on an incomplete spec'",
    "forge_request_confirmation":
        "a NEGATIVE claim: 'this tool does NOT refuse to build a confirmation package'",
    "forge_build_page":
        "real refusals (a dangling OpenPopup, a placeholder binding on a load-bearing widget), "
        "but they live in kfforge.pages/pages_live and need a whole page graph to trigger — "
        "already triggered by tests/test_pages_live.py "
        "(test_an_on_click_pointing_at_a_popup_the_op_never_declares_is_refused) and "
        "tests/test_pages.py, not re-staged here",
}

_REFUSAL_WORD = re.compile(r"\b(refus\w+|reject\w+)\b", re.IGNORECASE)


def _listed() -> dict[str, Any]:
    from fastmcp import Client

    async def _run() -> Any:
        async with Client(srv.mcp) as client:
            return await client.list_tools()

    return {t.name: t for t in asyncio.run(_run())}


@pytest.fixture()
def offline_client(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    """A FakeClient over the engine's own synthetic process draft, in place of the live one.

    Every refusal under test is supposed to fire before the first PUT, so the fake's `puts`
    counter IS the assertion — a "refusal" that already wrote is not a refusal.
    """
    fake = FakeClient(synthetic_process_draft())
    monkeypatch.setattr(srv, "_client", lambda app_id=None, require_app=True: fake)
    return fake


def _description(tool_name: str) -> str:
    """The live description with its wrapping collapsed — a claim must not fall out of the table
    just because a line got re-flowed."""
    return " ".join((_listed()[tool_name].description or "").split())


def _call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Materialise the two placeholders the static table cannot hold: a real draft graph, and a
    real, fully-populated AppSpec (the digest/token refusals sit BEHIND spec validation, so a
    stub spec would prove only that the validator works)."""
    from kfforge.intake.serde import spec_to_dict
    from test_intake import _full_spec

    args = dict(args)
    target = args.pop("__via__", tool_name)
    if args.get("draft", "") is None:
        args["draft"] = synthetic_process_draft()
    if args.get("spec") == "__full__":
        args["spec"] = spec_to_dict(_full_spec())
    return getattr(srv, target)(**args)


@pytest.mark.parametrize("tool_name", sorted(CLAIMS))
def test_the_claimed_phrase_is_actually_in_the_live_description(tool_name: str) -> None:
    """Half one: the table may not check a promise the description no longer makes."""
    phrase, _args, _fragment = CLAIMS[tool_name]
    description = _description(tool_name)
    assert phrase in description, (
        f"{tool_name}'s description no longer contains {phrase!r} — either the promise moved "
        f"(update the table) or it was dropped (delete the row)"
    )


@pytest.mark.parametrize("tool_name", sorted(CLAIMS))
def test_every_refusal_claim_is_backed_by_a_refusal_you_can_trigger(
    tool_name: str, offline_client: FakeClient,
) -> None:
    """Half two: the promise is kept, as DATA (doctrine 7), naming what was wrong."""
    _phrase, args, fragment = CLAIMS[tool_name]
    got = _call(tool_name, args)
    assert isinstance(got, dict), f"{tool_name} returned {type(got).__name__}, not data"
    assert got.get("isError") is True, f"{tool_name} did not refuse: {got}"
    assert fragment in got.get("error", ""), (
        f"{tool_name} refused, but not for the claimed reason — wanted {fragment!r}, got "
        f"{got.get('error')!r}"
    )


@pytest.mark.parametrize("tool_name", sorted(CLAIMS))
def test_a_refusal_never_writes_first(tool_name: str, offline_client: FakeClient) -> None:
    """"Refused" in this codebase's voice means BEFORE any write. A tool that refuses after a PUT
    has already changed the tenant, which is the opposite of what the word promises."""
    _phrase, args, _fragment = CLAIMS[tool_name]
    _call(tool_name, args)
    assert offline_client.puts == 0, f"{tool_name} wrote {offline_client.puts} time(s) then refused"


def test_every_refusal_claiming_tool_is_accounted_for() -> None:
    """The drift guard. A new tool cannot add "X is refused" to its description and stay out of
    both the table and the explicitly-reasoned exemption list."""
    claiming = {name for name, t in _listed().items()
                if _REFUSAL_WORD.search(t.description or "")}
    unaccounted = sorted(claiming - set(CLAIMS) - set(NOT_A_CLAIM_ABOUT_THIS_TOOL))
    assert not unaccounted, (
        f"{unaccounted} claim a refusal in their description with nothing proving it — add a "
        f"triggering row to CLAIMS, or an entry to NOT_A_CLAIM_ABOUT_THIS_TOOL saying which "
        f"occurrence it is and why"
    )


def test_neither_list_carries_a_stale_entry() -> None:
    """The back edge: a tool that dropped its refusal claim (or was deleted) must leave both
    lists, or they stop describing anything."""
    listed = _listed()
    for table, label in ((CLAIMS, "CLAIMS"), (NOT_A_CLAIM_ABOUT_THIS_TOOL,
                                              "NOT_A_CLAIM_ABOUT_THIS_TOOL")):
        stale = sorted(name for name in table
                       if name not in listed
                       or not _REFUSAL_WORD.search(listed[name].description or ""))
        assert not stale, f"{stale} no longer claim a refusal — drop them from {label}"


def test_forge_set_events_names_five_types_not_six() -> None:
    """(b) pinned on both surfaces at once: the description and the refusal message must agree
    with `types.NO_EVENT_FIELD_TYPES`, and must say why the platform's sixth is not in it."""
    from kfforge.types import NO_EVENT_FIELD_TYPES

    assert len(NO_EVENT_FIELD_TYPES) == 5 and "Rich text" not in NO_EVENT_FIELD_TYPES
    description = _description("forge_set_events")
    assert "FIVE types this engine refuses outright" in description
    assert "Rich text" in description and "does NOT" in description
    for wire_type in sorted(NO_EVENT_FIELD_TYPES):
        assert wire_type in description, f"{wire_type} is refused but not named"


def test_the_events_refusal_message_reads_the_engine_set_rather_than_restating_it(
    offline_client: FakeClient,
) -> None:
    """The message used to hard-code the same wrong six. It now prints the real frozenset, so it
    cannot drift from the code it describes."""
    from kfforge.types import NO_EVENT_FIELD_TYPES

    err = srv.forge_set_events(flow_id="F1",
                               events={"Self-help Doc": [[None, "kf.x();"]]})["error"]
    for wire_type in sorted(NO_EVENT_FIELD_TYPES):
        assert wire_type in err, f"{wire_type} missing from the refusal: {err}"
    assert "Rich text" in err and "uncaptured" in err


def test_forge_create_list_no_longer_claims_a_gate_the_compiler_does_not_have() -> None:
    """(c): `_op_create_list` emits a create_list op for a personal_data list like any other. The
    gate is the op's own `why`, and the description must point at THAT, not at a refusal."""
    import dataclasses as dc

    from kfforge.intake.compile import compile_spec

    description = _description("forge_create_list")
    assert "the spec path refuses to compile" not in description
    assert "HUMAN-GATED" in description and "`why`" in description

    from test_intake import _full_spec

    full = _full_spec()
    flagged = tuple(dc.replace(lst, personal_data=(lst.name == "Urgency Levels"))
                    for lst in full.master_data.lists)
    plan = compile_spec(dc.replace(full,
                                   master_data=dc.replace(full.master_data, lists=flagged)))
    op = next(o for o in plan.ops if o.kind == "create_list"
              and o.args["name"] == "Urgency Levels")
    assert op.args["personal_data"] is True
    assert "HUMAN-GATED" in op.why, "the op's `why` IS the gate the description now names"
