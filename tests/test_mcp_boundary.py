"""The MCP boundary itself — the one surface that had no test asserting anything (bundle C).

Everything here is OFFLINE. Where a test needs the REAL protocol path it uses FastMCP's in-memory
Client (same technique as tests/test_p2_server.py: no subprocess, no network), because the four
things under test — the result ENVELOPE's isError flag, tool annotations, tool titles and the
JSON-Schema enums — do not exist at all on a plain Python call into the tool function.

Four axes:
  1. protocol isError   — every failure sets `CallToolResult.isError`, and the payload key that
                          ~40 other tests assert on survives it intact.
  2. annotations/titles — all 59 tools carry all four hints plus a human title, and the hints
                          match what the BODY does, not what the description says.
  3. closed-set enums   — every closed vocabulary the engine already knows is an `enum`/`const`
                          in the emitted schema, and each one matches the engine constant it
                          mirrors (the anti-drift guard).
  4. no raises          — no tool escapes as an exception, with well-formed OR malformed args.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

import kfforge.server as srv
from kfforge.client import _SWEEP_SCOPES, _TIER_MAP, FlowKind
from kfforge.types import FieldType

KF_ENV_VARS = (
    "KF_DEV_ACCESS_KEY_ID", "KF_DEV_ACCESS_KEY_SECRET", "KF_DEV_ACCOUNT_ID", "KF_DEV_DOMAIN",
    "KF_APP",
)

# Well-typed args that reach each tool's FIRST statement and no further — the same idea as
# tests/test_p2_server.py's DUMMY_ARGS, extended to the whole 59-tool surface (that fixture only
# covers the forge_* subset). Every value is minimal and schema-valid: the point is to prove the
# tool RETURNS, never to make it do work.
MINIMAL_ARGS: dict[str, dict[str, Any]] = {
    "kf_list_field_types": {},
    "kf_plan_field_change": {"draft": {}, "changes": []},
    "kf_get_flow_schema": {"flow_kind": "process", "flow_id": "F"},
    "kf_apply_field_change": {"flow_kind": "process", "flow_id": "F", "changes": []},
    "kf_create_process": {"name": "N", "steps": [], "fields": []},
    "kf_plan_step_visibility": {"draft": {}, "owners": {}},
    "kf_set_step_visibility": {"flow_id": "F", "owners": {}},
    "kf_publish": {"flow_kind": "process", "flow_id": "F"},
    "forge_create_process": {"name": "N"},
    "forge_member_batch": {"target_flow_id": "F"},
    "forge_add_member_roles": {"target_flow_id": "F", "roles": {}},
    "forge_create_app_role": {"name": "R"},
    "forge_delete_app_role": {"role_id": "R"},
    "forge_list_app_roles": {},
    "forge_apply_fields": {"flow_id": "F", "fields": []},
    "forge_apply_layout": {"flow_id": "F", "layout": {}},
    "forge_add_table": {"flow_id": "F", "name": "T", "columns": []},
    "forge_compare_to_spec": {"flow_id": "F", "spec": {}},
    "forge_create_list": {"name": "L", "values": []},
    "forge_add_sequence_number": {"flow_id": "F", "field_name": "N", "section_name": "S",
                                  "prefix": "P-", "padding": "0001", "step_activity_name": "Start"},
    "forge_add_field_validation": {"flow_id": "F", "rules": {}},
    "forge_build_workflow": {"flow_id": "F", "steps": []},
    "forge_add_goto_gate": {"flow_id": "F", "target_activity_name": "A", "field_name": "B"},
    "forge_set_branch_conditions": {"flow_id": "F", "field_name": "B", "branch_literals": {}},
    "forge_set_visibility": {"flow_id": "F", "owners": {}},
    "forge_set_events": {"flow_id": "F", "events": {}},
    "forge_delete_fields": {"flow_id": "F", "fields": ["a"]},
    "forge_rename_fields": {"flow_id": "F", "renames": {}},
    "forge_set_required": {"flow_id": "F", "required": []},
    "forge_set_styles": {"flow_id": "F", "styles": {}},
    "forge_publish": {"kind": "process", "flow_id": "F"},
    "forge_doctor": {"flow_id": "F"},
    "forge_create_page": {"app_id": "A", "name": "P"},
    "forge_build_page": {"app_id": "A", "page_id": "P", "steps": []},
    "forge_set_navigation": {"app_id": "A", "page_id": "P", "label": "L"},
    "forge_share_report": {"flow_id": "F", "report_id": "R", "members": []},
    "forge_simulate_case": {"flow_id": "F", "steps": []},
    "forge_create_app": {"name": "N"},
    "forge_list_apps": {},
    "forge_delete_flow": {"kind": "process", "flow_id": "F"},
    "forge_add_role_users": {"role_id": "R", "user_query": "ann"},
    "forge_grant_tier": {"kind": "process", "flow_id": "F", "role_id": "R", "tier": "Manage"},
    "forge_create_flow": {"kind": "process", "name": "N"},
    "forge_publish_app": {"app_id": "A"},
    "forge_dataset_records": {"flow_id": "F", "op": "list"},
    "forge_set_role_preference": {"role_id": "R", "default_page": "Default"},
    "forge_sweep": {"scope": "apps"},
    "forge_capabilities": {},
    "forge_playbook": {},
    "forge_copilot_ask": {"app_id": "A", "message": "hi"},
    "forge_copilot_check": {"app_id": "A", "conversation_id": "C"},
    "forge_intake_questions": {},
    "forge_update_spec": {"spec": None, "patch": {}},
    "forge_render_flow_diagram": {"spec": {}},
    "forge_render_schema_diagram": {"spec": {}},
    "forge_render_mockups": {"spec": {}},
    "forge_request_confirmation": {"spec": {}},
    "forge_apply_revisions": {"spec": {}, "revisions": {}},
    "forge_approve_spec": {"spec": {}, "digest": "d", "decision": "approve"},
    "forge_plan_app": {"spec": {}, "approval_token": "t"},
}


def _tool_names() -> list[str]:
    return sorted(n for n in dir(srv) if n.startswith(("kf_", "forge_")) and callable(getattr(srv, n)))


def _listed() -> list[Any]:
    from fastmcp import Client

    async def _run() -> list[Any]:
        async with Client(srv.mcp) as client:
            return await client.list_tools()

    return asyncio.run(_run())


@pytest.fixture()
def no_kf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in KF_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def test_minimal_args_cover_every_registered_tool() -> None:
    """Fixture-drift guard: a new tool must be probed by every test in this file, not skipped."""
    assert set(MINIMAL_ARGS) == set(_tool_names())


# =================================================================================================
# 1. PROTOCOL isError (M1) — the finding, on the wire
# =================================================================================================

def _call(tool: str, args: dict[str, Any]) -> Any:
    from fastmcp import Client

    async def _run() -> Any:
        async with Client(srv.mcp) as client:
            # raise_on_error=False so the RESULT is inspectable — the whole point here is the flag
            # on the envelope, which the raising path swallows into a ToolError string.
            return await client.call_tool(tool, args, raise_on_error=False)

    return asyncio.run(_run())


@pytest.mark.parametrize("tool_name", sorted(n for n in MINIMAL_ARGS if n.startswith("forge_")
                                             and n not in {"forge_capabilities", "forge_playbook",
                                                           "forge_intake_questions",
                                                           "forge_update_spec"}))
def test_a_failing_tool_sets_isError_on_the_PROTOCOL_envelope(tool_name: str,
                                                              no_kf_env: None) -> None:
    """M1: every tool reports failure as a payload dict carrying `isError: true`, but MCP defines
    isError on the result ENVELOPE. Because these tools RETURN rather than raise, the envelope
    flag stayed False and every failure read as a protocol SUCCESS to any gateway, dashboard or
    retry layer. Proven here on the real wire, tool by tool."""
    result = _call(tool_name, MINIMAL_ARGS[tool_name])
    assert result.structured_content is not None, tool_name
    assert result.structured_content.get("isError") is True, result.structured_content
    assert result.is_error is True, (
        f"{tool_name} reported isError in its PAYLOAD but the protocol envelope says success: "
        f"{result.structured_content}"
    )


def test_the_isError_payload_key_survives_the_promotion(no_kf_env: None) -> None:
    """The middleware must set the envelope flag WITHOUT touching the payload — ~40 tests in this
    repo (and every caller written against this surface) read `got["isError"]` off the dict."""
    result = _call("forge_doctor", {"flow_id": "F"})
    assert result.is_error is True
    assert result.structured_content == {
        "isError": True,
        "error": "config: missing env var KF_DEV_DOMAIN",
        "status": None,
    }
    # content blocks are copied through byte-identically too, not re-serialized
    assert result.content and "missing env var" in str(result.content)


def test_a_succeeding_tool_is_NOT_marked_an_error(no_kf_env: None) -> None:
    """The other half of the invariant: promotion is driven by the payload, so an offline tool
    that genuinely succeeds must still come back as a protocol success."""
    result = _call("forge_playbook", {})
    assert result.structured_content is not None
    assert result.structured_content.get("isError") is False
    assert result.is_error is False


def test_a_tool_whose_result_has_no_isError_key_is_left_alone(no_kf_env: None) -> None:
    """kf_list_field_types returns a bare list — no isError key anywhere. The middleware must not
    invent a verdict for a payload that never claimed one."""
    result = _call("kf_list_field_types", {})
    assert result.is_error is False
    assert "Text" in result.data


def test_every_boundary_returns_a_dict_carrying_an_explicit_isError(no_kf_env: None) -> None:
    """The two tools that used to return a module call directly rather than through `_result`
    (forge_sweep -> run_sweep, forge_capabilities -> search_capabilities), plus forge_playbook and
    forge_delete_flow, now all route through it. Whatever they return must carry the payload key
    the middleware reads, or the promotion above can never fire for them."""
    for tool, args in (("forge_sweep", {"scope": "apps"}),
                       ("forge_capabilities", {"query": ""}),
                       ("forge_playbook", {}),
                       ("forge_delete_flow", {"kind": "process", "flow_id": "F"})):
        got = getattr(srv, tool)(**args)
        assert isinstance(got, dict), f"{tool} returned {type(got).__name__}"
        assert "isError" in got, f"{tool} result has no isError key: {sorted(got)}"


# =================================================================================================
# 2. ANNOTATIONS + TITLES (M2)
# =================================================================================================

def test_every_tool_carries_all_four_hints_and_a_title() -> None:
    """M2: zero of the 59 tools carried readOnlyHint/destructiveHint/idempotentHint/openWorldHint,
    despite ~40 live write tools and several that delete whole applications."""
    for t in _listed():
        assert t.title, f"{t.name} has no human-readable title"
        a = t.annotations
        assert a is not None, f"{t.name} has no annotations"
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert getattr(a, hint) is not None, f"{t.name} is missing {hint}"


def test_read_only_is_never_claimed_by_a_tool_that_writes_something() -> None:
    """readOnlyHint true ONLY if the body writes neither the tenant nor the filesystem. The four
    render/confirm tools are the trap: every one of them says "OFFLINE" in its own description and
    then writes files to disk, which is precisely why these hints are derived from the body."""
    writes_files = {"forge_render_flow_diagram", "forge_render_schema_diagram",
                    "forge_render_mockups", "forge_request_confirmation"}
    by_name = {t.name: t for t in _listed()}
    for name in writes_files:
        assert by_name[name].annotations.readOnlyHint is False, (
            f"{name} writes artifact files to disk — it is not read-only, whatever its "
            f"description prefix says"
        )
        assert by_name[name].annotations.openWorldHint is False, f"{name} touches no tenant"

    # ...and no tool claiming readOnlyHint may call a WRITE entrypoint or write a file. Reading
    # the tenant is read-only; writing it is not, and that distinction is what the hint is for.
    for name, t in by_name.items():
        if not t.annotations.readOnlyHint:
            continue
        body = inspect.getsource(getattr(srv, name))
        assert "_write_artifact(" not in body, f"{name} claims readOnlyHint but writes a file"
        for writer in sorted(_LIVE_WRITE_ENTRYPOINTS):
            assert f"{writer}(" not in body, (
                f"{name} claims readOnlyHint but its body calls {writer}()"
            )


def test_destructive_hint_is_set_on_every_tool_that_replaces_or_deletes_state() -> None:
    """The named cases from the finding, each verified against what the body actually does."""
    by_name = {t.name: t for t in _listed()}
    must_be_destructive = {
        # replaces EVERY Permission on the flow
        "forge_set_visibility", "kf_set_step_visibility",
        # wipes every Activity/ProcessDef/Resource/Permission
        "forge_build_workflow",
        # REPLACE semantics on the whole item array
        "forge_create_list",
        # SET semantics: every root field not listed comes back optional
        "forge_set_required",
        # rebuilds every Row in the named sections
        "forge_apply_layout", "forge_apply_fields",
        # replaces every existing event on the named fields
        "forge_set_events",
        # "No access" is a real DELETE .../member/{role_id}
        "forge_grant_tier",
        # deletes, outright
        "forge_delete_fields", "forge_delete_flow", "forge_delete_app_role",
        # op="delete" is one of the four
        "forge_dataset_records",
    }
    for name in sorted(must_be_destructive):
        assert by_name[name].annotations.destructiveHint is True, (
            f"{name} removes or overwrites existing state but is not marked destructive"
        )
    # ...and the additive ones are not over-flagged
    for name in ("kf_apply_field_change", "forge_add_table", "forge_add_sequence_number",
                 "forge_add_field_validation", "forge_add_role_users", "forge_member_batch"):
        assert by_name[name].annotations.destructiveHint is False, name


def test_open_world_is_exactly_the_tenant_touching_set() -> None:
    """openWorldHint true for anything that reaches the Kissflow tenant — which is exactly the set
    of tools that resolve a client, plus nothing else."""
    for t in _listed():
        body = inspect.getsource(getattr(srv, t.name))
        touches_tenant = "_client(" in body
        assert t.annotations.openWorldHint is touches_tenant, (
            f"{t.name}: openWorldHint={t.annotations.openWorldHint} but "
            f"{'it resolves a KfClient' if touches_tenant else 'it never touches the tenant'}"
        )


def test_the_four_render_tools_no_longer_advertise_themselves_as_offline_only() -> None:
    """A hint disagreeing with its own description is the same bug in a different place."""
    by_name = {t.name: t for t in _listed()}
    for name in ("forge_render_flow_diagram", "forge_render_mockups"):
        assert "Written to" in by_name[name].description or "written to" in by_name[name].description


# =================================================================================================
# 3. CLOSED-SET ENUMS (A2)
# =================================================================================================

# Every live-WRITE orchestration entrypoint this module exposes, derived from the module itself
# rather than hand-listed, so a new writer joins the check the day it is imported. `run_doctor` /
# `run_sweep` / `search_capabilities` are reads and do not match the verb prefixes.
_LIVE_WRITE_ENTRYPOINTS = {
    name for name in dir(srv)
    if getattr(getattr(srv, name), "__module__", "") in ("kfforge.client", "kfforge.pages_live")
    and name.split("_")[0] in ("apply", "create", "delete", "rename", "publish")
} - {
    # a MISNOMER, not an exception to the rule: `apply_copilot_check` only reads — the copilot
    # thread, the flow inventory, and one draft per scattered flow. Nothing in it writes.
    "apply_copilot_check",
}


def _param_schema(tool_name: str, param: str) -> dict[str, Any]:
    t = next(t for t in _listed() if t.name == tool_name)
    return (t.inputSchema.get("properties") or {})[param]


def _closed_values(schema: dict[str, Any]) -> list[Any]:
    """A closed set is `enum` for 2+ members and `const` for exactly one (Pydantic emits both)."""
    if "enum" in schema:
        return list(schema["enum"])
    if "const" in schema:
        return [schema["const"]]
    raise AssertionError(f"not a closed set: {schema}")


@pytest.mark.parametrize("tool_name, param, expected", [
    ("kf_get_flow_schema", "flow_kind", ["form", "process", "case", "dataset", "page"]),
    ("kf_apply_field_change", "flow_kind", ["form", "process", "case", "dataset"]),
    ("forge_apply_fields", "kind", ["form", "process", "case", "dataset"]),
    ("kf_publish", "flow_kind", ["form", "process", "case"]),
    ("forge_publish", "kind", ["form", "process", "case", "page", "application"]),
    ("forge_delete_flow", "kind",
     ["form", "process", "case", "list", "dataset", "page", "application"]),
    ("forge_grant_tier", "kind", ["process", "case"]),
    ("forge_create_flow", "kind", ["process", "form", "list", "dataset", "case"]),
    ("forge_dataset_records", "op", ["create", "update", "delete", "list"]),
    ("forge_sweep", "scope", ["apps", "flows", "pages", "roles", "lists", "all"]),
    ("forge_approve_spec", "decision", ["approve"]),
])
def test_a_closed_vocabulary_reaches_the_schema_as_an_enum(tool_name: str, param: str,
                                                           expected: list[str]) -> None:
    """A2: 214 parameters, ZERO enums — and two of these were interpolated UNVALIDATED into live
    API URLs. Every one of them is a set the engine already knew and erased at the boundary."""
    assert _closed_values(_param_schema(tool_name, param)) == expected


def test_the_different_kind_sets_are_NOT_unified() -> None:
    """Several different closed sets hide under the one parameter name `kind`. Collapsing them
    into a single union would tell a caller that forge_grant_tier(kind="form") or
    forge_create_flow(kind="application") is legal — neither is. The DELETE set is the fifth, and
    the one that got wrongly folded into `publish` (D7): it is the widest of them all."""
    grant = set(_closed_values(_param_schema("forge_grant_tier", "kind")))
    create = set(_closed_values(_param_schema("forge_create_flow", "kind")))
    publish = set(_closed_values(_param_schema("forge_publish", "kind")))
    flow = set(_closed_values(_param_schema("forge_doctor", "kind")))
    delete = set(_closed_values(_param_schema("forge_delete_flow", "kind")))
    data = set(_closed_values(_param_schema("forge_apply_fields", "kind")))
    assert "form" not in grant and "application" not in create
    assert "list" not in publish and "application" not in flow
    assert "list" not in data, "a word list has no field-bearing draft graph"
    assert len({frozenset(s) for s in (grant, create, publish, flow, delete, data)}) == 6


def test_every_kind_shaped_parameter_is_a_closed_set() -> None:
    """No silent survivor: any parameter named kind/flow_kind/scope/op/tier/decision on any tool
    must be enumerable, or a typo reaches the engine again."""
    closed_names = {"kind", "flow_kind", "scope", "op", "tier", "decision"}
    checked = 0
    for t in _listed():
        for pname, schema in (t.inputSchema.get("properties") or {}).items():
            # forge_build_page's `op` is a compiled build_page OBJECT, not a vocabulary — the
            # name collides, the meaning does not. Only string-valued slots are vocabularies.
            if pname not in closed_names or schema.get("type") != "string":
                continue
            _closed_values(schema)  # raises with the offending schema if it is open
            checked += 1
    assert checked >= 28, f"only {checked} closed-set parameters found — did a Literal get lost?"


def test_boundary_enums_match_the_engine_constants_they_mirror() -> None:
    """The anti-drift guard. These Literals are hand-written (a Literal cannot be built from a
    runtime dict), so this test is what stops them diverging from the engine's own sets."""
    assert set(_closed_values(_param_schema("forge_doctor", "kind"))) == set(FlowKind.__args__)
    assert set(_closed_values(_param_schema("forge_grant_tier", "kind"))) == set(_TIER_MAP)
    assert set(_closed_values(_param_schema("forge_grant_tier", "tier"))) == {
        tier for by_tier in _TIER_MAP.values() for tier in by_tier
    }
    assert set(_closed_values(_param_schema("forge_sweep", "scope"))) == set(_SWEEP_SCOPES) | {"all"}


def test_kf_list_field_types_still_serves_the_engine_set_it_documents() -> None:
    assert srv.kf_list_field_types() == [t.value for t in FieldType]


def test_kf_list_field_types_no_longer_calls_the_engine_set_the_platforms_closed_enum() -> None:
    """C5: this one tool misrepresented the platform — it called the 8 types this engine can build
    the platform's "closed enum" when the platform's palette is much wider. It must now say what
    it actually is and point at forge_capabilities for the rest."""
    doc = next(t for t in _listed() if t.name == "kf_list_field_types").description or ""
    assert "closed enum" not in doc.lower()
    assert "forge_capabilities" in doc
    assert "THIS ENGINE" in doc or "this engine" in doc


# =================================================================================================
# 4. NO RAISES THROUGH THE TOOL BOUNDARY (A1, doctrine 7)
# =================================================================================================

# The nested arguments a schema can only describe as list[Any]/dict[str, Any] — one malformed
# value each, of the shape an agent actually gets wrong: a pair one element short, an object with
# a missing key, a bare string where a list of triples belongs.
# The nested arguments a schema can only describe as list[Any]/dict[str, Any] — one malformed
# value each, of the shape an agent actually gets wrong (a pair one element short, an object with
# a missing key), paired with the fragment its refusal MUST name.
MALFORMED_ARGS: dict[str, tuple[dict[str, Any], str]] = {
    "kf_plan_field_change": ({"draft": {}, "changes": [{"name": "x"}]},
                             "changes[0]['type']"),
    "kf_apply_field_change": ({"flow_kind": "process", "flow_id": "F",
                               "changes": [{"name": "x", "type": "Wat"}]},
                              "changes[0]['type']"),
    "kf_create_process": ({"name": "N", "steps": [], "fields": [{"type": "Text"}]},
                          "fields[0]['name']"),
    "forge_apply_fields": ({"flow_id": "F", "fields": [{"name": "a", "type": "Nope"}]},
                           "fields[0]['type']"),
    "forge_apply_layout": ({"flow_id": "F", "layout": {"S": [[["a", 0]]]}},
                           "layout['S'][0][0]"),
    "forge_add_table": ({"flow_id": "F", "name": "T", "columns": [["only-a-name"]]},
                        "columns[0]"),
    "forge_add_field_validation": ({"flow_id": "F", "rules": {"a": [["CONTAINS"]]}},
                                   "rules['a'][0]"),
    "forge_build_workflow": ({"flow_id": "F", "steps": [["Approve"]]},
                             "steps[0]"),
    "forge_set_events": ({"flow_id": "F", "events": {"a": [["onChange"]]}},
                         "events['a'][0]"),
    "forge_build_page": ({"app_id": "A", "page_id": "P", "steps": [{"kwargs": {}}]},
                         "steps[0]['kind']"),
    "forge_simulate_case": ({"flow_id": "F", "steps": [{"values": {}}]},
                            "steps[0]['name']"),
}

# The one parameter with a nested list-of-lists inside an object.
MALFORMED_PARALLEL = {"flow_id": "F", "steps": [["Approve", None]],
                      "parallel": {"branches": [["B", [["S", None]]]]}}  # no 'name'


@pytest.mark.parametrize("tool_name", sorted(MALFORMED_ARGS))
def test_a_malformed_nested_arg_returns_data_not_a_traceback(tool_name: str,
                                                             fake_kf_env: None) -> None:
    """A1 / doctrine 7. Every one of these destructured a nested parameter with no shape check, so
    the single most likely agent mistake produced a bare Python traceback instead of structured
    data. `fake_kf_env` puts a well-formed (fake) dev config in place on purpose: without it the
    config gate short-circuits first and the destructure below it is never even reached, which is
    what made this class of bug invisible to the existing offline suite. No network happens —
    every one of these guards sits between the config gate and the first HTTP call."""
    args, _ = MALFORMED_ARGS[tool_name]
    got = getattr(srv, tool_name)(**args)
    assert isinstance(got, dict), f"{tool_name} returned {type(got).__name__}, not a dict"
    assert got.get("isError") is True, got
    assert got.get("error", "").startswith("verify:"), got


@pytest.mark.parametrize("tool_name", sorted(MALFORMED_ARGS))
def test_the_refusal_names_the_parameter_and_shows_a_correct_example(tool_name: str,
                                                                     fake_kf_env: None) -> None:
    """A refusal that does not say WHICH argument was wrong, what arrived, and what right looks
    like is just a nicer traceback."""
    args, wanted = MALFORMED_ARGS[tool_name]
    err = getattr(srv, tool_name)(**args)["error"]
    assert wanted in err, f"{tool_name}: refusal does not name {wanted}: {err}"
    assert "correct shape:" in err or "valid:" in err, f"{tool_name}: no example: {err}"


def test_a_parallel_block_with_no_name_is_refused_by_name(fake_kf_env: None) -> None:
    got = srv.forge_build_workflow(**MALFORMED_PARALLEL)
    assert got.get("isError") is True
    assert "parallel['name']" in got["error"], got


def test_the_two_plan_tools_no_longer_raise_before_any_gate(no_kf_env: None) -> None:
    """kf_plan_field_change and kf_plan_step_visibility are OFFLINE — they have no config gate to
    short-circuit behind, so a bad argument used to escape as a bare traceback on the very first
    statement, credentials or not. Both now return the refusal as data."""
    bad_type = srv.kf_plan_field_change({}, [{"name": "x", "type": "Nope"}])
    assert bad_type["isError"] is True and "changes[0]['type']" in bad_type["error"]

    # an empty/foreign draft: graph.progressive_matrix's own ValueError, now translated
    bad_draft = srv.kf_plan_step_visibility({}, {"Intake": ["Start"]})
    assert bad_draft["isError"] is True
    assert "verify:" in bad_draft["error"] and "ProcessDef" in bad_draft["error"]


@pytest.mark.parametrize("tool_name", sorted(MINIMAL_ARGS))
def test_no_tool_escapes_as_an_exception_with_no_credentials(tool_name: str,
                                                             no_kf_env: None) -> None:
    """The blanket net: every tool on the surface, called with well-typed args and no config,
    returns rather than raises."""
    got = getattr(srv, tool_name)(**MINIMAL_ARGS[tool_name])
    assert isinstance(got, (dict, list)), f"{tool_name} returned {type(got).__name__}"


@pytest.mark.parametrize("tool_name", sorted(MINIMAL_ARGS))
def test_no_tool_escapes_as_an_exception_with_malformed_args(tool_name: str,
                                                             no_kf_env: None) -> None:
    """The same net, with garbage in every slot the schema types loosely. Offline (no config), so
    a tool that survives its own shape check simply stops at the config gate — either way nothing
    leaves this boundary as an exception."""
    garbage: dict[str, Any] = {}
    for key, value in MINIMAL_ARGS[tool_name].items():
        if isinstance(value, dict):
            garbage[key] = {"": ["", 1, None]}
        elif isinstance(value, list):
            garbage[key] = [["only-one"], {"no": "kind"}, None]
        else:
            garbage[key] = value
    got = getattr(srv, tool_name)(**garbage)
    assert isinstance(got, (dict, list)), f"{tool_name} returned {type(got).__name__}"


@pytest.mark.parametrize("tool_name", sorted(MALFORMED_ARGS))
def test_a_malformed_arg_is_an_error_on_the_protocol_envelope_too(tool_name: str,
                                                                  fake_kf_env: None) -> None:
    """The two fixes meet: a shape refusal is structured DATA (A1) AND a protocol error (M1)."""
    result = _call(tool_name, MALFORMED_ARGS[tool_name][0])
    assert result.is_error is True, result.structured_content
    assert result.structured_content is not None
    assert result.structured_content.get("isError") is True


@pytest.fixture()
def fake_kf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed but entirely FAKE dev config, so `_client()` succeeds and the shape guards
    below it are actually reached. Nothing here can reach a real tenant: the domain does not
    resolve, and every guarded destructure returns before the first HTTP call anyway."""
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-nowhere.invalid")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_ID", "fake-id")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "fake-secret")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "fake-account")
    monkeypatch.setenv("KF_APP", "App_fake")


# ---- D3: a DIAGNOSIS is not a failed call ------------------------------------------------------

def test_a_health_verdict_is_not_promoted_to_a_protocol_error(monkeypatch) -> None:
    """Driven END TO END through the real middleware, because that is where the bug lived.

    forge_doctor is a read-only audit: it states a verdict about the FLOW under `ok` and sets the
    payload's own `isError` from it. A doctor run that finds a sparse matrix has WORKED. SKILL.md
    tells the builder to run it after EVERY edit, so a mid-build call legitimately reports problems
    almost every time — promoting that to the ENVELOPE marks a perfectly healthy read-only call as
    a protocol failure, and under a client's default raise_on_error it RAISES, destroying the
    diagnosis the caller asked for.
    """
    import asyncio
    import kfforge.server as srv

    draft = {
        "Root": "M1", "M1": {"Id": "M1", "Kind": "Model"},
        "A1": {"Id": "A1", "Kind": "Activity", "Name": "S1"},
        "R1": {"Id": "R1", "Kind": "Row", "Row::Column": ["C_a"]},
        "S1": {"Id": "S1", "Kind": "Column", "Type": "Section", "Name": "Ghost",
               "Column::Row": ["R1"]},
        "C_a": {"Id": "C_a", "Kind": "Column", "Type": "Field", "Name": "F",
                "Start": 0, "End": 2},
    }

    class _Fake:
        _cfg = type("c", (), {"app_id": "App1"})()

        def get_draft(self, *a, **k):
            return draft

        def list_lists(self, *a, **k):
            return []

    monkeypatch.setattr(srv, "_client", lambda app_id=None, require_app=True: _Fake())
    result = asyncio.run(srv.mcp.call_tool("forge_doctor", {"flow_id": "F1"}))
    payload = result.structured_content or {}

    assert payload["ok"] is False and payload["problems"], "the audit must have found something"
    assert payload["isError"] is True, "the payload verdict convention is unchanged"
    assert result.is_error is False, (
        "a read-only audit that successfully diagnosed a problem is NOT a failed call"
    )


def test_a_real_failure_is_still_promoted_end_to_end(monkeypatch) -> None:
    """The control: the M1 fix must survive the D3 carve-out."""
    import asyncio
    import kfforge.server as srv
    from kfforge.client import Err

    monkeypatch.setattr(srv, "_client",
                        lambda app_id=None, require_app=True: Err("config", "missing env var"))
    result = asyncio.run(srv.mcp.call_tool("kf_publish",
                                           {"flow_kind": "process", "flow_id": "X"}))
    payload = result.structured_content or {}
    assert payload["isError"] is True and "error" in payload
    assert result.is_error is True, "a genuine failure must still reach the envelope"


# =================================================================================================
# 5. THE OPPOSITE FAILURE (D7) — an enum TIGHTER than the code supports is a capability regression
#
# Adding enums in bulk has its own trap, and this branch shipped it: `forge_delete_flow` took a
# bare `str` and reached `client.delete_flow(kind, ...)` for ANY kind. Typing it as PublishKind
# removed the only route to delete a `list` or a `dataset` — two kinds `forge_create_flow` mints
# freely — because "cannot be published" was read as "cannot be deleted". These tests assert the
# reachable set, from the reachable CREATES and from the code path behind each parameter.
# =================================================================================================


def test_every_kind_forge_create_flow_can_mint_can_also_be_deleted() -> None:
    """D7, stated as the invariant it is: an agent must never be able to create something through
    this surface that it cannot then clean up through this surface."""
    creatable = set(_closed_values(_param_schema("forge_create_flow", "kind")))
    deletable = set(_closed_values(_param_schema("forge_delete_flow", "kind")))
    assert creatable - deletable == set(), (
        f"forge_create_flow can mint {sorted(creatable - deletable)} and forge_delete_flow "
        f"cannot delete them — a capability regression, not a tighter schema"
    )


def test_delete_and_publish_are_deliberately_DIFFERENT_sets() -> None:
    """The bug was reusing one Literal for both. `list`/`dataset` are born LIVE with no publish
    route at all, and are ordinary /flow records that delete + re-list like any other."""
    publishable = set(_closed_values(_param_schema("forge_publish", "kind")))
    deletable = set(_closed_values(_param_schema("forge_delete_flow", "kind")))
    assert {"list", "dataset"} <= deletable
    assert {"list", "dataset"} & publishable == set()
    assert publishable != deletable


def test_delete_anything_really_routes_a_list_and_a_dataset(monkeypatch) -> None:
    """Not just the schema: the engine path behind the widened enum, exercised offline. A `list`
    and a `dataset` take the generic /flow/2/{acct}/{kind}/{id} branch and are verified by
    re-listing that kind — never archived first (only a process needs that)."""
    from kfforge.client import delete_anything

    class _Fake:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, str, bool]] = []
            self.listed: list[str] = []

        def delete_flow(self, kind, flow_id, archive_first=True):
            self.deleted.append((kind, flow_id, archive_first))
            return None

        def list_flows(self, kind):
            self.listed.append(kind)
            return []

    for kind in ("list", "dataset"):
        c = _Fake()
        got = delete_anything(c, kind, "F1")
        assert got == {"kind": kind, "id": "F1", "deleted": True, "verified": True,
                       "isError": False}, got
        assert c.deleted == [(kind, "F1", True)] and c.listed == [kind]


def test_a_dataform_draft_is_still_readable_and_field_writable() -> None:
    """The other half of the same audit: `dataset` was reachable on the draft-read and
    field-write tools before the enums landed, and docs/capabilities/module.dataform.md is the
    coverage row that proves it ("the engine's `apply_fields` runs unmodified with
    kind='dataset'"). `list` is NOT admitted anywhere — a word list has no draft graph, and
    doctrine 10 says no capture means refuse, not guess."""
    for tool, param in (("kf_get_flow_schema", "flow_kind"),
                        ("kf_apply_field_change", "flow_kind"),
                        ("forge_apply_fields", "kind")):
        values = set(_closed_values(_param_schema(tool, param)))
        assert "dataset" in values, f"{tool}.{param} lost the dataform"
        assert "list" not in values, f"{tool}.{param} admits a kind with no captured draft graph"


def test_the_widened_sets_are_still_closed_and_still_reject_junk() -> None:
    """Widening is not opening: every set stays an enum, and nothing outside it gets through."""
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    async def _run() -> Any:
        async with Client(srv.mcp) as client:
            return await client.call_tool("forge_delete_flow",
                                          {"kind": "spreadsheet", "flow_id": "F"},
                                          raise_on_error=False)

    result = asyncio.run(_run())
    assert result.is_error is True
    assert "spreadsheet" in str(result.content) or "enum" in str(result.content).lower()
