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
    `personal_data` list. `app.application.intake.compile._op_create_list` emits a `create_list` op for it
    like any other, gated only by prose in that op's own `why`. The gate is real but it is the
    PLAN's, not this tool's, and the description now says so — an agent that believed the old
    sentence would have executed exactly the op the plan gated.

The tests below are the standing guard. `CLAIMS` pairs a description PHRASE with an argument set
that must actually produce the refusal, and `test_every_refusal_claiming_tool_is_accounted_for`
makes sure no future tool can add a refusal claim and stay out of the table.

Stage E switch: every tool call below goes through `create_server(lifespan)` and an in-process
`fastmcp.Client` (the old plain-function calls `getattr(srv, name)(**kwargs)` and the monolithic
`FakeClient` are both gone with the rest of `app.infrastructure.mcp.server`'s module-level `mcp`
and `app.infrastructure.kissflow.client`). `offline_resources` wires one `FakeFlowRepository`/
`FakeAppRepository` pair, primed with the engine's own synthetic process draft, shared by every
family's use case the table exercises; every refusal under test is still supposed to fire before
the first WRITE call, which is what "refused" means in this codebase's voice -- proven now by
scanning every fake's own `.calls` log for a write-shaped method name, rather than one `FakeClient.
puts` counter. A raised `ApplicationError` reaches the caller as a `ToolError`; the claimed
fragment is checked against `str(exc.value)`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from synthetic import synthetic_process_draft
from tests.fakes.app import FakeAppRepository
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.copilot import FakeCopilotService
from tests.fakes.dataset import FakeDatasetRepository
from tests.fakes.docs import FakeDocsReader
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.intake_specs import full_spec
from tests.fakes.item import FakeItemService
from tests.fakes.page import FakePageRepository

from app.domain.entities.flow_draft import FlowDraft
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server

# --------------------------------------------------------------------------------------------
# The table. Each row: tool -> (a phrase that must appear in the LIVE description,
#                               kwargs that must trigger the refusal,
#                               a fragment the refusal message must name).
# The phrase is load-bearing in both directions: it stops the table drifting away from the text
# it claims to check, and it stops the text quietly losing a promise the code still keeps.
# --------------------------------------------------------------------------------------------
CLAIMS: dict[str, tuple[str, dict[str, Any], str]] = {
    "forge_add_role_users": (
        "is refused",
        {"role_id": "R1", "groups": [{"_id": "everyone", "Name": "Everyone"}]},
        "confirm_group_notification=True",
    ),
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
    "forge_add_table": (
        "it is refused here instead, before any write",
        {"flow_id": "F1", "name": "Items", "columns": [["Grade", "Select"]]},
        "ReferredList",
    ),
    "forge_add_goto_gate": (
        "rejected offline, before any write",
        {
            "flow_id": "F1",
            "target_activity_name": "Assess unit",
            "field_name": "Ticket No",
        },
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
        # Stage D moved this check into the request DTO's own closed `type` enum (spec G10:
        # "the same bad inputs fail with ValidationError") -- Pydantic's own loc-path notation
        # replaces the old hand-built "changes[0]['type']" bracket string, but the claim (a
        # malformed entry is refused BY INDEX, before any write) still holds.
        "changes.0.type",
    ),
    "kf_list_field_types": (
        "a wrong type is refused offline",
        # the claim is ABOUT the four tools whose `type` key it backstops — triggered on one of
        # them, since kf_list_field_types itself takes no arguments to get wrong
        {
            "__via__": "forge_add_table",
            "flow_id": "F1",
            "name": "T",
            "columns": [["SKU", "Nope"]],
        },
        "not a field type this engine can build",
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
    "forge_member_batch": "'still leaves the initiator refused' — the PLATFORM refusing a submit, not this tool "
    "refusing an argument",
    "forge_add_member_roles": "'member/batch rejects any role NOT scoped to KF_APP' — the write API's own rejection, "
    "which is exactly what this tool exists to avoid provoking",
    "forge_playbook": "names the playbook's 'refuse-loudly table' as a document section",
    "forge_render_flow_diagram": "a NEGATIVE claim: 'this tool never refuses on an incomplete spec'",
    "forge_request_confirmation": "a NEGATIVE claim: 'this tool does NOT refuse to build a confirmation package'",
    "forge_build_page": "real refusals (a dangling OpenPopup, a placeholder binding on a load-bearing widget), "
    "but they live in PageDraft/_build.py and need a whole page graph to trigger — "
    "already triggered by tests/unit/application/use_cases/page/test__build.py "
    "and tests/unit/domain/entities/test_page_draft.py, not re-staged here",
}

_REFUSAL_WORD = re.compile(r"\b(refus\w+|reject\w+)\b", re.IGNORECASE)

# Any port method whose name starts with one of these is a WRITE -- generalised across every
# family's fake (`tests/fakes/*.py`) rather than one family's own vocabulary, since this file
# drives tools across flow/app/page/dataset/item/intake in one table.
_WRITE_PREFIXES = (
    "put_",
    "create_",
    "delete_",
    "archive_",
    "publish",
    "post_",
    "submit",
    "reject",
)


def _settings() -> Settings:
    return Settings(
        kf_dev_domain="dev-acme.kissflow.com",
        kf_dev_account_id="A1",
        kf_app="App1",  # a single-app default, so no CLAIMS row needs its own app_id
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id="k1",
        kf_dev_access_key_secret="s1",
        http_timeout_seconds=10.0,
    )


@pytest.fixture()
def offline_resources() -> AppResources:
    """One `AppResources`, every fake fresh per test, `FakeFlowRepository.get_draft` primed with
    the engine's own synthetic process draft (several claimed refusals -- an unknown field name,
    a non-Boolean gate field -- only fire once the draft is actually read).

    Every refusal under test is supposed to fire before the first WRITE call, which is what
    "refused" means in this codebase's voice -- proven by scanning `flow.calls`/`app.calls` for a
    write-shaped method name (`_WRITE_PREFIXES`), never a live PUT.
    """
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire(synthetic_process_draft())] * 5
    return AppResources(
        flow=flow,
        app=FakeAppRepository(),
        artifacts=FakeArtifactWriter(),
        page=FakePageRepository(),
        dataset=FakeDatasetRepository(),
        item=FakeItemService(),
        copilot=FakeCopilotService(),
        docs=FakeDocsReader(),
    )


def _lifespan_factory(resources: AppResources):
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": resources, "settings": _settings()}

    return _lifespan


def _server(resources: AppResources) -> FastMCP:
    return create_server(_lifespan_factory(resources))


def _listed(resources: AppResources | None = None) -> dict[str, Any]:
    server = (
        _server(resources)
        if resources is not None
        else _server(
            AppResources(
                flow=FakeFlowRepository(),
                app=FakeAppRepository(),
                artifacts=FakeArtifactWriter(),
                page=FakePageRepository(),
                dataset=FakeDatasetRepository(),
                item=FakeItemService(),
                copilot=FakeCopilotService(),
                docs=FakeDocsReader(),
            )
        )
    )

    async def _run() -> Any:
        async with Client(server) as client:
            return await client.list_tools()

    return {t.name: t for t in asyncio.run(_run())}


def _description(tool_name: str) -> str:
    """The live description with its wrapping collapsed — a claim must not fall out of the table
    just because a line got re-flowed."""
    return " ".join((_listed()[tool_name].description or "").split())


async def _call_async(server: FastMCP, tool_name: str, args: dict[str, Any]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(tool_name, args)


def _call(tool_name: str, args: dict[str, Any], resources: AppResources) -> ToolError:
    """Materialise the two placeholders the static table cannot hold: a real draft graph, and a
    real, fully-populated AppSpec (the digest/token refusals sit BEHIND spec validation, so a
    stub spec would prove only that the validator works). Returns the raised `ToolError`.
    """
    args = dict(args)
    target = args.pop("__via__", tool_name)
    if args.get("draft", "") is None:
        args["draft"] = synthetic_process_draft()
    if args.get("spec") == "__full__":
        args["spec"] = full_spec().model_dump(mode="json")

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(_call_async(_server(resources), target, args))
    return excinfo.value


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
    tool_name: str,
    offline_resources: AppResources,
) -> None:
    """Half two: the promise is kept, as a `ToolError` naming what was wrong."""
    _phrase, args, fragment = CLAIMS[tool_name]
    exc = _call(tool_name, args, offline_resources)
    assert fragment in str(exc), (
        f"{tool_name} refused, but not for the claimed reason — wanted {fragment!r}, got {exc!r}"
    )


@pytest.mark.parametrize("tool_name", sorted(CLAIMS))
def test_a_refusal_never_writes_first(
    tool_name: str, offline_resources: AppResources
) -> None:
    """ "Refused" in this codebase's voice means BEFORE any write. A tool that refuses after a PUT
    has already changed the tenant, which is the opposite of what the word promises."""
    _phrase, args, _fragment = CLAIMS[tool_name]
    _call(tool_name, args, offline_resources)
    writes = [
        (name, fake_name)
        for fake_name, fake in (
            ("flow", offline_resources.flow),
            ("app", offline_resources.app),
            ("page", offline_resources.page),
            ("dataset", offline_resources.dataset),
            ("item", offline_resources.item),
        )
        for name, _call_args, _kwargs in cast(Any, fake).calls
        if name.startswith(_WRITE_PREFIXES)
    ]
    assert not writes, f"{tool_name} wrote {writes} then refused"


def test_every_refusal_claiming_tool_is_accounted_for() -> None:
    """The drift guard. A new tool cannot add "X is refused" to its description and stay out of
    both the table and the explicitly-reasoned exemption list."""
    claiming = {
        name
        for name, t in _listed().items()
        if _REFUSAL_WORD.search(t.description or "")
    }
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
    for table, label in (
        (CLAIMS, "CLAIMS"),
        (NOT_A_CLAIM_ABOUT_THIS_TOOL, "NOT_A_CLAIM_ABOUT_THIS_TOOL"),
    ):
        stale = sorted(
            name
            for name in table
            if name not in listed
            or not _REFUSAL_WORD.search(listed[name].description or "")
        )
        assert not stale, f"{stale} no longer claim a refusal — drop them from {label}"


def test_forge_set_events_names_five_types_not_six() -> None:
    """(b) pinned on both surfaces at once: the description and the refusal message must agree
    with `types.NO_EVENT_FIELD_TYPES`, and must say why the platform's sixth is not in it."""
    from app.domain.value_objects.field_type import NO_EVENT_FIELD_TYPES

    assert len(NO_EVENT_FIELD_TYPES) == 5 and "Rich text" not in NO_EVENT_FIELD_TYPES
    description = _description("forge_set_events")
    assert "FIVE types this engine refuses outright" in description
    assert "Rich text" in description and "does NOT" in description
    for wire_type in sorted(NO_EVENT_FIELD_TYPES):
        assert wire_type in description, f"{wire_type} is refused but not named"


def test_the_events_refusal_message_reads_the_engine_set_rather_than_restating_it(
    offline_resources: AppResources,
) -> None:
    """The message used to hard-code the same wrong six. It now prints the real frozenset, so it
    cannot drift from the code it describes."""
    from app.domain.value_objects.field_type import NO_EVENT_FIELD_TYPES

    exc = _call(
        "forge_set_events",
        {"flow_id": "F1", "events": {"Self-help Doc": [[None, "kf.x();"]]}},
        offline_resources,
    )
    err = str(exc)
    for wire_type in sorted(NO_EVENT_FIELD_TYPES):
        assert wire_type in err, f"{wire_type} missing from the refusal: {err}"
    assert "Rich text" in err and "uncaptured" in err


def test_forge_create_list_no_longer_claims_a_gate_the_compiler_does_not_have() -> None:
    """(c): `_op_create_list` emits a create_list op for a personal_data list like any other. The
    gate is the op's own `why`, and the description must point at THAT, not at a refusal."""
    from app.application.use_cases.intake._compile import compile_spec

    description = _description("forge_create_list")
    assert "the spec path refuses to compile" not in description
    assert "HUMAN-GATED" in description and "`why`" in description

    full = full_spec()
    flagged = tuple(
        lst.model_copy(update={"personal_data": lst.name == "Urgency Levels"})
        for lst in full.master_data.lists
    )
    plan = compile_spec(
        full.model_copy(
            update={
                "master_data": full.master_data.model_copy(update={"lists": flagged})
            }
        )
    )
    op = next(
        o
        for o in plan.ops
        if o.kind == "create_list" and o.args["name"] == "Urgency Levels"
    )
    assert op.args["personal_data"] is True
    assert "HUMAN-GATED" in op.why, (
        "the op's `why` IS the gate the description now names"
    )
