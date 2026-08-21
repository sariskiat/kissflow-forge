"""The MCP SURFACE contract — the net that stops the tool boundary regressing again.

The root cause behind every boundary finding bundles A/B/C closed, stated plainly: grepping the
whole suite at 9d4fa36 for `_list_tools`, `to_mcp_tool`, `outputSchema` or `annotations` returned
ZERO hits. Nothing would have noticed if a tool lost its description, cited a tool that does not
exist, shipped an open `str` where the engine has a closed set, or started reporting protocol
SUCCESS on failure. For a repo whose governing rule is that a claim is not a fact until something
verifies it, the emitted MCP surface was the one place with no verification — which is exactly how
it accumulated zero annotations, 59 vacuous output schemas, a dangling tool citation and an
inverted error flag, all at once and all unnoticed.

This file is that missing verification. It asserts the CONTRACT OF THE EMITTED SURFACE, never the
Python functions behind it — every check reads the real `list_tools()` output through FastMCP's
in-memory Client (same technique as tests/test_p2_server.py and tests/test_mcp_boundary.py: no
subprocess, no network), because a description, a title, an annotation block, a JSON-Schema enum
and the result envelope's `isError` flag do not exist at all on a plain Python call.

Six axes:
  1. per tool     — a real description, a real title, an annotations block whose four hints are
                    booleans and are self-consistent (nothing is read-only AND destructive), and
                    hints that agree with what the tool's own prose claims about itself.
  2. citations    — every `kf_*`/`forge_*` name mentioned in ANY description resolves to a
                    registered tool, and so does every one mentioned anywhere in the engine (the
                    `remediation` tuples cross the boundary as data — a name that resolves to
                    nothing is an instruction the caller cannot follow).
  3. the enum lint— no parameter whose description enumerates its own legal values is typed as a
                    bare `str`. This is the check that stops the next change re-opening A2.
  4. the ratchets — the two gaps bundle C could NOT close (vacuous output schemas, undocumented
                    parameters) are pinned behind SHRINK-ONLY allowlists, so the debt is visible,
                    cannot grow silently, and goes away by being deleted from a list.
  5. the flag     — a payload-level failure is ALSO a protocol-level failure (C1), asserted at the
                    surface AND at the mechanism, so removing the middleware fails a test.
  6. the joins    — the review's three headline reproductions, each proven to survive the trip out
                    through the tool boundary rather than only inside its own module.

Deliberately NOT duplicated from tests/test_mcp_boundary.py: that file proves each individual fix
(which hint each tool should carry, which enum matches which engine constant, which malformed
argument produces which refusal). This one proves the SHAPE OF THE SURFACE, tool-agnostically, so
a tool added tomorrow is held to the same contract without anyone remembering to add it here.
"""
from __future__ import annotations

import asyncio
import functools
import pathlib
import re
from typing import Any

import pytest
from test_client import FakeClient, _bare_form_draft  # tests/ is on sys.path, see conftest.py

import kfforge.server as srv
from kfforge.client import ApplyReport

KF_ENV_VARS = (
    "KF_DEV_ACCESS_KEY_ID", "KF_DEV_ACCESS_KEY_SECRET", "KF_DEV_ACCOUNT_ID", "KF_DEV_DOMAIN",
    "KF_APP",
)


def _module_tool_names() -> list[str]:
    """The tool names visible on the module, used for parametrization at COLLECTION time.

    Deliberately not `_emitted()`: collection must not depend on an event loop, and the two sets
    being equal is itself an assertion below (a decoration-time failure leaves the plain function
    in the module namespace, so a name-check alone proves nothing about registration)."""
    return sorted(n for n in dir(srv)
                  if n.startswith(("kf_", "forge_")) and callable(getattr(srv, n)))


@functools.lru_cache(maxsize=1)
def _emitted() -> dict[str, Any]:
    """name -> the REAL emitted MCP tool. Built once: booting the server is the expensive part,
    and every test in this file wants the same immutable listing."""
    from fastmcp import Client

    async def _run() -> list[Any]:
        async with Client(srv.mcp) as client:
            return await client.list_tools()

    return {t.name: t for t in asyncio.run(_run())}


@pytest.fixture()
def no_kf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in KF_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


# =================================================================================================
# 1. PER TOOL — description, title, annotations
# =================================================================================================

def test_every_module_level_tool_is_actually_registered() -> None:
    """Registration drift, both ways: a tool whose decoration failed still shows up in `dir(srv)`,
    and a tool registered under a different name than its function would go unprobed by every
    parametrized test below."""
    assert set(_emitted()) == set(_module_tool_names())


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_every_tool_has_a_non_empty_description(tool_name: str) -> None:
    """The description is the ONLY thing an agent reads before deciding to call a live write tool
    against a real tenant. An empty one is not a cosmetic defect."""
    desc = (_emitted()[tool_name].description or "").strip()
    assert desc, f"{tool_name} has no description"
    assert len(desc) >= 60, f"{tool_name}'s description is a stub ({len(desc)} chars): {desc!r}"
    assert desc.lower() != (_emitted()[tool_name].title or "").lower(), (
        f"{tool_name}'s description is just its title repeated"
    )


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_every_tool_has_a_human_title(tool_name: str) -> None:
    """A title is prose for a human picking from a list — not the identifier again."""
    title = (_emitted()[tool_name].title or "").strip()
    assert title, f"{tool_name} has no title"
    assert title != tool_name, f"{tool_name}'s title is just its own name"
    assert "_" not in title, f"{tool_name}'s title {title!r} is an identifier, not a human label"


def test_titles_are_unique_across_the_surface() -> None:
    """Two tools sharing one title makes the title useless exactly where it is used — a picker
    listing 60 entries. `kf_set_step_visibility` and `forge_set_visibility` both said "Rebuild step
    visibility" and are genuinely different tools (only the second takes `field_owners`)."""
    seen: dict[str, str] = {}
    for name, t in sorted(_emitted().items()):
        title = t.title or ""
        assert title not in seen, f"{name} and {seen[title]} share the title {title!r}"
        seen[title] = name


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_every_tool_carries_an_annotations_block_of_four_booleans(tool_name: str) -> None:
    """M2's contract, restated tool-agnostically: not "most tools have hints" but "a tool without
    all four hints cannot reach this surface"."""
    ann = _emitted()[tool_name].annotations
    assert ann is not None, f"{tool_name} has no annotations block"
    for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
        value = getattr(ann, hint, None)
        assert isinstance(value, bool), f"{tool_name}.{hint} is {value!r}, not a bool"


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_tool_hints_are_self_consistent(tool_name: str) -> None:
    """The hints are a claim about the SAME call, so they can contradict each other. A client that
    auto-approves read-only tools and confirms destructive ones cannot resolve a tool claiming
    both, and will pick one — whichever it picks, the caller was misled."""
    ann = _emitted()[tool_name].annotations
    assert not (ann.readOnlyHint and ann.destructiveHint), (
        f"{tool_name} claims readOnlyHint AND destructiveHint — a call that removes state is not "
        f"a read"
    )
    if ann.readOnlyHint:
        assert ann.idempotentHint, (
            f"{tool_name} is read-only but not idempotent — a call that writes nothing cannot "
            f"leave a different result the second time"
        )


# The tool's own prose, versus the hints. These two are a matched pair by construction: the M2
# finding was that FOUR tools' descriptions disagreed with what their bodies did, so a hint set
# derived from the body must be checked back against the prose, or the pair silently drifts again.
# Quoted spans are stripped first: `forge_grant_tier` names a permission tier "Read-only" as a
# VALUE — that is vocabulary, not a claim about the call.
_QUOTED_SPAN = re.compile(r'"[^"\n]*"|`[^`\n]*`')


def _unquoted(text: str) -> str:
    return _QUOTED_SPAN.sub(" ", text)


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_a_tool_that_calls_itself_destructive_in_prose_carries_the_hint(tool_name: str) -> None:
    t = _emitted()[tool_name]
    if re.search(r"\bdestructive\b", _unquoted(t.description or ""), re.I):
        assert t.annotations.destructiveHint is True, (
            f"{tool_name}'s own description says DESTRUCTIVE but its hint says otherwise"
        )


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_a_tool_that_calls_itself_read_only_in_prose_carries_the_hint(tool_name: str) -> None:
    t = _emitted()[tool_name]
    if re.search(r"\bread-only\b", _unquoted(t.description or ""), re.I):
        assert t.annotations.readOnlyHint is True, (
            f"{tool_name}'s own description says read-only but its hint says otherwise"
        )


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_a_tool_that_calls_itself_LIVE_is_marked_open_world(tool_name: str) -> None:
    """"LIVE (dev only)" is this codebase's fixed opening for a tool that reaches the tenant."""
    t = _emitted()[tool_name]
    if re.search(r"\bLIVE\b", _unquoted(t.description or "")):
        assert t.annotations.openWorldHint is True, (
            f"{tool_name} announces itself LIVE but is not marked openWorld"
        )


def test_the_prose_hint_lints_actually_match_something() -> None:
    """A lint that matches nothing passes forever. Pin the floor so deleting the word from every
    description cannot quietly retire the three checks above."""
    descs = [_unquoted(t.description or "") for t in _emitted().values()]
    assert sum(bool(re.search(r"\bdestructive\b", d, re.I)) for d in descs) >= 3
    assert sum(bool(re.search(r"\bread-only\b", d, re.I)) for d in descs) >= 5
    assert sum(bool(re.search(r"\bLIVE\b", d)) for d in descs) >= 30


# =================================================================================================
# 2. CITATIONS — every tool name mentioned resolves to a registered tool
# =================================================================================================

_TOOL_CITATION = re.compile(r"\b((?:kf|forge)_[a-z0-9_]+)")


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_every_tool_name_cited_in_a_description_resolves(tool_name: str) -> None:
    """A description is a set of instructions. "verify via forge_list_app_roles" when no such tool
    is registered is an instruction the caller CANNOT follow — and, worse, one it will try: an
    agent reading that line calls a name that does not exist and gets a protocol error nobody
    wrote a handler for. Found live on `forge_delete_app_role`, whose read-back instruction
    (doctrine 1: a delete response alone proves nothing) named a tool that was never registered;
    the tool now exists, because the instruction was right and the surface was missing."""
    registered = set(_emitted())
    cited = set(_TOOL_CITATION.findall(_emitted()[tool_name].description or ""))
    dangling = sorted(cited - registered)
    assert not dangling, f"{tool_name}'s description cites unregistered tool(s): {dangling}"


def test_the_citation_check_actually_sees_citations() -> None:
    """Anti-vacuity: these descriptions really do point at each other, a lot."""
    cited = {c for t in _emitted().values()
             for c in _TOOL_CITATION.findall(t.description or "")}
    assert len(cited) >= 15, f"only {len(cited)} distinct tool citations found — regex rotted?"


def test_every_tool_name_cited_anywhere_in_the_engine_resolves() -> None:
    """The same defect one layer down, and the one with teeth: `ApplyReport.remediation` is a tuple
    of TOOL NAMES that crosses the boundary as data ("this change was ignored; call these instead"),
    so a name that resolves to nothing is a dead end handed to the caller as a next step. Scanning
    the whole package rather than just those tuples costs nothing and caught a second one:
    `KfConfig.from_env` cited a `forge_use_app` tool that has never existed on this surface."""
    registered = set(_emitted())
    dangling: dict[str, list[str]] = {}
    for path in sorted(pathlib.Path(srv.__file__).parent.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for cited in _TOOL_CITATION.findall(line):
                if cited not in registered:
                    dangling.setdefault(cited, []).append(f"{path.name}:{lineno}")
    assert not dangling, f"engine cites unregistered tool(s): {dangling}"


# =================================================================================================
# 3. THE ENUM LINT (A2) — a documented vocabulary must reach the schema as a vocabulary
# =================================================================================================

# A2 was: 214 parameters, ZERO enums, while the engine already knew every one of those sets and
# the DOCSTRINGS already listed them out loud (`kind` is "process"/"form"/"case", `scope` is one of
# "apps"|"flows"|...). Prose is not a constraint: a typo still reached the engine, and in two cases
# went straight into a live API URL. The lint below is the general form of that finding — if a
# tool's own description enumerates a parameter's legal values, the schema must too.
_QUOTED_LITERAL = r'"[A-Za-z][\w \-]{0,24}"'
# an ALTERNATION of >=2 quoted literals: "a"/"b", "a" | "b", "a", "b", "a" or "b"
_ALTERNATION = re.compile(
    _QUOTED_LITERAL + r'(?:\s*(?:/|\||,|\s+or\s+)\s*' + _QUOTED_LITERAL + r')+')


def _is_open_string(schema: dict[str, Any]) -> bool:
    """True for a `str`-shaped parameter with no closed vocabulary. Pydantic emits `enum` for 2+
    members and `const` for exactly one, and wraps an optional in `anyOf` — all three count."""
    subs = [s for s in schema.get("anyOf", []) if isinstance(s, dict)]
    if any("enum" in s or "const" in s for s in [schema, *subs]):
        return False
    return "string" in {schema.get("type"), *(s.get("type") for s in subs)}


def enum_lint(description: str, properties: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """(parameter, enumerated values) for every parameter this description gives a closed set of
    values for while the schema still types it as a bare string.

    Attribution is to the NEAREST parameter name mentioned before the alternation, within one
    clause (90 chars) — the shape every one of these docstrings actually uses ("`kind` is
    "process"/"form"/"case""). An alternation introduced by a JSON key (`{"kind": "container"|
    "widget"|...}`) describes a key nested INSIDE a loosely-typed parameter, not the parameter
    itself: no JSON-Schema enum can express it (that is what tools.coerce_page_steps is for), so
    it is not a finding here.
    """
    found: list[tuple[str, list[str]]] = []
    for match in _ALTERNATION.finditer(description):
        before = description[:match.start()]
        if before.rstrip().endswith(('":', "':")):
            continue                                     # a nested JSON key, not a parameter
        window = before[-90:]
        nearest, position = None, -1
        for param, schema in properties.items():
            hit = None
            for hit in re.finditer(r"\b" + re.escape(param) + r"\b", window):
                pass                                     # the LAST mention wins — the nearest one
            if hit is not None and hit.start() > position and _is_open_string(schema):
                nearest, position = param, hit.start()
        if nearest is not None:
            values = re.findall(_QUOTED_LITERAL, match.group(0))
            found.append((nearest, [v.strip('"') for v in values]))
    return found


@pytest.mark.parametrize("tool_name", _module_tool_names())
def test_a_parameter_whose_description_enumerates_its_values_is_never_a_bare_string(
        tool_name: str) -> None:
    """The lint that stops A2 re-opening. A closed set stated only in prose is a set the caller can
    typo past, the schema will accept, and the engine will interpolate into a URL."""
    t = _emitted()[tool_name]
    findings = enum_lint(t.description or "", (t.inputSchema or {}).get("properties") or {})
    assert not findings, (
        f"{tool_name}: its description enumerates the legal values of "
        + "; ".join(f"`{p}` ({'/'.join(v)})" for p, v in findings)
        + " but the schema types it as an open string — type it as a typing.Literal so the "
          "enum reaches the caller (see server.py 'The boundary vocabulary')"
    )


def test_the_enum_lint_has_teeth_on_real_prose() -> None:
    """Proof the lint above is not passing because it sees nothing: take `forge_publish`'s REAL
    description and re-open its `kind` to a bare string, exactly the regression it exists to
    catch. If this stops firing, the lint has rotted and the check above is decorative."""
    real = _emitted()["forge_publish"].description or ""
    findings = enum_lint(real, {"kind": {"type": "string"}, "flow_id": {"type": "string"}})
    assert findings, "the enum lint no longer fires on forge_publish's own docstring"
    param, values = findings[0]
    assert param == "kind"
    assert {"process", "form", "case"} <= set(values)


def test_the_enum_lint_fires_on_every_vocabulary_the_boundary_currently_types() -> None:
    """Wider proof of teeth: with EVERY parameter artificially re-opened, the lint must rediscover
    the vocabularies the Literals now cover — otherwise it is only watching one docstring.

    Asserted per TOOL, not per parameter, because attribution to the nearest preceding parameter
    name is a heuristic and is sometimes off by one slot: `forge_grant_tier` documents its `tier`
    ladder inside the clause describing `kind` ("`kind` is "process" (tiers: "No access" | ...)"),
    so the lint names `kind`. That is fine for what the lint is FOR — it fires on the tool, quotes
    the values it found, and a human types the Literal on the right parameter."""
    hits = {(t.name, param)
            for t in _emitted().values()
            for param, _values in enum_lint(
                t.description or "",
                {p: {"type": "string"}
                 for p in ((t.inputSchema or {}).get("properties") or {})})}
    tools_that_fire = {name for name, _param in hits}
    assert {"forge_sweep", "kf_get_flow_schema", "forge_publish", "forge_grant_tier",
            "forge_approve_spec"} <= tools_that_fire, sorted(tools_that_fire)
    assert ("forge_sweep", "scope") in hits and ("kf_get_flow_schema", "flow_kind") in hits


def test_the_enum_lint_does_not_flag_a_vocabulary_that_lives_inside_a_nested_key() -> None:
    """`forge_build_page`'s `steps` is `list[Any]`; the alternation in its docstring belongs to the
    nested `"kind"` KEY of each step, which no JSON-Schema enum on `page_id` could ever express.
    Flagging it would make the lint unfixable, and an unfixable lint gets deleted."""
    desc = 'each step is `{"kind": "container"|"widget"|"popup", "kwargs": {...}}`'
    assert enum_lint(desc, {"page_id": {"type": "string"}}) == []


def test_the_enum_lint_flags_an_open_parameter_but_not_a_closed_one() -> None:
    """Both directions on one synthetic description, so a lint that flags everything (or nothing)
    fails here rather than being discovered by whoever it blocks."""
    desc = '`mode` is "fast"/"slow"/"careful".'
    assert enum_lint(desc, {"mode": {"type": "string"}}) == [
        ("mode", ["fast", "slow", "careful"])]
    assert enum_lint(desc, {"mode": {"type": "string",
                                     "enum": ["fast", "slow", "careful"]}}) == []
    assert enum_lint(desc, {"mode": {"anyOf": [{"type": "string",
                                                "enum": ["fast", "slow"]},
                                               {"type": "null"}]}}) == []


# =================================================================================================
# 4. THE RATCHETS — the two gaps bundle C could not close, pinned so they can only shrink
# =================================================================================================

# Every tool here returns `dict[str, Any]`, so FastMCP emits `{"type": "object"}` with no
# properties: a schema that describes nothing. Bundle C could not fix this without a result model
# per tool (59 of them, each mirroring a Report dataclass that already exists in kfforge.client /
# kfforge.pages_live), which is real follow-on work and not a boundary-annotation change.
#
# FOLLOW-ON: give each Report dataclass a TypedDict/model and annotate the tool's return type with
# it, then DELETE the tool's name from this list and lower the ceiling below. The list is the
# to-do; the ceiling is what stops it becoming a place to hide.
_VACUOUS_OUTPUT_SCHEMAS = frozenset({
    "forge_create_template_app",  # audit bundle: doctor + members + urls, shapes vary per run
    "kf_plan_field_change", "kf_get_flow_schema", "kf_apply_field_change", "kf_create_process",
    "kf_plan_step_visibility", "kf_set_step_visibility", "kf_publish",
    "forge_create_process", "forge_member_batch", "forge_add_member_roles",
    "forge_create_app_role", "forge_delete_app_role", "forge_list_app_roles",
    "forge_apply_fields", "forge_apply_layout", "forge_add_table", "forge_compare_to_spec",
    "forge_create_list", "forge_add_sequence_number", "forge_add_field_validation",
    "forge_build_workflow", "forge_add_goto_gate", "forge_set_branch_conditions",
    "forge_set_visibility", "forge_set_events", "forge_delete_fields", "forge_rename_fields",
    "forge_set_required", "forge_set_styles", "forge_publish", "forge_doctor",
    "forge_create_page", "forge_build_page", "forge_set_navigation", "forge_share_report",
    "forge_simulate_case", "forge_create_app", "forge_list_apps", "forge_delete_flow",
    "forge_add_role_users", "forge_grant_tier", "forge_create_flow", "forge_publish_app",
    "forge_dataset_records", "forge_set_role_preference", "forge_sweep", "forge_capabilities",
    "forge_playbook", "forge_copilot_ask", "forge_copilot_check", "forge_intake_questions",
    "forge_update_spec", "forge_render_flow_diagram", "forge_render_schema_diagram",
    "forge_render_mockups", "forge_request_confirmation", "forge_apply_revisions",
    "forge_approve_spec", "forge_plan_app",
})
_VACUOUS_OUTPUT_CEILING = 60       # SHRINK-ONLY. Lower it as tools gain a real result model.

# Not one of the 231 emitted parameters carries a `description`: FastMCP fills that from a
# per-parameter docstring section none of these docstrings has (they describe parameters in prose
# instead, which is why the enum lint above has to read the whole description). Bundle C typed the
# closed vocabularies; documenting every parameter is a separate pass.
#
# FOLLOW-ON: move each tool's per-parameter prose into an Args: section (or a Field(description=))
# so it reaches the schema, then lower this ceiling.
_UNDOCUMENTED_PARAM_CEILING = 231  # SHRINK-ONLY.


def _vacuous(tool: Any) -> bool:
    """An output schema that constrains nothing: absent, or an object with no declared properties.
    `kf_list_field_types` returns `list[str]` and gets a real one — the check can tell them
    apart, which is what makes the allowlist below meaningful."""
    schema = tool.outputSchema
    return not schema or (schema.get("type") == "object" and not schema.get("properties"))


def test_no_tool_outside_the_known_gap_ships_a_vacuous_output_schema() -> None:
    """The ratchet's forward edge: a NEW tool may not join the debt silently. Adding one to the
    allowlist also means raising the pinned ceiling below — a deliberate, visible act in the diff,
    which is the whole point."""
    newly = sorted(name for name, t in _emitted().items()
                   if _vacuous(t) and name not in _VACUOUS_OUTPUT_SCHEMAS)
    assert not newly, (
        f"{newly} ship an output schema that describes nothing. Declare a result model, or add "
        f"the name to _VACUOUS_OUTPUT_SCHEMAS and raise _VACUOUS_OUTPUT_CEILING on purpose"
    )


def test_the_vacuous_output_schema_allowlist_carries_no_stale_entries() -> None:
    """The ratchet's back edge: a tool that GAINED a real schema, or was deleted, must leave the
    list. Without this the list only ever grows and stops describing anything."""
    stale = sorted(name for name in _VACUOUS_OUTPUT_SCHEMAS
                   if name not in _emitted() or not _vacuous(_emitted()[name]))
    assert not stale, (
        f"{stale} no longer belong in _VACUOUS_OUTPUT_SCHEMAS — delete them and lower "
        f"_VACUOUS_OUTPUT_CEILING to {len(_VACUOUS_OUTPUT_SCHEMAS) - len(stale)}"
    )


def test_the_vacuous_output_schema_allowlist_only_shrinks() -> None:
    assert len(_VACUOUS_OUTPUT_SCHEMAS) <= _VACUOUS_OUTPUT_CEILING


def test_at_least_one_tool_already_ships_a_real_output_schema() -> None:
    """Anti-vacuity for the ratchet itself: if `_vacuous` called everything vacuous, the allowlist
    would be meaningless and the tests above would pass on a surface with no schemas at all."""
    real = sorted(name for name, t in _emitted().items() if not _vacuous(t))
    assert real == ["kf_list_field_types"], real


def test_undocumented_parameters_only_shrink() -> None:
    """The other pinned gap. Counted, not listed, because 231 names in a literal would be noise —
    the number is the debt, and it may only go down."""
    undocumented = [f"{name}.{param}" for name, t in _emitted().items()
                    for param, schema in (((t.inputSchema or {}).get("properties") or {}).items())
                    if not (schema.get("description") or "").strip()]
    assert len(undocumented) <= _UNDOCUMENTED_PARAM_CEILING, (
        f"{len(undocumented)} parameters carry no description, above the pinned ceiling of "
        f"{_UNDOCUMENTED_PARAM_CEILING} — document them, never raise the ceiling"
    )


def test_every_parameter_that_has_a_description_has_a_useful_one() -> None:
    """As the ceiling above comes down, this is what the descriptions being added are held to."""
    for name, t in _emitted().items():
        for param, schema in ((t.inputSchema or {}).get("properties") or {}).items():
            desc = (schema.get("description") or "").strip()
            if not desc:
                continue
            assert len(desc) > len(param), f"{name}.{param}'s description restates its name"


# =================================================================================================
# 5. THE FLAG (C1) — a payload failure is a PROTOCOL failure, at the surface and at the mechanism
# =================================================================================================

def _call(tool: str, args: dict[str, Any]) -> Any:
    from fastmcp import Client

    async def _run() -> Any:
        # raise_on_error=False so the RESULT is inspectable — the raising path swallows the very
        # flag under test into a ToolError string.
        async with Client(srv.mcp) as client:
            return await client.call_tool(tool, args, raise_on_error=False)

    return asyncio.run(_run())


@pytest.mark.parametrize("tool_name, args", [
    ("kf_get_flow_schema", {"flow_kind": "process", "flow_id": "F"}),   # a live READ
    ("forge_apply_fields", {"flow_id": "F", "fields": []}),             # a live WRITE
    ("forge_doctor", {"flow_id": "F"}),                                 # a live audit
    ("forge_sweep", {"scope": "apps"}),                                 # a live inventory
])
def test_a_payload_level_failure_is_also_a_protocol_level_failure(
        tool_name: str, args: dict[str, Any], no_kf_env: None) -> None:
    """C1, at the surface: these tools report failure as DATA (doctrine 7 — errors cross the tool
    boundary as the frozen `Err`, never as an exception), and MCP defines `isError` on the result
    ENVELOPE. Because they RETURN rather than raise, the envelope flag stayed False and every
    failure read as a protocol SUCCESS to any gateway, dashboard or retry layer. Both flags, one
    call: the payload key ~40 other tests read, and the envelope flag the protocol promises."""
    result = _call(tool_name, args)
    assert result.structured_content is not None, tool_name
    assert result.structured_content.get("isError") is True, result.structured_content
    assert result.is_error is True, (
        f"{tool_name} reported isError in its PAYLOAD but the protocol envelope says success: "
        f"{result.structured_content}"
    )


def test_the_isError_promotion_middleware_is_installed_on_the_server() -> None:
    """The promotion is ONE line (`mcp.add_middleware(_PromoteIsErrorToProtocol())`) covering all
    60 tools. Deleting that line breaks every tool at once and no tool body changes, so nothing
    else in this repo would point at it."""
    installed = [type(m).__name__ for m in srv.mcp.middleware]
    assert "_PromoteIsErrorToProtocol" in installed, installed


def test_the_promotion_is_a_middleware_not_a_per_tool_habit() -> None:
    """The mechanism itself, on a throwaway server carrying ONLY that middleware and two synthetic
    tools. This is what proves a tool added tomorrow inherits the fix without knowing about it —
    and it keeps proving it if every forge_* tool in this repo is rewritten."""
    from fastmcp import Client, FastMCP

    probe = FastMCP("promotion-probe")
    probe.add_middleware(srv._PromoteIsErrorToProtocol())

    @probe.tool(title="Fails")
    def fails() -> dict[str, Any]:
        """A tool that reports failure the way every tool in kfforge.server does."""
        return {"isError": True, "error": "verify: nope"}

    @probe.tool(title="Succeeds")
    def succeeds() -> dict[str, Any]:
        """The other half of the invariant: a real success stays a success."""
        return {"isError": False, "added": ["a"]}

    async def _run() -> tuple[Any, Any]:
        async with Client(probe) as client:
            return (await client.call_tool("fails", {}, raise_on_error=False),
                    await client.call_tool("succeeds", {}, raise_on_error=False))

    failed, ok = asyncio.run(_run())
    assert failed.is_error is True
    assert failed.structured_content == {"isError": True, "error": "verify: nope"}, (
        "the promotion must set the envelope flag WITHOUT touching the payload"
    )
    assert ok.is_error is False and ok.structured_content["isError"] is False


# =================================================================================================
# 6. THE JOINS — the review's three headline reproductions, on the far side of the tool boundary
# =================================================================================================
# Each defect already has a permanent regression test inside its own module (F1 in
# tests/test_graph.py, F2 in tests/test_client.py, M1 in tests/test_mcp_boundary.py). What no test
# covered is the trip OUT: a defect can be fixed in the engine and still be invisible, or still
# escape as an exception, by the time it reaches an MCP caller. These three close that gap.

def test_an_off_grid_layout_span_leaves_the_boundary_as_data_not_a_traceback(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """F1, on the far side of the boundary. `graph.validate_layout_spans` (bundle A) refuses a
    span past the 6-unit row by RAISING — correct inside a pure transform, and a bare traceback if
    it reaches the tool boundary unhandled (doctrine 7). `apply_layout` catches it, and this is the
    test that says so from outside. The draft must also be untouched: a refused spec is refused
    BEFORE the deepcopy, so nothing may have been PUT."""
    from kfforge.client import apply_fields_and_layout
    from kfforge.types import FieldSpec, FieldType

    fake = FakeClient(_bare_form_draft())
    apply_fields_and_layout(fake, "form", "F1",
                            [FieldSpec(name=n, type=FieldType.TEXT) for n in ("a", "b")],
                            groups=[("G", ["a", "b"])])
    monkeypatch.setattr(srv, "_client", lambda *a, **k: fake)
    puts_before = fake.puts

    got = srv.forge_apply_layout(flow_id="F1", layout={"G": [[["a", 0, 99]]]}, kind="form")

    assert isinstance(got, dict), f"the boundary returned {type(got).__name__}"
    assert got["isError"] is True, got
    assert "0" in got["error"] and "99" in got["error"], got
    assert fake.puts == puts_before, "a refused layout spec must never reach a PUT"


def test_a_silently_ignored_type_change_is_an_error_on_the_protocol_envelope(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """F2 (bundle B) meeting M1 (bundle C) — the join neither bundle could make alone.

    `graph.apply_changes` only ever CREATES, so asking for a different Type on an EXISTING field
    name is a silent no-op that used to be counted under `skipped` AND `verified` at once: a clean
    success for a change that never happened. It now lands in `changed_ignored`, which sets the
    payload's `isError`. This asserts the whole chain: the bucket, the payload flag it drives, the
    remediation the caller is owed — and that the ENVELOPE says error too, because a caller that
    only reads the protocol flag (which is all MCP promises it) would otherwise still see the
    silent drop as a success."""
    from kfforge.types import FieldType

    fake = FakeClient(_bare_form_draft())
    monkeypatch.setattr(srv, "_client", lambda *a, **k: fake)

    first = srv.kf_apply_field_change("form", "F1", [{"name": "alpha", "type": "Text"}])
    assert first["isError"] is False and first["added"] == ["alpha"]

    args = {"flow_kind": "form", "flow_id": "F1",
            "changes": [{"name": "alpha", "type": FieldType.NUMBER.value}]}
    second = srv.kf_apply_field_change(**args)
    assert second["changed_ignored"], "the ignored change must land in its own bucket"
    assert second["verified"] == [] and second["skipped"] == [], (
        "one record, ONE bucket — it used to be counted under skipped AND verified at once"
    )
    assert second["remediation"] == ["forge_delete_fields", "forge_apply_fields"]
    assert second["isError"] is True

    result = _call("kf_apply_field_change", args)
    assert result.structured_content["changed_ignored"], result.structured_content
    assert result.is_error is True, (
        "a change this engine silently dropped still reads as a protocol SUCCESS on the wire"
    )


def test_a_report_carrying_only_collateral_damage_is_not_reported_as_an_error() -> None:
    """The other half of the F2/M1 join, on the same mechanism: `collateral` (bundle A4 — what a
    write destroyed or moved that the caller never named) is a WARNING, not a failure. A promotion
    that fired on any non-empty report field would turn every honest partial-layout call into a
    protocol error and train callers to ignore the flag."""
    warned = ApplyReport(flow_id="F1", added=("a",), skipped=(), verified=("a",), missing=(),
                         changed_ignored=(), collateral=("'b' was re-tiled",),
                         remediation=("forge_apply_layout",), meta_version="v2", published=False)
    assert warned.as_tool_result()["isError"] is False

    failed = ApplyReport(flow_id="F1", added=(), skipped=(), verified=(), missing=(),
                         changed_ignored=("'alpha' asked for Number, live is Text",),
                         collateral=(), remediation=("forge_delete_fields",),
                         meta_version="v2", published=False)
    assert failed.as_tool_result()["isError"] is True


# =================================================================================================
# The tool the surface was missing — registered because its own citation demanded it (see
# test_every_tool_name_cited_in_a_description_resolves). A new tool needs its own behavior test:
# the checks above prove it is well-FORMED, never that it reads the right thing.
# =================================================================================================

def test_forge_list_app_roles_returns_only_the_roles_scoped_to_the_app(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The account route pages the WHOLE account (356 roles in the probe tenant — CLAUDE.md
    leakage), so this tool always filters to one application."""
    fake = FakeClient(_bare_form_draft())
    fake.app_roles = [
        {"_id": "Ro1", "Name": "Requester", "_application_id": "App_here"},
        {"_id": "Ro2", "Name": "Approver",
         "Applications": [{"_id": "App_here", "Type": "Application"}]},
        {"_id": "Ro3", "Name": "Elsewhere", "_application_id": "App_other"},
    ]
    monkeypatch.setattr(srv, "_client", lambda *a, **k: fake)

    got = srv.forge_list_app_roles(app_id="App_here")

    assert got["isError"] is False
    assert got["roles"] == [{"_id": "Ro1", "Name": "Requester"},
                            {"_id": "Ro2", "Name": "Approver"}]
    assert got["count"] == 2 and got["app_id"] == "App_here"


def test_forge_list_app_roles_is_the_read_back_forge_delete_app_role_names(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctrine 1, end to end: a delete response alone proves nothing (`delete_app_role` returns
    `{"status":"success"}`), so the deletion is only a fact once the LIST route stops carrying the
    role. That instruction has been in `forge_delete_app_role`'s description all along, naming a
    tool nobody had registered."""
    fake = FakeClient(_bare_form_draft())
    fake.app_roles = [{"_id": "Ro1", "Name": "Throwaway", "_application_id": "App_here"}]
    monkeypatch.setattr(srv, "_client", lambda *a, **k: fake)

    assert srv.forge_delete_app_role(role_id="Ro1", app_id="App_here")["deleted"] is True
    after = srv.forge_list_app_roles(app_id="App_here")
    assert after["roles"] == [] and after["count"] == 0


def test_forge_list_app_roles_fails_gracefully_with_no_credentials(no_kf_env: None) -> None:
    got = srv.forge_list_app_roles()
    assert got["isError"] is True and got["error"].startswith("config:")


def test_every_client_is_told_the_group_rule_in_the_handshake() -> None:
    """The group broadcast is the one mistake on this surface whose cost lands on OTHER PEOPLE,
    and it cannot be undone (membership writes are add-only). A tool description is read only when
    that tool is considered and `forge_playbook` only when someone thinks to fetch it, so the rule
    also has to travel in `instructions` — the one channel every connecting client receives in the
    initialize handshake, before any tool is listed or called."""
    import asyncio

    from fastmcp import Client

    from kfforge.server import mcp

    async def _handshake() -> str:
        async with Client(mcp) as client:
            return client.initialize_result.instructions or ""

    instructions = asyncio.run(_handshake())

    assert instructions.strip(), "the server must ship instructions"
    assert "NEVER GRANT A GROUP" in instructions
    assert "CANNOT BE UNDONE" in instructions
    assert "user_query" in instructions, "must name the safe way to test membership"
    assert "confirm_group_notification" in instructions, "must name the flag that gates it"


def test_the_group_rule_also_rides_the_tool_that_enforces_it() -> None:
    """Belt and braces: an agent that skips the handshake briefing still meets the rule on the
    tool itself, and on the parameter it applies to."""
    tool = _emitted()["forge_add_role_users"]

    assert "confirm_group_notification" in (tool.description or "")
    props = (tool.inputSchema or {}).get("properties") or {}
    assert "EMAILS every member" in (props["groups"].get("description") or "")
    assert "email every member" in (props["confirm_group_notification"].get("description") or "")
