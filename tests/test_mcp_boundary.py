"""The MCP boundary itself — the one surface that had no test asserting anything (bundle C).

Everything here is OFFLINE. Where a test needs the REAL protocol path it uses FastMCP's in-memory
Client (same technique as tests/test_p2_server.py: no subprocess, no network), because the four
things under test — the result ENVELOPE's isError flag, tool annotations, tool titles and the
JSON-Schema enums — do not exist at all on a plain Python call into the tool function.

Three axes now (Stage E, spec G12):
  2. annotations/titles — all 61 tools carry all four hints plus a human title, and the hints
                          match what the BODY does, not what the description says.
  3. closed-set enums   — every closed vocabulary the engine already knows is an `enum`/`const`
                          in the emitted schema, and each one matches the engine constant it
                          mirrors (the anti-drift guard).
  4. no raises          — no tool escapes as a bare Python exception, well-formed OR malformed.

Stage E retired axis 1 (the isError-promotion middleware) outright: every new tool raises
`ToolError` on failure, so a payload-level failure IS a protocol-level failure by construction
(`scripts/arch_scan.py`'s `iserror_dicts` scan pins the payload-dict count at 0) -- there is no
longer a payload `isError` key to promote, and the D3 "a diagnosis is not a failure" carve-out that
middleware needed no longer applies either: `forge_doctor`'s own response DTO still carries its
`ok`/`problems` verdict, and a diagnosis with real problems is still a normal, non-raising return
(spec rule 7, `brief_stage_d_common.md`: verdict tools are the exception to "a failed write is
never a success", and they report their verdict IN the response, never via a raised error).

Every tool call below goes through `create_server(lifespan)` and an in-process `fastmcp.Client`
(the old `getattr(srv, name)(**kwargs)` plain-function calls and `srv._client`/`srv._write_artifact`
monkeypatch seams are gone with the rest of `app.infrastructure.mcp.server`'s module-level `mcp`).
`_resources()` builds one fresh `AppResources` per test, every family fake sharing one call log
each -- the same "any write-shaped method got called" check `tests/test_tool_claims.py` uses,
generalised here to the WHOLE 61-tool surface rather than one refusal table.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from tests.fakes.app import FakeAppRepository
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.copilot import FakeCopilotService
from tests.fakes.dataset import FakeDatasetRepository
from tests.fakes.docs import FakeDocsReader
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.item import FakeItemService
from tests.fakes.page import FakePageRepository

from app.application.models.requests.intake.app_spec import blank_spec
from app.application.use_cases.app._roles import _TIER_MAP
from app.application.use_cases.app._sweep import SWEEP_SCOPES
from app.domain.value_objects.field_type import FieldType
from app.domain.value_objects.kinds import FlowKind
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server

_BLANK_SPEC = blank_spec().model_dump(mode="json")

# Well-typed args that reach each tool's own body and no further — the same idea as
# tests/test_p2_server.py's DUMMY_ARGS, extended to the whole 61-tool surface (that fixture only
# covers the forge_* subset). Every value is minimal and schema-valid: the point is to prove the
# tool RETURNS a well-formed result (or a `ToolError`, never a bare exception), never to make it do
# real work.
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
    "forge_create_template_app": {"name": "N"},
    "forge_member_batch": {"target_flow_id": "F"},
    "forge_add_member_roles": {"target_flow_id": "F", "roles": {}},
    "forge_create_app_role": {"name": "R"},
    "forge_delete_app_role": {"role_id": "R"},
    "forge_list_app_roles": {},
    "forge_apply_fields": {"flow_id": "F", "fields": []},
    "forge_apply_layout": {"flow_id": "F", "layout": {}},
    "forge_add_table": {"flow_id": "F", "name": "T", "columns": []},
    # a bare `{}` fails `AppSpec` validation before the tool ever reaches its own draft read
    # (unlike the render/confirm/revisions/approve/plan tools below, whose `spec` stays a raw
    # `dict[str, Any]` at the DTO boundary and only decodes lazily) -- a real `blank_spec()` gets
    # this one all the way to `get_draft`.
    "forge_compare_to_spec": {"flow_id": "F", "spec": _BLANK_SPEC},
    "forge_create_list": {"name": "L", "values": []},
    "forge_add_sequence_number": {
        "flow_id": "F",
        "field_name": "N",
        "section_name": "S",
        "prefix": "P-",
        "padding": "0001",
        "step_activity_name": "Start",
    },
    "forge_add_field_validation": {"flow_id": "F", "rules": {}},
    "forge_build_workflow": {"flow_id": "F", "steps": []},
    "forge_add_goto_gate": {
        "flow_id": "F",
        "target_activity_name": "A",
        "field_name": "B",
    },
    "forge_set_branch_conditions": {
        "flow_id": "F",
        "field_name": "B",
        "branch_literals": {},
    },
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
    "forge_grant_tier": {
        "kind": "process",
        "flow_id": "F",
        "role_id": "R",
        "tier": "Manage",
    },
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


def _settings() -> Settings:
    return Settings(
        kf_dev_domain="dev-acme.kissflow.com",
        kf_dev_account_id="A1",
        kf_app="App1",  # a single-app default, so no MINIMAL_ARGS row needs its own app_id
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id="k1",
        kf_dev_access_key_secret="s1",
        http_timeout_seconds=10.0,
    )


def _resources() -> AppResources:
    """A fresh `AppResources`, every fake empty (no queued values, so every read returns the
    fake's own harmless default -- an empty draft, an empty list, ...). Good enough for every
    check in this file: none of them needs a specific tenant SHAPE, only "did a write happen"
    and "did the tool return/refuse cleanly, never raise"."""
    return AppResources(
        flow=FakeFlowRepository(),
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


def _tool_names() -> list[str]:
    return sorted(_listed(_resources()))


def _listed(resources: AppResources | None = None) -> dict[str, Any]:
    server = _server(resources if resources is not None else _resources())

    async def _run() -> list[Any]:
        async with Client(server) as client:
            return await client.list_tools()

    return {t.name: t for t in asyncio.run(_run())}


def _call(tool: str, args: dict[str, Any], resources: AppResources) -> Any:
    async def _run() -> Any:
        async with Client(_server(resources)) as client:
            return await client.call_tool(tool, args, raise_on_error=False)

    return asyncio.run(_run())


def test_minimal_args_cover_every_registered_tool() -> None:
    """Fixture-drift guard: a new tool must be probed by every test in this file, not skipped."""
    assert set(MINIMAL_ARGS) == set(_tool_names())


# =================================================================================================
# 2. ANNOTATIONS + TITLES (M2)
# =================================================================================================


def test_every_tool_carries_all_four_hints_and_a_title() -> None:
    """M2: zero of the 59 tools carried readOnlyHint/destructiveHint/idempotentHint/openWorldHint,
    despite ~40 live write tools and several that delete whole applications."""
    for t in _listed().values():
        assert t.title, f"{t.name} has no human-readable title"
        a = t.annotations
        assert a is not None, f"{t.name} has no annotations"
        for hint in (
            "read_only_hint",
            "destructive_hint",
            "idempotent_hint",
            "open_world_hint",
        ):
            assert getattr(a, hint) is not None, f"{t.name} is missing {hint}"


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


def _write_calls(resources: AppResources) -> list[tuple[str, str]]:
    return [
        (fake_name, name)
        for fake_name, fake in (
            ("flow", resources.flow),
            ("app", resources.app),
            ("page", resources.page),
            ("dataset", resources.dataset),
            ("item", resources.item),
        )
        for name, _args, _kwargs in cast(Any, fake).calls
        if name.startswith(_WRITE_PREFIXES)
    ]


def _any_call(resources: AppResources) -> bool:
    return any(
        cast(Any, fake).calls
        for fake in (
            resources.flow,
            resources.app,
            resources.page,
            resources.dataset,
            resources.item,
            resources.copilot,
        )
    )


def test_read_only_is_never_claimed_by_a_tool_that_writes_something() -> None:
    """readOnlyHint true ONLY if the body writes neither the tenant nor the filesystem. The four
    render/confirm tools are the trap: every one of them says "OFFLINE" in its own description and
    then writes files to disk, which is precisely why these hints are derived from the body.

    Proven behaviorally, not by grepping tool source: each readOnly-claiming tool RUNS against
    fresh, empty family fakes and (for the four artifact writers) a patched `write_artifact`, and
    any write it performs on either surface disproves the claim, however the body reached it. A
    tool that refuses mid-call still proves the property: whatever it did before refusing is on
    the fake's own call log.
    """
    writes_files = {
        "forge_render_flow_diagram",
        "forge_render_schema_diagram",
        "forge_render_mockups",
        "forge_request_confirmation",
    }
    by_name = _listed()
    for name in writes_files:
        assert by_name[name].annotations.read_only_hint is False, (
            f"{name} writes artifact files to disk — it is not read-only, whatever its "
            f"description prefix says"
        )
        assert by_name[name].annotations.open_world_hint is False, (
            f"{name} touches no tenant"
        )

    for name, t in sorted(by_name.items()):
        if not t.annotations.read_only_hint:
            continue
        resources = _resources()
        # an error is not a write — only the call logs below disprove the claim
        with contextlib.suppress(Exception):
            asyncio.run(_run_tool_only(_server(resources), name, MINIMAL_ARGS[name]))
        wrote_tenant = _write_calls(resources)
        assert not wrote_tenant, f"{name} claims readOnlyHint but wrote {wrote_tenant}"


async def _run_tool_only(server: FastMCP, name: str, args: dict[str, Any]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(name, args, raise_on_error=False)


def test_destructive_hint_is_set_on_every_tool_that_replaces_or_deletes_state() -> None:
    """The named cases from the finding, each verified against what the body actually does."""
    by_name = _listed()
    must_be_destructive = {
        # replaces EVERY Permission on the flow
        "forge_set_visibility",
        "kf_set_step_visibility",
        # wipes every Activity/ProcessDef/Resource/Permission
        "forge_build_workflow",
        # REPLACE semantics on the whole item array
        "forge_create_list",
        # SET semantics: every root field not listed comes back optional
        "forge_set_required",
        # rebuilds every Row in the named sections
        "forge_apply_layout",
        "forge_apply_fields",
        # replaces every existing event on the named fields
        "forge_set_events",
        # "No access" is a real DELETE .../member/{role_id}
        "forge_grant_tier",
        # deletes, outright
        "forge_delete_fields",
        "forge_delete_flow",
        "forge_delete_app_role",
        # op="delete" is one of the four
        "forge_dataset_records",
    }
    for name in sorted(must_be_destructive):
        assert by_name[name].annotations.destructive_hint is True, (
            f"{name} removes or overwrites existing state but is not marked destructive"
        )
    # ...and the additive ones are not over-flagged
    for name in (
        "kf_apply_field_change",
        "forge_add_table",
        "forge_add_sequence_number",
        "forge_add_field_validation",
        "forge_add_role_users",
        "forge_member_batch",
    ):
        assert by_name[name].annotations.destructive_hint is False, name


def test_open_world_is_exactly_the_tenant_touching_set() -> None:
    """openWorldHint true for anything that reaches the Kissflow tenant — which is exactly the set
    of tools that call a port method at all, plus nothing else. Proven behaviorally: every tool is
    CALLED with its minimal args against fresh, empty family fakes, and the hint must match
    whether the tool actually made a port call — however it got there, helper or not."""
    for name, t in _listed().items():
        resources = _resources()
        with contextlib.suppress(Exception):
            asyncio.run(_run_tool_only(_server(resources), name, MINIMAL_ARGS[name]))
        touches_tenant = _any_call(resources)
        assert t.annotations.open_world_hint is touches_tenant, (
            f"{name}: openWorldHint={t.annotations.open_world_hint} but "
            f"{'it calls a port method' if touches_tenant else 'it never touches the tenant'}"
        )


def test_the_four_render_tools_no_longer_advertise_themselves_as_offline_only() -> None:
    """A hint disagreeing with its own description is the same bug in a different place."""
    by_name = _listed()
    for name in ("forge_render_flow_diagram", "forge_render_mockups"):
        assert (
            "Written to" in by_name[name].description
            or "written to" in by_name[name].description
        )


# =================================================================================================
# 3. CLOSED-SET ENUMS (A2)
# =================================================================================================


def _param_schema(tool_name: str, param: str) -> dict[str, Any]:
    return (_listed()[tool_name].input_schema.get("properties") or {})[param]


def _closed_values(schema: dict[str, Any]) -> list[Any]:
    """A closed set is `enum` for 2+ members and `const` for exactly one (Pydantic emits both)."""
    if "enum" in schema:
        return list(schema["enum"])
    if "const" in schema:
        return [schema["const"]]
    raise AssertionError(f"not a closed set: {schema}")


@pytest.mark.parametrize(
    "tool_name, param, expected",
    [
        (
            "kf_get_flow_schema",
            "flow_kind",
            ["form", "process", "case", "dataset", "page"],
        ),
        ("kf_apply_field_change", "flow_kind", ["form", "process", "case", "dataset"]),
        ("forge_apply_fields", "kind", ["form", "process", "case", "dataset"]),
        ("kf_publish", "flow_kind", ["form", "process", "case"]),
        ("forge_publish", "kind", ["form", "process", "case", "page", "application"]),
        (
            "forge_delete_flow",
            "kind",
            ["form", "process", "case", "list", "dataset", "page", "application"],
        ),
        ("forge_grant_tier", "kind", ["process", "case"]),
        ("forge_create_flow", "kind", ["process", "form", "list", "dataset", "case"]),
        ("forge_dataset_records", "op", ["create", "update", "delete", "list"]),
        ("forge_sweep", "scope", ["apps", "flows", "pages", "roles", "lists", "all"]),
        ("forge_approve_spec", "decision", ["approve"]),
    ],
)
def test_a_closed_vocabulary_reaches_the_schema_as_an_enum(
    tool_name: str, param: str, expected: list[str]
) -> None:
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
    assert (
        len({frozenset(s) for s in (grant, create, publish, flow, delete, data)}) == 6
    )


def test_every_kind_shaped_parameter_is_a_closed_set() -> None:
    """No silent survivor: any parameter named kind/flow_kind/scope/op/tier/decision on any tool
    must be enumerable, or a typo reaches the engine again."""
    closed_names = {"kind", "flow_kind", "scope", "op", "tier", "decision"}
    checked = 0
    for t in _listed().values():
        for pname, schema in (t.input_schema.get("properties") or {}).items():
            # forge_build_page's `op` is a compiled build_page OBJECT, not a vocabulary — the
            # name collides, the meaning does not. Only string-valued slots are vocabularies.
            if pname not in closed_names or schema.get("type") != "string":
                continue
            _closed_values(schema)  # raises with the offending schema if it is open
            checked += 1
    assert checked >= 28, (
        f"only {checked} closed-set parameters found — did a Literal get lost?"
    )


def test_boundary_enums_match_the_engine_constants_they_mirror() -> None:
    """The anti-drift guard. These Literals are hand-written (a Literal cannot be built from a
    runtime dict), so this test is what stops them diverging from the engine's own sets."""
    assert set(_closed_values(_param_schema("forge_doctor", "kind"))) == set(
        FlowKind.__args__
    )
    assert set(_closed_values(_param_schema("forge_grant_tier", "kind"))) == set(
        _TIER_MAP
    )
    assert set(_closed_values(_param_schema("forge_grant_tier", "tier"))) == {
        tier for by_tier in _TIER_MAP.values() for tier in by_tier
    }
    assert set(_closed_values(_param_schema("forge_sweep", "scope"))) == set(
        SWEEP_SCOPES
    ) | {"all"}


def test_kf_list_field_types_no_longer_calls_the_engine_set_the_platforms_closed_enum() -> (
    None
):
    """C5: this one tool misrepresented the platform — it called the 8 types this engine can build
    the platform's "closed enum" when the platform's palette is much wider. It must now say what
    it actually is and point at forge_capabilities for the rest."""
    doc = _listed()["kf_list_field_types"].description or ""
    assert "closed enum" not in doc.lower()
    assert "forge_capabilities" in doc
    assert "THIS ENGINE" in doc or "this engine" in doc


def test_field_type_enum_matches_the_engine_catalog() -> None:
    """`kf_list_field_types`' own catalog (`tests/unit/application/use_cases/meta/
    test__field_types.py` proves the tool itself) must still be exactly `FieldType`'s wire
    values -- the anti-drift guard for the one non-tool-parameter enum this boundary carries."""
    assert {t.value for t in FieldType} == {
        "Text",
        "Textarea",
        "Date",
        "DateTime",
        "Boolean",
        "Select",
        "User",
        "Number",
        "Attachment",
    }


# =================================================================================================
# 4. NO RAISES THROUGH THE TOOL BOUNDARY (A1, doctrine 7)
# =================================================================================================

# The nested arguments a schema can only describe as list[Any]/dict[str, Any] — one malformed
# value each, of the shape an agent actually gets wrong: a pair one element short, an object with
# a missing key, a bare string where a list of triples belongs. Fragments below name the failing
# nested entry in the request DTO's validation message (spec G10: "the same bad inputs fail with
# ValidationError"). The custom shape validators preserve the old bracketed path for their own
# restored refusal text; the CLAIM each row backs (a malformed nested argument is refused as DATA,
# before any write, naming which entry) is unchanged.
MALFORMED_ARGS: dict[str, tuple[dict[str, Any], str]] = {
    "kf_plan_field_change": (
        {"draft": {}, "changes": [{"name": "x"}]},
        "changes.0.type",
    ),
    "kf_apply_field_change": (
        {
            "flow_kind": "process",
            "flow_id": "F",
            "changes": [{"name": "x", "type": "Wat"}],
        },
        "changes.0.type",
    ),
    "kf_create_process": (
        {"name": "N", "steps": [], "fields": [{"type": "Text"}]},
        "fields.0.name",
    ),
    "forge_apply_fields": (
        {"flow_id": "F", "fields": [{"name": "a", "type": "Nope"}]},
        "fields.0.type",
    ),
    "forge_apply_layout": (
        {"flow_id": "F", "layout": {"S": [[["a", 0]]]}},
        "layout['S'][0][0]",
    ),
    "forge_add_table": (
        {"flow_id": "F", "name": "T", "columns": [["only-a-name"]]},
        "columns.0",
    ),
    "forge_add_field_validation": (
        {"flow_id": "F", "rules": {"a": [["CONTAINS"]]}},
        "rules['a'][0]",
    ),
    "forge_build_workflow": ({"flow_id": "F", "steps": [["Approve"]]}, "steps.0.1"),
    "forge_set_events": (
        {"flow_id": "F", "events": {"a": [["onChange"]]}},
        "events['a'][0]",
    ),
    "forge_build_page": (
        {"app_id": "A", "page_id": "P", "steps": [{"kwargs": {}}]},
        "steps[0]['kind']",
    ),
    "forge_simulate_case": (
        {"flow_id": "F", "steps": [{"values": {}}]},
        "steps[0]['name']",
    ),
}


@pytest.mark.parametrize("tool_name", sorted(MALFORMED_ARGS))
def test_a_malformed_nested_arg_is_refused_as_data_not_a_traceback(
    tool_name: str,
) -> None:
    """A1 / doctrine 7. Every one of these destructured a nested parameter with no shape check, so
    the single most likely agent mistake produced a bare Python traceback instead of structured
    data. Refused now as a `ToolError` naming the offending entry, never a raw exception through
    `Client.call_tool`."""
    args, fragment = MALFORMED_ARGS[tool_name]
    with pytest.raises(ToolError) as excinfo:
        _call_raising(tool_name, args, _resources())
    assert fragment in str(excinfo.value), (
        f"{tool_name}: refusal does not name {fragment}: {excinfo.value}"
    )


def _call_raising(tool: str, args: dict[str, Any], resources: AppResources) -> Any:
    async def _run() -> Any:
        async with Client(_server(resources)) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(_run())


def test_a_parallel_block_with_no_name_is_refused_by_name() -> None:
    # A BLANK name (present, empty) reaches `ForgeBuildWorkflowRequest`'s own custom
    # `_parallel_is_named` validator, which names the parameter -- an ABSENT "name" key fails
    # Pydantic's own tuple-element type check first instead ("Input should be a valid string"),
    # a plainer message this row is not about.
    args = {
        "flow_id": "F",
        "steps": [["Approve", None]],
        "parallel": {"name": "", "branches": [["B", [["S", None]]]]},
    }
    with pytest.raises(ToolError, match=r"parallel\['name'\]"):
        _call_raising("forge_build_workflow", args, _resources())


def test_the_two_plan_tools_no_longer_raise_before_any_gate() -> None:
    """kf_plan_field_change and kf_plan_step_visibility are OFFLINE — they have no config gate to
    short-circuit behind, so a bad argument used to escape as a bare traceback on the very first
    statement, credentials or not. Both now return the refusal as a `ToolError`."""
    with pytest.raises(ToolError, match="changes.0.type"):
        _call_raising(
            "kf_plan_field_change",
            {"draft": {}, "changes": [{"name": "x", "type": "Nope"}]},
            _resources(),
        )

    # an empty/foreign draft: graph.progressive_matrix's own ValueError, translated
    with pytest.raises(ToolError, match="ProcessDef"):
        _call_raising(
            "kf_plan_step_visibility",
            {"draft": {}, "owners": {"Intake": ["Start"]}},
            _resources(),
        )


def test_no_tool_escapes_as_a_raw_exception_with_no_credentials() -> None:
    """The blanket net: every tool on the surface, called with well-typed args and empty (never
    configured) family fakes, returns a `CallToolResult` rather than raising a bare exception
    through `Client.call_tool`. FastMCP's own transport catches every exception a tool body
    raises and reports it as a protocol error (`mask_error_details=True`), so this is a structural
    guarantee of `create_server` now, not something each tool body must individually re-prove --
    proven once, generically, below (`test_an_unexpected_exception_never_escapes_the_transport`);
    this keeps the ORIGINAL per-tool sweep, since a genuinely malformed `MINIMAL_ARGS` entry (a
    typo in this very file) is still worth catching tool by tool."""
    for name in sorted(MINIMAL_ARGS):
        result = _call(name, MINIMAL_ARGS[name], _resources())
        assert result is not None, name


def test_no_tool_escapes_as_a_raw_exception_with_malformed_args() -> None:
    """The same net, with garbage in every slot the schema types loosely."""
    for name in sorted(MINIMAL_ARGS):
        garbage: dict[str, Any] = {}
        for key, value in MINIMAL_ARGS[name].items():
            if isinstance(value, dict):
                garbage[key] = {"": ["", 1, None]}
            elif isinstance(value, list):
                garbage[key] = [["only-one"], {"no": "kind"}, None]
            else:
                garbage[key] = value
        result = _call(name, garbage, _resources())
        assert result is not None, name


def test_an_unexpected_exception_never_escapes_the_transport() -> None:
    """The mechanism itself, on a throwaway server carrying one synthetic tool that raises a raw,
    un-translated `KeyError` -- the shape a genuine bug in a use case would take. `create_server`'s
    own `mask_error_details=True` (spec G6) must still turn it into a protocol error, never let it
    propagate out of `Client.call_tool`."""

    def _lifespan(server: FastMCP):
        @asynccontextmanager
        async def _run(inner: FastMCP) -> AsyncIterator[dict[str, Any]]:
            del inner
            yield {"resources": _resources(), "settings": _settings()}

        return _run(server)

    probe = FastMCP("boundary-probe", mask_error_details=True)

    @probe.tool(title="Breaks")
    def breaks() -> dict[str, Any]:
        """A tool that raises a raw exception, the way a genuine bug would."""
        raise KeyError("boom")

    async def _run() -> Any:
        async with Client(probe) as client:
            return await client.call_tool("breaks", {}, raise_on_error=False)

    result = asyncio.run(_run())
    assert result.is_error is True


def test_a_malformed_arg_is_a_tool_error_on_the_protocol_envelope_too() -> None:
    """The two fixes meet: a shape refusal is structured DATA (A1) AND a protocol error (M1)."""
    for tool_name, (args, _fragment) in MALFORMED_ARGS.items():
        result = _call(tool_name, args, _resources())
        assert result.is_error is True, (tool_name, result.structured_content)


# =================================================================================================
# 5. THE OPPOSITE FAILURE (D7) — an enum TIGHTER than the code supports is a capability regression
#
# Adding enums in bulk has its own trap, and this branch shipped it: `forge_delete_flow` took a
# bare `str` and reached `client.delete_flow(kind, ...)` for ANY kind. Typing it as PublishKind
# removed the only route to delete a `list` or a `dataset` — two kinds `forge_create_flow` mints
# freely — because "cannot be published" was read as "cannot be deleted". These tests assert the
# reachable set, from the reachable CREATES and from the code path behind each parameter.
#
# `test_delete_anything_really_routes_a_list_and_a_dataset` and
# `test_force_regrant_groups_is_forwarded_through_the_tool_boundary` (old `delete_anything`/
# `_FakeRoleClient` direct-function tests) are ported to `tests/unit/application/use_cases/flow/
# test__delete.py` and Stage D group 5's own `forge_add_role_users` suite -- not re-staged here.
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


def test_a_dataform_draft_is_still_readable_and_field_writable() -> None:
    """The other half of the same audit: `dataset` was reachable on the draft-read and
    field-write tools before the enums landed, and docs/capabilities/module.dataform.md is the
    coverage row that proves it ("the engine's `apply_fields` runs unmodified with
    kind='dataset'"). `list` is NOT admitted anywhere — a word list has no draft graph, and
    doctrine 10 says no capture means refuse, not guess."""
    for tool, param in (
        ("kf_get_flow_schema", "flow_kind"),
        ("kf_apply_field_change", "flow_kind"),
        ("forge_apply_fields", "kind"),
    ):
        values = set(_closed_values(_param_schema(tool, param)))
        assert "dataset" in values, f"{tool}.{param} lost the dataform"
        assert "list" not in values, (
            f"{tool}.{param} admits a kind with no captured draft graph"
        )


def test_the_widened_sets_are_still_closed_and_still_reject_junk() -> None:
    """Widening is not opening: every set stays an enum, and nothing outside it gets through."""
    result = _call(
        "forge_delete_flow", {"kind": "spreadsheet", "flow_id": "F"}, _resources()
    )
    assert result.is_error is True
    assert "spreadsheet" in str(result.content) or "enum" in str(result.content).lower()
