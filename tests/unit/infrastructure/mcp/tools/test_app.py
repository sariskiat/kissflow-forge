"""The app-family tool module: `register` calls both work groups.

`_register_roles` (the app-roles group, Stage D group 5) and `_register_apps`
(the applications group, Stage D group 6) are both filled below, each driven
through a real in-process MCP client -- proving argument mapping,
`ApplicationError` -> `ToolError`, and the missing-key-pair guard all the way
through each thin tool, not just through `_shared.run_use_case` in isolation
(already covered by `tests/unit/infrastructure/mcp/tools/test__shared.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

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

from app.application.exceptions import RepositoryError
from app.domain.entities.flow_draft import FlowDraft
from app.domain.entities.navigation import Navigation
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server
from app.infrastructure.mcp.tools import app as app_tools

_ROLE_TOOL_NAMES = {
    "forge_member_batch",
    "forge_add_member_roles",
    "forge_create_app_role",
    "forge_delete_app_role",
    "forge_list_app_roles",
    "forge_add_role_users",
    "forge_grant_tier",
    "forge_set_role_preference",
}

_APP_TOOL_NAMES = {
    "forge_create_app",
    "forge_list_apps",
    "forge_publish_app",
    "forge_create_template_app",
    "forge_share_report",
    "forge_sweep",
}


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_every_work_group_without_error() -> None:
    """Today's state, pinned: both work groups (group 5, app roles; group 6,
    app family apps) have landed here -- the exact set of the 14 tools."""
    mcp = FastMCP("test")
    app_tools.register(mcp)
    assert set(await _tool_names(mcp)) == _ROLE_TOOL_NAMES | _APP_TOOL_NAMES


def test_every_work_group_is_independently_callable() -> None:
    """Each group takes the server alone, so two writers filling different groups in
    Stage D can each test their own function in isolation."""
    mcp = FastMCP("test")
    app_tools._register_roles(mcp)
    app_tools._register_apps(mcp)


# =====================================================================================
# _register_roles (Stage D group 5): argument mapping, ApplicationError ->
# ToolError, and the missing-key-pair path, through the real MCP call_tool
# path: `fastmcp.Client(create_server(fake_lifespan))`.
# =====================================================================================


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "Acc1",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": "key-1",
        "kf_dev_access_key_secret": "secret-1",  # gitleaks:allow
        "http_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return Settings(**values)


def _resources(
    *, flow: FakeFlowRepository | None = None, app: FakeAppRepository | None = None
) -> AppResources:
    return AppResources(
        flow=flow if flow is not None else FakeFlowRepository(),
        app=app if app is not None else FakeAppRepository(),
        page=FakePageRepository(),
        dataset=FakeDatasetRepository(),
        item=FakeItemService(),
        copilot=FakeCopilotService(),
        docs=FakeDocsReader(),
        artifacts=FakeArtifactWriter(),
    )


def _lifespan(settings: Settings, resources: AppResources) -> Any:
    @asynccontextmanager
    async def _run(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": resources, "settings": settings}

    return _run


def _server(settings: Settings, resources: AppResources) -> FastMCP:
    return create_server(_lifespan(settings, resources))


# ---- forge_member_batch ----


@pytest.mark.asyncio
async def test_forge_member_batch_maps_arguments_and_grants_from_the_account() -> None:
    flow = FakeFlowRepository()
    flow.results["list_flows"] = [[]]
    app = FakeAppRepository()
    app.results["list_app_roles"] = [
        [{"_id": "RoA", "Name": "Admin", "Applications": [{"_id": "App1"}]}]
    ]
    flow.results["get_members"] = [[{"_id": "RoA", "Name": "Admin", "Kind": "AppRole"}]]
    server = _server(_settings(), _resources(flow=flow, app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_member_batch", {"target_flow_id": "F1", "app_id": "App1"}
        )

    assert result.structured_content["target_flow_id"] == "F1"
    assert result.structured_content["role_ids"] == ["RoA"]
    assert result.structured_content["snapshot_version"] is None
    # `ForgeMemberBatchResponse`'s own key set (old
    # `client.MemberReport.as_tool_result()`, minus `isError`, plus
    # `snapshot_version`).
    assert set(result.structured_content) == {
        "target_flow_id",
        "source_flow_id",
        "harvested",
        "applied",
        "verified",
        "missing",
        "note",
        "role_ids",
        "resolved",
        "roles_seen",
        "roles_granted",
        "roles_unusable",
        "snapshot_version",
    }
    assert flow.calls[0][0] == "list_flows"
    assert app.calls[0][0] == "list_app_roles"


# Every tool of this group, with the smallest valid arguments short of an app id.
_MINIMAL_ARGS: dict[str, dict[str, Any]] = {
    "forge_member_batch": {"target_flow_id": "F1"},
    "forge_add_member_roles": {"target_flow_id": "F1", "roles": {"RoX": "Requester"}},
    "forge_create_app_role": {"name": "Reviewer"},
    "forge_delete_app_role": {"role_id": "Ro1"},
    "forge_list_app_roles": {},
    "forge_add_role_users": {"role_id": "R1", "user_query": "ann"},
    "forge_grant_tier": {
        "kind": "process",
        "flow_id": "F1",
        "role_id": "R1",
        "tier": "Manage",
    },
    "forge_set_role_preference": {"role_id": "R1", "default_page": "Default"},
}

_NO_APP_MESSAGE = (
    "no app selected — pass app_id (see forge_list_apps for valid ids), or set "
    "the KF_APP env var as a single-app default"
)


def test_the_minimal_arguments_cover_every_tool_of_the_group() -> None:
    assert set(_MINIMAL_ARGS) == _ROLE_TOOL_NAMES


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(_ROLE_TOOL_NAMES))
async def test_no_key_pair_fails_before_the_use_case_runs(tool_name: str) -> None:
    flow = FakeFlowRepository()
    app = FakeAppRepository()
    server = _server(
        _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None),
        _resources(flow=flow, app=app),
    )

    async with Client(server) as client:
        result = await client.call_tool(
            tool_name,
            {**_MINIMAL_ARGS[tool_name], "app_id": "App1"},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert "no Kissflow key pair on this call" in str(result.content)
    assert flow.calls == [] and app.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(_ROLE_TOOL_NAMES))
async def test_an_application_error_is_a_tool_error_with_the_same_message(
    tool_name: str,
) -> None:
    """No `app_id` argument and no `KF_APP` default: the use case raises
    `ApplicationError(code=REFUSED)`, and the client reads the same message."""
    flow = FakeFlowRepository()
    app = FakeAppRepository()
    server = _server(_settings(kf_app=None), _resources(flow=flow, app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            tool_name, _MINIMAL_ARGS[tool_name], raise_on_error=False
        )

    assert result.is_error is True
    assert result.content[0].text == _NO_APP_MESSAGE
    assert flow.calls == [] and app.calls == []


@pytest.mark.asyncio
async def test_the_kf_app_default_resolves_when_no_app_id_is_passed() -> None:
    app = FakeAppRepository()
    server = _server(_settings(kf_app="App_default"), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool("forge_list_app_roles", {})

    assert result.structured_content["app_id"] == "App_default"
    assert app.calls == [("list_app_roles", (), {"app_id": "App_default"})]


# ---- forge_add_member_roles ----


@pytest.mark.asyncio
async def test_forge_add_member_roles_maps_arguments_and_creates_a_role() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [[], [{"_id": "RoNew1", "Name": "Requester"}]]
    app.results["create_app_role"] = ["RoNew1"]
    flow = FakeFlowRepository()
    server = _server(_settings(), _resources(flow=flow, app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_member_roles",
            {
                "target_flow_id": "F1",
                "roles": {"RoX": "Requester"},
                "app_id": "App1",
            },
        )

    assert result.structured_content["resolved"] == {"Requester": "RoNew1"}
    assert app.calls[0][0] == "list_app_roles"
    # `ForgeAddMemberRolesResponse`'s own key set.
    assert set(result.structured_content) == {
        "target_flow_id",
        "source_flow_id",
        "harvested",
        "applied",
        "verified",
        "missing",
        "note",
        "role_ids",
        "resolved",
        "roles_seen",
        "roles_granted",
        "roles_unusable",
        "snapshot_version",
    }


# ---- forge_create_app_role ----


@pytest.mark.asyncio
async def test_forge_create_app_role_maps_arguments() -> None:
    app = FakeAppRepository()
    app.results["create_app_role"] = ["RoNew1"]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_create_app_role", {"name": "Reviewer", "app_id": "App1"}
        )

    assert result.structured_content == {
        "role_id": "RoNew1",
        "name": "Reviewer",
        "app_id": "App1",
        "snapshot_version": None,
    }
    assert app.calls[0][0] == "list_app_roles"
    assert app.calls[1] == ("create_app_role", ("Reviewer",), {"app_id": "App1"})


# ---- forge_delete_app_role ----


@pytest.mark.asyncio
async def test_forge_delete_app_role_maps_arguments() -> None:
    app = FakeAppRepository()
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_delete_app_role", {"role_id": "Ro1", "app_id": "App1"}
        )

    assert result.structured_content == {
        "role_id": "Ro1",
        "deleted": True,
        "snapshot_version": None,
    }
    assert app.calls[0][0] == "get_app_role"
    assert app.calls[1][0] == "delete_app_role"


# ---- forge_list_app_roles ----


@pytest.mark.asyncio
async def test_forge_list_app_roles_maps_arguments() -> None:
    app = FakeAppRepository()
    app.results["list_app_roles"] = [[{"_id": "Ro1", "Name": "Reviewer"}]]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool("forge_list_app_roles", {"app_id": "App1"})

    assert result.structured_content == {
        "roles": [{"_id": "Ro1", "Name": "Reviewer"}],
        "count": 1,
        "app_id": "App1",
    }
    assert "snapshot_version" not in result.structured_content


# ---- forge_add_role_users ----


@pytest.mark.asyncio
async def test_forge_add_role_users_maps_arguments_and_grants_by_query() -> None:
    app = FakeAppRepository()
    app.results["get_app_role"] = [
        {"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0},
        {
            "_id": "R1",
            "Name": "Reviewer",
            "Members": [{"_id": "U1", "Kind": "User", "Name": "Ann"}],
            "UserCount": 1,
        },
    ]
    app.results["get_assignee"] = [
        [{"_id": "U1", "Kind": "User", "Email": "ann@x.com", "Name": "Ann"}]
    ]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_role_users",
            {"role_id": "R1", "user_query": "ann", "app_id": "App1"},
        )

    assert result.structured_content["added"] == ["U1"]
    assert app.calls[0][0] == "get_app_role"
    # `ForgeAddRoleUsersResponse`'s own key set, `groups_note` DROPPED here --
    # no group was granted this call, so the old
    # `RoleUsersReport.as_tool_result()`'s own conditional `if
    # self.groups_note: out["groups_note"] = ...` never added it (lesson 15).
    assert set(result.structured_content) == {
        "role_id",
        "added",
        "already_present",
        "not_found",
        "user_count",
        "groups_added",
        "groups_already_present",
        "groups_unverified",
        "groups_refused",
        "group_count",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_add_role_users_groups_note_present_when_a_group_lands() -> None:
    """The other of fix 10's "both cases of `groups_note`": a group grant that
    verifies by `GroupCount` movement (no group LIST on this tenant) carries
    a non-empty `groups_note`, so the key IS present this time."""
    app = FakeAppRepository()
    app.results["get_app_role"] = [
        {"_id": "R1", "Name": "Reviewer", "Members": [], "GroupCount": 0},
        {"_id": "R1", "Name": "Reviewer", "Members": [], "GroupCount": 1},
    ]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_role_users",
            {
                "role_id": "R1",
                "groups": [{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
                "confirm_group_notification": True,
                "app_id": "App1",
            },
        )

    assert result.structured_content["groups_added"] == ["everyone"]
    assert "groups_note" in result.structured_content
    assert "GroupCount 0 -> 1" in result.structured_content["groups_note"]
    assert set(result.structured_content) == {
        "role_id",
        "added",
        "already_present",
        "not_found",
        "user_count",
        "groups_added",
        "groups_already_present",
        "groups_unverified",
        "groups_refused",
        "group_count",
        "groups_note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_add_role_users_group_without_confirmation_is_refused() -> None:
    app = FakeAppRepository()
    app.results["get_app_role"] = [{"_id": "R1", "Name": "Reviewer"}]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_role_users",
            {
                "role_id": "R1",
                "groups": [{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
                "app_id": "App1",
            },
            raise_on_error=False,
        )

    assert result.is_error is True
    assert "confirm_group_notification=True" in str(result.content)
    # Refused before any write -- the app port never even got the role detail.
    assert app.calls == []


@pytest.mark.asyncio
async def test_forge_add_role_users_unresolved_query_is_verify_failed() -> None:
    """Review rule 7: a `not_found` user is a write that did not fully land, so it
    raises `ApplicationError(code=VERIFY_FAILED)` rather than returning a response
    with `not_found` populated."""
    app = FakeAppRepository()
    app.results["get_app_role"] = [
        {"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}
    ]
    app.results["get_assignee"] = [[]]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_add_role_users",
            {"role_id": "R1", "user_query": "nobody", "app_id": "App1"},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert "not_found: nobody" in str(result.content)


# ---- forge_grant_tier ----


@pytest.mark.asyncio
async def test_forge_grant_tier_maps_arguments_and_grants_manage() -> None:
    flow = FakeFlowRepository()
    app = FakeAppRepository()
    app.results["get_app_role"] = [{"_id": "R1", "Name": "Reviewer"}]
    flow.results["get_members"] = [
        [],
        [
            {
                "_id": "R1",
                "Name": "Reviewer",
                "Role": "DataAdmin",
                "Permission": ["InitiateItems"],
            }
        ],
    ]
    server = _server(_settings(), _resources(flow=flow, app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_grant_tier",
            {
                "kind": "process",
                "flow_id": "F1",
                "role_id": "R1",
                "tier": "Manage",
                "app_id": "App1",
            },
        )

    assert result.structured_content == {
        "flow_id": "F1",
        "kind": "process",
        "role_id": "R1",
        "tier": "Manage",
        "verified": True,
        "snapshot_version": None,
    }
    assert flow.calls[0][0] == "get_members"


@pytest.mark.asyncio
async def test_forge_grant_tier_bad_kind_is_a_validation_tool_error() -> None:
    server = _server(_settings(), _resources())

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_grant_tier",
            {
                "kind": "form",
                "flow_id": "F1",
                "role_id": "R1",
                "tier": "Manage",
                "app_id": "App1",
            },
            raise_on_error=False,
        )

    assert result.is_error is True


# ---- forge_set_role_preference ----


@pytest.mark.asyncio
async def test_forge_set_role_preference_maps_arguments() -> None:
    app = FakeAppRepository()
    app.results["get_app_role"] = [
        {"_id": "R1", "Name": "Reviewer", "Members": []},
        {
            "_id": "R1",
            "Name": "Reviewer",
            "Members": [],
            "Preference": {"DefaultPage": "Page_1"},
        },
    ]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_role_preference",
            {"role_id": "R1", "default_page": "Page_1", "app_id": "App1"},
        )

    assert result.structured_content == {
        "role_id": "R1",
        "default_page": "Page_1",
        "default_navigation": None,
        "verified": True,
        "snapshot_version": None,
    }


@pytest.mark.asyncio
async def test_forge_set_role_preference_neither_key_given_is_a_tool_error() -> None:
    app = FakeAppRepository()
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_role_preference",
            {"role_id": "R1", "app_id": "App1"},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert "give default_page or default_navigation" in str(result.content)
    assert app.calls == []


@pytest.mark.asyncio
async def test_forge_set_role_preference_unverified_write_is_verify_failed() -> None:
    app = FakeAppRepository()
    app.results["get_app_role"] = [
        {"_id": "R1", "Name": "Reviewer", "Members": []},
        {"_id": "R1", "Name": "Reviewer", "Members": [], "Preference": {}},
    ]
    server = _server(_settings(), _resources(app=app))

    async with Client(server) as client:
        result = await client.call_tool(
            "forge_set_role_preference",
            {"role_id": "R1", "default_page": "Page_1", "app_id": "App1"},
            raise_on_error=False,
        )

    assert result.is_error is True
    assert "did not verify on read-back" in str(result.content)


# ---- the group rule at the tool edge ----
# Ports tests/test_mcp_surface.py's handshake and tool-description checks and
# tests/test_tool_claims.py's forge_add_role_users / forge_grant_tier rows onto the
# new server.


@pytest.mark.asyncio
async def test_every_client_is_told_the_group_rule_in_the_handshake() -> None:
    async with Client(_server(_settings(), _resources())) as client:
        instructions = client.instructions or ""

    assert "NEVER GRANT A GROUP" in instructions
    assert "CANNOT BE UNDONE" in instructions
    assert "user_query" in instructions
    assert "confirm_group_notification" in instructions


@pytest.mark.asyncio
async def test_the_group_rule_also_rides_the_tool_that_enforces_it() -> None:
    async with Client(_server(_settings(), _resources())) as client:
        tools = {t.name: t for t in await client.list_tools()}
    tool = tools["forge_add_role_users"]

    assert "confirm_group_notification" in (tool.description or "")
    props = (tool.input_schema or {}).get("properties") or {}
    assert "EMAILS every member" in (props["groups"].get("description") or "")
    assert "email every member" in (
        props["confirm_group_notification"].get("description") or ""
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "phrase", "args", "fragment"),
    [
        (
            "forge_add_role_users",
            "is refused",
            {"role_id": "R1", "groups": [{"_id": "everyone", "Name": "Everyone"}]},
            "confirm_group_notification=True",
        ),
        (
            "forge_grant_tier",
            "is refused loudly",
            {"kind": "process", "flow_id": "F1", "role_id": "R1", "tier": "Read-only"},
            "valid",
        ),
    ],
)
async def test_each_claimed_refusal_is_real_and_writes_nothing(
    tool_name: str, phrase: str, args: dict[str, Any], fragment: str
) -> None:
    flow = FakeFlowRepository()
    app = FakeAppRepository()
    server = _server(_settings(kf_app="App1"), _resources(flow=flow, app=app))

    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
        result = await client.call_tool(tool_name, args, raise_on_error=False)

    assert phrase in " ".join((tools[tool_name].description or "").split())
    assert result.is_error is True
    assert fragment in str(result.content)
    assert flow.calls == [] and app.calls == [], "a refusal must not call Kissflow"


# =====================================================================================
# _register_apps (Stage D group 6): the six application tools.
# =====================================================================================


def _lifespan_factory(
    app: FakeAppRepository,
    flow: FakeFlowRepository | None = None,
    page: FakePageRepository | None = None,
    **settings_overrides: Any,
):
    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {
            "settings": _settings(**settings_overrides),
            "resources": _Resources(
                app=app,
                flow=flow or FakeFlowRepository(),
                page=page or FakePageRepository(),
            ),
        }

    return _lifespan


class _Resources:
    """The subset of `AppResources` the app-family tools actually read --
    `resources.app`/`resources.flow`/`resources.page` -- built by hand so this
    test module does not need a fake for every one of `AppResources`' seven
    ports (matching `tests/unit/infrastructure/mcp/tools/test_flow.py`'s own
    `SimpleNamespace`-based pattern, made a small class here since three
    fields need naming)."""

    def __init__(
        self, app: FakeAppRepository, flow: FakeFlowRepository, page: FakePageRepository
    ) -> None:
        self.app = app
        self.flow = flow
        self.page = page


# ---- forge_create_app ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_create_app_maps_arguments_and_returns_the_response() -> None:
    fake = FakeAppRepository()
    fake.results["create_application"] = ["App_1"]
    fake.results["list_applications"] = [[], [{"_id": "App_1", "Name": "Sample App"}]]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool("forge_create_app", {"name": "Sample App"})

    assert result.structured_content["app_id"] == "App_1"
    assert result.structured_content["verified"] is True
    create_calls = [c for c in fake.calls if c[0] == "create_application"]
    assert create_calls == [("create_application", ("Sample App",), {})]
    # `ForgeCreateAppResponse`'s own key set.
    assert set(result.structured_content) == {
        "app_id",
        "name",
        "verified",
        "supported",
        "note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_create_app_application_error_becomes_a_tool_error() -> None:
    fake = FakeAppRepository()
    fake.results["create_application"] = ["App_1"]
    fake.results["list_applications"] = [[], []]  # never verifies

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="did not verify"):
            await client.call_tool("forge_create_app", {"name": "Sample App"})


@pytest.mark.asyncio
async def test_forge_create_app_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeAppRepository()
    server = create_server(
        _lifespan_factory(
            fake, kf_dev_access_key_id=None, kf_dev_access_key_secret=None
        )
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool("forge_create_app", {"name": "Sample App"})
    assert fake.calls == []


# ---- forge_list_apps -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_list_apps_maps_arguments_and_returns_the_response() -> None:
    fake = FakeAppRepository()
    fake.results["list_applications"] = [[{"_id": "App_1", "Name": "Demo"}]]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool("forge_list_apps", {})

    assert result.structured_content["apps"] == [{"_id": "App_1", "Name": "Demo"}]
    assert result.structured_content["count"] == 1
    # `ForgeListAppsResponse`'s own key set -- read-only, no `snapshot_version`.
    assert set(result.structured_content) == {"apps", "count"}


@pytest.mark.asyncio
async def test_forge_list_apps_application_error_becomes_a_tool_error() -> None:
    class _Failing(FakeAppRepository):
        async def list_applications(self):  # type: ignore[override]
            raise RepositoryError("500 Internal Server Error")

    server = create_server(_lifespan_factory(_Failing()))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="500 Internal Server Error"):
            await client.call_tool("forge_list_apps", {})


@pytest.mark.asyncio
async def test_forge_list_apps_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeAppRepository()
    server = create_server(
        _lifespan_factory(
            fake, kf_dev_access_key_id=None, kf_dev_access_key_secret=None
        )
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool("forge_list_apps", {})
    assert fake.calls == []


# ---- forge_publish_app ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_publish_app_maps_arguments_and_returns_the_response() -> None:
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [
        Navigation.from_wire({}),
        Navigation.from_wire({"_meta_version": "v9"}),
    ]

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        result = await client.call_tool("forge_publish_app", {"app_id": "App1"})

    assert result.structured_content["published"] is True
    assert result.structured_content["meta_version"] == "v9"
    # `ForgePublishAppResponse`'s own key set.
    assert set(result.structured_content) == {
        "app_id",
        "published",
        "runtime_id",
        "meta_version",
        "note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_publish_app_falls_back_to_settings_kf_app() -> None:
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [Navigation.from_wire({}), Navigation.from_wire({})]

    server = create_server(_lifespan_factory(fake, kf_app="App9"))
    async with Client(server) as client:
        await client.call_tool("forge_publish_app", {"app_id": ""})

    publish_calls = [c for c in fake.calls if c[0] == "publish_app"]
    assert publish_calls == [("publish_app", ("App9",), {})]


@pytest.mark.asyncio
async def test_forge_publish_app_application_error_becomes_a_tool_error() -> None:
    fake = FakeAppRepository()

    server = create_server(_lifespan_factory(fake))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool("forge_publish_app", {"app_id": ""})
    assert fake.calls == []


@pytest.mark.asyncio
async def test_forge_publish_app_no_key_pair_fails_before_the_use_case_runs() -> None:
    fake = FakeAppRepository()
    server = create_server(
        _lifespan_factory(
            fake, kf_dev_access_key_id=None, kf_dev_access_key_secret=None
        )
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool("forge_publish_app", {"app_id": "App1"})
    assert fake.calls == []


# ---- forge_create_template_app -------------------------------------------------------


def _bare_process_draft(name: str) -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "_meta_version": "v1",
            "M1": {"Id": "M1", "Kind": "Model", "Name": name, "FlowType": "Process"},
        }
    )


class _StatefulFlow(FakeFlowRepository):
    """See `tests/unit/application/use_cases/app/test_forge_create_template_app.py`'s
    own `_StatefulFlow`: `put_draft` really persists, so the later read-backs
    (the graph verify AND the doctor read) reflect what was actually written."""

    def __init__(self, draft: FlowDraft) -> None:
        super().__init__()
        self.draft = draft

    async def get_draft(self, app_id: str, kind: str, flow_id: str) -> FlowDraft:  # type: ignore[override]
        self.calls.append(("get_draft", (app_id, kind, flow_id), {}))
        return self.draft

    async def put_draft(  # type: ignore[override]
        self, app_id: str, kind: str, flow_id: str, new: FlowDraft, expect_version
    ) -> FlowDraft:
        self.calls.append(
            (
                "put_draft",
                (app_id, kind, flow_id, new),
                {"expect_version": expect_version},
            )
        )
        self.draft = new
        return new


@pytest.mark.asyncio
async def test_forge_create_template_app_maps_arguments_and_returns_the_response() -> (
    None
):
    name = "Sample Template App"
    role_name = f"{name} Role"
    app = FakeAppRepository()
    app.results["create_application"] = ["App_1"]
    app.results["list_applications"] = [[], [{"_id": "App_1", "Name": name}]]
    app.results["create_app_role"] = ["R1"]
    app.results["list_app_roles"] = [[{"_id": "R1", "Name": role_name}]]
    app.results["get_app_draft"] = [
        Navigation.from_wire({}),
        Navigation.from_wire({"_meta_version": "appv2"}),
    ]
    flow = _StatefulFlow(_bare_process_draft(name))
    flow.results["create_flow"] = ["F1"]
    roster = [{"_id": "R1", "Role": "DataAdmin"}]
    flow.results["get_members"] = [roster, roster]
    flow.results["get_flow_detail"] = [{"_id": "F1", "Status": "Live"}]

    server = create_server(_lifespan_factory(app, flow))
    async with Client(server) as client:
        result = await client.call_tool("forge_create_template_app", {"name": name})

    assert result.structured_content["app_id"] == "App_1"
    assert result.structured_content["flow_id"] == "F1"
    assert result.structured_content["process_status"] == "Live"
    # `ForgeCreateTemplateAppResponse`'s own key set. `members`/`app_publish`/
    # `doctor` lose their own `isError` key (the main session's decision,
    # `brief_stage_d_common.md` group 5/6 review): the facts stay in the
    # other keys (`doctor.problems`).
    assert set(result.structured_content) == {
        "app_id",
        "name",
        "flow_id",
        "role_id",
        "role_name",
        "members",
        "process_status",
        "app_publish",
        "doctor",
        "app_url",
        "process_url",
        "url_verified",
        "graph_nodes_verified",
        "snapshot_version",
    }
    assert "isError" not in result.structured_content["members"]
    assert "isError" not in result.structured_content["app_publish"]
    assert "isError" not in result.structured_content["doctor"]


@pytest.mark.asyncio
async def test_forge_create_template_app_application_error_becomes_a_tool_error() -> (
    None
):
    class _Refusing(FakeAppRepository):
        async def create_application(self, name: str) -> str:  # type: ignore[override]
            raise RepositoryError("FlowNameAlreadyExists")

    app = _Refusing()
    app.results["list_applications"] = [[]]

    server = create_server(_lifespan_factory(app))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="FlowNameAlreadyExists"):
            await client.call_tool(
                "forge_create_template_app", {"name": "Sample Template App"}
            )


@pytest.mark.asyncio
async def test_forge_create_template_app_no_key_pair_fails_before_use_case_runs() -> (
    None
):
    app = FakeAppRepository()
    server = create_server(
        _lifespan_factory(app, kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "forge_create_template_app", {"name": "Sample Template App"}
            )
    assert app.calls == []


# ---- forge_share_report --------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_share_report_maps_arguments_and_returns_the_response() -> None:
    flow = FakeFlowRepository()
    flow.results["post_report_member_batch"] = [{"ok": True}]
    members = [{"_id": "m1", "Name": "Lead", "Kind": "AppRole", "Role": "Ro_lead"}]

    server = create_server(_lifespan_factory(FakeAppRepository(), flow))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_share_report",
            {
                "flow_id": "F1",
                "report_id": "Rep1",
                "members": members,
                "app_id": "A1",
            },
        )

    assert result.structured_content["verified"] is None
    assert result.structured_content["posted"] == {"ok": True}
    post_calls = [c for c in flow.calls if c[0] == "post_report_member_batch"]
    assert post_calls == [
        ("post_report_member_batch", ("A1", "F1", "Rep1", members), {})
    ]
    # `ForgeShareReportResponse`'s own key set.
    assert set(result.structured_content) == {
        "flow_id",
        "report_id",
        "requested",
        "posted",
        "verified",
        "note",
        "snapshot_version",
    }


@pytest.mark.asyncio
async def test_forge_share_report_application_error_becomes_a_tool_error() -> None:
    flow = FakeFlowRepository()

    server = create_server(_lifespan_factory(FakeAppRepository(), flow))
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_share_report",
                {"flow_id": "F1", "report_id": "Rep1", "members": []},
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_forge_share_report_no_key_pair_fails_before_the_use_case_runs() -> None:
    flow = FakeFlowRepository()
    server = create_server(
        _lifespan_factory(
            FakeAppRepository(),
            flow,
            kf_dev_access_key_id=None,
            kf_dev_access_key_secret=None,
        )
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool(
                "forge_share_report",
                {"flow_id": "F1", "report_id": "Rep1", "members": [], "app_id": "A1"},
            )
    assert flow.calls == []


# ---- forge_sweep ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_sweep_maps_arguments_and_returns_the_response() -> None:
    app = FakeAppRepository()
    app.results["list_applications"] = [[{"_id": "App_1", "Name": "Demo"}]]

    server = create_server(_lifespan_factory(app))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_sweep", {"scope": "apps", "app_id": "App_1"}
        )

    assert result.structured_content["ok"] is True
    assert result.structured_content["results"]["apps"]["count"] == 1
    # `ForgeSweepResponse`'s own key set. `forge_sweep` is a verdict tool
    # (rule 7): its own `ok` IS the response's own key, not an `isError`.
    assert set(result.structured_content) == {"scope", "app_id", "results", "ok"}


@pytest.mark.asyncio
async def test_forge_sweep_reports_a_failed_sub_scope_as_ok_false() -> None:
    """`forge_sweep` is a verdict tool (rule 7, `brief_stage_d_common.md`): a
    sub-scope's own read failure surfaces as `ok: False` in the response, never
    as a `ToolError` -- the call itself worked."""

    class _Failing(FakeAppRepository):
        async def list_applications(self):  # type: ignore[override]
            raise RepositoryError("boom")

    server = create_server(_lifespan_factory(_Failing()))
    async with Client(server) as client:
        result = await client.call_tool(
            "forge_sweep", {"scope": "apps", "app_id": "App_1"}
        )

    assert result.structured_content["ok"] is False
    assert result.structured_content["results"]["apps"]["status"] == "error"


@pytest.mark.asyncio
async def test_forge_sweep_no_key_pair_fails_before_the_use_case_runs() -> None:
    app = FakeAppRepository()
    server = create_server(
        _lifespan_factory(app, kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    )
    async with Client(server) as client:
        with pytest.raises(ToolError, match="no Kissflow key pair"):
            await client.call_tool("forge_sweep", {"scope": "apps"})
    assert app.calls == []
