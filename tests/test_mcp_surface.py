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

Five axes now (Stage E retired axis 5, the isError-promotion middleware, along with the isError
payload dict it promoted -- every tool raises `ToolError` on failure now, which IS a protocol-level
failure by construction; `scripts/arch_scan.py`'s `iserror_dicts` scan pins that at 0):
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
                    cannot grow silently, and goes away by being deleted from a list. Stage E
                    (the Pydantic response DTOs, spec G10) paid off most of the vacuous-schema
                    debt: the allowlist below shrank from 60 tools to 12 -- the ones a
                    `@model_serializer` (payload-parity, `brief_stage_d_common.md` lesson 15)
                    or a `RootModel[dict[str, Any]]` response still leaves unconstrained.

Deliberately NOT duplicated from tests/test_mcp_boundary.py: that file proves each individual fix
(which hint each tool should carry, which enum matches which engine constant, which malformed
argument produces which refusal). This one proves the SHAPE OF THE SURFACE, tool-agnostically, so
a tool added tomorrow is held to the same contract without anyone remembering to add it here.

Stage E moved every tool off `server.py`'s own module-level `mcp` and into the family modules
`create_server(lifespan)` registers -- `_emitted()` now builds that server (a fake lifespan; no
real Kissflow adapter, no real network) instead of reading `app.infrastructure.mcp.server.mcp`,
and is the single source of truth for both parametrization and lookup (the old
`_module_tool_names()`'s `dir(srv)` scan caught a tool whose `@mcp.tool` decoration silently left
the plain function in the module namespace -- that defect class cannot occur on the new surface at
all, since no individual tool is ever a module-level attribute of `server.py` to begin with).
"""

from __future__ import annotations

import asyncio
import functools
import pathlib
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.infrastructure.mcp.server import create_server


@functools.lru_cache(maxsize=1)
def _emitted() -> dict[str, Any]:
    """name -> the REAL emitted MCP tool. Built once: booting the server is the expensive part,
    and every test in this file wants the same immutable listing."""
    from fastmcp import Client, FastMCP

    @asynccontextmanager
    async def _fake_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": None, "settings": None}

    async def _run() -> list[Any]:
        async with Client(create_server(_fake_lifespan)) as client:
            return await client.list_tools()

    return {t.name: t for t in asyncio.run(_run())}


# =================================================================================================
# 1. PER TOOL — description, title, annotations
# =================================================================================================


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_every_tool_has_a_non_empty_description(tool_name: str) -> None:
    """The description is the ONLY thing an agent reads before deciding to call a live write tool
    against a real tenant. An empty one is not a cosmetic defect."""
    desc = (_emitted()[tool_name].description or "").strip()
    assert desc, f"{tool_name} has no description"
    assert len(desc) >= 60, (
        f"{tool_name}'s description is a stub ({len(desc)} chars): {desc!r}"
    )
    assert desc.lower() != (_emitted()[tool_name].title or "").lower(), (
        f"{tool_name}'s description is just its title repeated"
    )


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_every_tool_has_a_human_title(tool_name: str) -> None:
    """A title is prose for a human picking from a list — not the identifier again."""
    title = (_emitted()[tool_name].title or "").strip()
    assert title, f"{tool_name} has no title"
    assert title != tool_name, f"{tool_name}'s title is just its own name"
    assert "_" not in title, (
        f"{tool_name}'s title {title!r} is an identifier, not a human label"
    )


def test_titles_are_unique_across_the_surface() -> None:
    """Two tools sharing one title makes the title useless exactly where it is used — a picker
    listing 60 entries. `kf_set_step_visibility` and `forge_set_visibility` both said "Rebuild step
    visibility" and are genuinely different tools (only the second takes `field_owners`)."""
    seen: dict[str, str] = {}
    for name, t in sorted(_emitted().items()):
        title = t.title or ""
        assert title not in seen, f"{name} and {seen[title]} share the title {title!r}"
        seen[title] = name


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_every_tool_carries_an_annotations_block_of_four_booleans(
    tool_name: str,
) -> None:
    """M2's contract, restated tool-agnostically: not "most tools have hints" but "a tool without
    all four hints cannot reach this surface"."""
    ann = _emitted()[tool_name].annotations
    assert ann is not None, f"{tool_name} has no annotations block"
    for hint in (
        "read_only_hint",
        "destructive_hint",
        "idempotent_hint",
        "open_world_hint",
    ):
        value = getattr(ann, hint, None)
        assert isinstance(value, bool), f"{tool_name}.{hint} is {value!r}, not a bool"


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_tool_hints_are_self_consistent(tool_name: str) -> None:
    """The hints are a claim about the SAME call, so they can contradict each other. A client that
    auto-approves read-only tools and confirms destructive ones cannot resolve a tool claiming
    both, and will pick one — whichever it picks, the caller was misled."""
    ann = _emitted()[tool_name].annotations
    assert not (ann.read_only_hint and ann.destructive_hint), (
        f"{tool_name} claims readOnlyHint AND destructiveHint — a call that removes state is not "
        f"a read"
    )
    if ann.read_only_hint:
        assert ann.idempotent_hint, (
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


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_a_tool_that_calls_itself_destructive_in_prose_carries_the_hint(
    tool_name: str,
) -> None:
    t = _emitted()[tool_name]
    if re.search(r"\bdestructive\b", _unquoted(t.description or ""), re.I):
        assert t.annotations.destructive_hint is True, (
            f"{tool_name}'s own description says DESTRUCTIVE but its hint says otherwise"
        )


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_a_tool_that_calls_itself_read_only_in_prose_carries_the_hint(
    tool_name: str,
) -> None:
    t = _emitted()[tool_name]
    if re.search(r"\bread-only\b", _unquoted(t.description or ""), re.I):
        assert t.annotations.read_only_hint is True, (
            f"{tool_name}'s own description says read-only but its hint says otherwise"
        )


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_a_tool_that_calls_itself_LIVE_is_marked_open_world(tool_name: str) -> None:
    """ "LIVE (dev only)" is this codebase's fixed opening for a tool that reaches the tenant."""
    t = _emitted()[tool_name]
    if re.search(r"\bLIVE\b", _unquoted(t.description or "")):
        assert t.annotations.open_world_hint is True, (
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


def test_the_citation_regex_catches_a_citation_immediately_after_a_dot() -> None:
    """G2 added a `(?<!\\.)` lookbehind here to exclude an attribute access such as
    `settings.kf_dev_access_key_id`; the P1 review found that G4 had since deleted
    that code outright, so the exclusion no longer protected anything and only
    weakened the check going forward -- it would silently hide a genuine dangling
    citation sitting right after a dot (end of a sentence with no space, a chained
    example, ...). Restored to the plain form, which must catch a citation in exactly
    that position."""
    assert _TOOL_CITATION.findall("see helper.forge_ghost_tool for details") == [
        "forge_ghost_tool"
    ]


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
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
    assert not dangling, (
        f"{tool_name}'s description cites unregistered tool(s): {dangling}"
    )


def test_the_citation_check_actually_sees_citations() -> None:
    """Anti-vacuity: these descriptions really do point at each other, a lot."""
    cited = {
        c
        for t in _emitted().values()
        for c in _TOOL_CITATION.findall(t.description or "")
    }
    assert len(cited) >= 15, (
        f"only {len(cited)} distinct tool citations found — regex rotted?"
    )


def test_every_tool_name_cited_anywhere_in_the_engine_resolves() -> None:
    """The same defect one layer down, and the one with teeth: `ApplyReport.remediation` is a tuple
    of TOOL NAMES that crosses the boundary as data ("this change was ignored; call these instead"),
    so a name that resolves to nothing is a dead end handed to the caller as a next step. Scanning
    the whole package rather than just those tuples costs nothing and caught a second one:
    `KfConfig.from_env` cited a `forge_use_app` tool that has never existed on this surface.

    Skips `from `/`import ` lines (spec G10/G12, Stage D): a DTO module is named exactly
    `<tool>_request.py`/`<tool>_response.py`, so its own import line's dotted path
    legitimately contains a real tool name immediately followed by `_request`/
    `_response` -- module plumbing no caller ever reads, never "an instruction the
    caller cannot follow" (the axis this test actually guards, see the docstring
    above). A citation in a docstring, an error message, or any other line is still
    caught."""
    registered = set(_emitted())
    dangling: dict[str, list[str]] = {}
    import app.infrastructure.mcp.server as srv_module

    for path in sorted(pathlib.Path(srv_module.__file__).parent.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith(("from ", "import ")):
                continue
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
    _QUOTED_LITERAL + r"(?:\s*(?:/|\||,|\s+or\s+)\s*" + _QUOTED_LITERAL + r")+"
)


def _is_open_string(schema: dict[str, Any]) -> bool:
    """True for a `str`-shaped parameter with no closed vocabulary. Pydantic emits `enum` for 2+
    members and `const` for exactly one, and wraps an optional in `anyOf` — all three count."""
    subs = [s for s in schema.get("anyOf", []) if isinstance(s, dict)]
    if any("enum" in s or "const" in s for s in [schema, *subs]):
        return False
    return "string" in {schema.get("type"), *(s.get("type") for s in subs)}


def enum_lint(
    description: str, properties: dict[str, Any]
) -> list[tuple[str, list[str]]]:
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
        before = description[: match.start()]
        if before.rstrip().endswith(('":', "':")):
            continue  # a nested JSON key, not a parameter
        window = before[-90:]
        nearest, position = None, -1
        for param, schema in properties.items():
            hit = None
            # B007 stays: `hit` is read AFTER the loop on purpose — last-match-wins, so
            # the control variable IS the result, not a dead name.
            for hit in re.finditer(r"\b" + re.escape(param) + r"\b", window):  # noqa: B007
                pass  # the LAST mention wins — the nearest one
            if hit is not None and hit.start() > position and _is_open_string(schema):
                nearest, position = param, hit.start()
        if nearest is not None:
            values = re.findall(_QUOTED_LITERAL, match.group(0))
            found.append((nearest, [v.strip('"') for v in values]))
    return found


@pytest.mark.parametrize("tool_name", sorted(_emitted()))
def test_a_parameter_whose_description_enumerates_its_values_is_never_a_bare_string(
    tool_name: str,
) -> None:
    """The lint that stops A2 re-opening. A closed set stated only in prose is a set the caller can
    typo past, the schema will accept, and the engine will interpolate into a URL."""
    t = _emitted()[tool_name]
    findings = enum_lint(
        t.description or "", (t.input_schema or {}).get("properties") or {}
    )
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
    findings = enum_lint(
        real, {"kind": {"type": "string"}, "flow_id": {"type": "string"}}
    )
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
    hits = {
        (t.name, param)
        for t in _emitted().values()
        for param, _values in enum_lint(
            t.description or "",
            {
                p: {"type": "string"}
                for p in ((t.input_schema or {}).get("properties") or {})
            },
        )
    }
    tools_that_fire = {name for name, _param in hits}
    assert {
        "forge_sweep",
        "kf_get_flow_schema",
        "forge_publish",
        "forge_grant_tier",
        "forge_approve_spec",
    } <= tools_that_fire, sorted(tools_that_fire)
    assert ("forge_sweep", "scope") in hits and (
        "kf_get_flow_schema",
        "flow_kind",
    ) in hits


def test_the_enum_lint_does_not_flag_a_vocabulary_that_lives_inside_a_nested_key() -> (
    None
):
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
        ("mode", ["fast", "slow", "careful"])
    ]
    assert (
        enum_lint(
            desc, {"mode": {"type": "string", "enum": ["fast", "slow", "careful"]}}
        )
        == []
    )
    assert (
        enum_lint(
            desc,
            {
                "mode": {
                    "anyOf": [
                        {"type": "string", "enum": ["fast", "slow"]},
                        {"type": "null"},
                    ]
                }
            },
        )
        == []
    )


# =================================================================================================
# 4. THE RATCHETS — the two gaps bundle C could not close, pinned so they can only shrink
# =================================================================================================

# Stage E gave every tool a real Pydantic response DTO (spec G10), which paid off nearly all of
# this debt: the allowlist below shrank from 60 tools (every tool once returned a bare
# `dict[str, Any]`) to these 12, each vacuous for its own new-architecture reason rather than the
# old blanket one:
#   - kf_get_flow_schema, forge_set_visibility, kf_plan_step_visibility, kf_set_step_visibility:
#     `RootModel[dict[str, Any]]` responses (the draft graph itself, or a bounded free-form report)
#     -- `dict[str, Any]` constrains nothing regardless of which model wraps it.
#   - forge_add_role_users, forge_build_page, forge_capabilities, forge_create_flow,
#     forge_create_process, forge_dataset_records, forge_publish, kf_create_process: a
#     `@model_serializer(mode="wrap")` response (payload parity, `brief_stage_d_common.md`
#     lesson 15 -- an optional key the old success dict left out when empty must stay out of the
#     new one too). Pydantic cannot introspect a custom serializer function to build a real output
#     schema from it.
#
# FOLLOW-ON: none of these twelve can gain a real schema without giving up payload parity with the
# old success dict or the free-form draft/report shape the tool has always returned -- there is no
# further "declare a result model" step waiting here, unlike the old debt.
_VACUOUS_OUTPUT_SCHEMAS = frozenset(
    {
        "forge_add_role_users",
        "forge_build_page",
        "forge_capabilities",
        "forge_create_flow",
        "forge_create_process",
        "forge_dataset_records",
        "forge_publish",
        "forge_set_visibility",
        "kf_create_process",
        "kf_get_flow_schema",
        "kf_plan_step_visibility",
        "kf_set_step_visibility",
    }
)
_VACUOUS_OUTPUT_CEILING = 12  # SHRINK-ONLY. Lower it as tools gain a real result model.

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
    schema = tool.output_schema
    return not schema or (
        schema.get("type") == "object" and not schema.get("properties")
    )


def test_no_tool_outside_the_known_gap_ships_a_vacuous_output_schema() -> None:
    """The ratchet's forward edge: a NEW tool may not join the debt silently. Adding one to the
    allowlist also means raising the pinned ceiling below — a deliberate, visible act in the diff,
    which is the whole point."""
    newly = sorted(
        name
        for name, t in _emitted().items()
        if _vacuous(t) and name not in _VACUOUS_OUTPUT_SCHEMAS
    )
    assert not newly, (
        f"{newly} ship an output schema that describes nothing. Declare a result model, or add "
        f"the name to _VACUOUS_OUTPUT_SCHEMAS and raise _VACUOUS_OUTPUT_CEILING on purpose"
    )


def test_the_vacuous_output_schema_allowlist_carries_no_stale_entries() -> None:
    """The ratchet's back edge: a tool that GAINED a real schema, or was deleted, must leave the
    list. Without this the list only ever grows and stops describing anything."""
    stale = sorted(
        name
        for name in _VACUOUS_OUTPUT_SCHEMAS
        if name not in _emitted() or not _vacuous(_emitted()[name])
    )
    assert not stale, (
        f"{stale} no longer belong in _VACUOUS_OUTPUT_SCHEMAS — delete them and lower "
        f"_VACUOUS_OUTPUT_CEILING to {len(_VACUOUS_OUTPUT_SCHEMAS) - len(stale)}"
    )


def test_the_vacuous_output_schema_allowlist_only_shrinks() -> None:
    assert len(_VACUOUS_OUTPUT_SCHEMAS) <= _VACUOUS_OUTPUT_CEILING


def test_at_least_one_tool_already_ships_a_real_output_schema() -> None:
    """Anti-vacuity for the ratchet itself: if `_vacuous` called everything vacuous, the allowlist
    would be meaningless and the tests above would pass on a surface with no schemas at all.

    Stage E's response DTOs (spec G10) mean this is no longer just `kf_list_field_types` (the one
    real schema left from the old `dict[str, Any]`-everywhere surface) -- most of the 61 tools now
    carry a real one, so this pins a floor rather than the exact set (the exact set is each DTO's
    own job, proven under `tests/unit/application/models/responses/`)."""
    real = sorted(name for name, t in _emitted().items() if not _vacuous(t))
    assert "kf_list_field_types" in real
    assert len(real) >= 40, sorted(set(_emitted()) - set(real))


def test_undocumented_parameters_only_shrink() -> None:
    """The other pinned gap. Counted, not listed, because 231 names in a literal would be noise —
    the number is the debt, and it may only go down."""
    undocumented = [
        f"{name}.{param}"
        for name, t in _emitted().items()
        for param, schema in (((t.input_schema or {}).get("properties") or {}).items())
        if not (schema.get("description") or "").strip()
    ]
    assert len(undocumented) <= _UNDOCUMENTED_PARAM_CEILING, (
        f"{len(undocumented)} parameters carry no description, above the pinned ceiling of "
        f"{_UNDOCUMENTED_PARAM_CEILING} — document them, never raise the ceiling"
    )


def test_every_parameter_that_has_a_description_has_a_useful_one() -> None:
    """As the ceiling above comes down, this is what the descriptions being added are held to."""
    for name, t in _emitted().items():
        for param, schema in ((t.input_schema or {}).get("properties") or {}).items():
            desc = (schema.get("description") or "").strip()
            if not desc:
                continue
            assert len(desc) > len(param), (
                f"{name}.{param}'s description restates its name"
            )


# =================================================================================================
# Stage E removed sections 5 and 6 (the isError-promotion middleware and its mechanism test, the
# F1/F2/collateral "trip out through the boundary" joins, the forge_list_app_roles behavior tests,
# and the group-broadcast handshake tests) rather than porting them:
#   - Section 5 tested `_PromoteIsErrorToProtocol`, deleted with the rest of the old `server.py`
#     (spec G12) -- every new tool raises `ToolError` on failure, so a payload-level failure IS a
#     protocol-level failure by construction; there is no longer a payload `isError` dict to
#     promote (`scripts/arch_scan.py`'s `iserror_dicts` scan pins the count at 0).
#   - `test_an_off_grid_layout_span_leaves_the_boundary_as_data_not_a_traceback` and
#     `test_a_silently_ignored_type_change_is_an_error_on_the_protocol_envelope` (F1/F2 joins) and
#     `test_a_report_carrying_only_collateral_damage_is_not_reported_as_an_error`: their new-
#     architecture equivalent ("an ApplicationError raised by the use case reaches the caller as a
#     ToolError with the same message, never a bare traceback and never a silent success") is
#     proven per-tool in `tests/unit/infrastructure/mcp/tools/test_flow.py` (forge_apply_layout,
#     kf_apply_field_change) -- see `brief_stage_d_common.md` lesson 7.
#   - `test_forge_list_app_roles_returns_only_the_roles_scoped_to_the_app`,
#     `test_forge_list_app_roles_is_the_read_back_forge_delete_app_role_names` and
#     `test_forge_list_app_roles_fails_gracefully_with_no_credentials`: ported to
#     `tests/unit/application/use_cases/app/test__roles.py`/`test_forge_list_app_roles.py`/
#     `test_forge_delete_app_role.py` (Stage D group 5, `stage_d_ported.md`).
#   - `test_every_client_is_told_the_group_rule_in_the_handshake` and
#     `test_the_group_rule_also_rides_the_tool_that_enforces_it`: ported verbatim to
#     `tests/unit/infrastructure/mcp/tools/test_app.py` (Stage D group 5).
# =================================================================================================
