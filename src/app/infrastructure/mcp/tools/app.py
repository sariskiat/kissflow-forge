"""The app-family tool module (app roles, applications).

`register(mcp)` wires every app-family tool onto the new, thin server (spec
G12). Each work group below is its own function, filled independently in
Stage D by the app family writer. `ruff format` caps blank lines at two, so
the distance between groups below is a comment block, not blank padding --
either way, two writers filling different groups produce a diff-clean
merge, since neither one's edit region reaches the other's.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from app.application.models.requests.app.forge_add_member_roles_request import (
    ForgeAddMemberRolesRequest,
)
from app.application.models.requests.app.forge_add_role_users_request import (
    ForgeAddRoleUsersRequest,
)
from app.application.models.requests.app.forge_create_app_request import (
    ForgeCreateAppRequest,
)
from app.application.models.requests.app.forge_create_app_role_request import (
    ForgeCreateAppRoleRequest,
)
from app.application.models.requests.app.forge_create_template_app_request import (
    ForgeCreateTemplateAppRequest,
)
from app.application.models.requests.app.forge_delete_app_role_request import (
    ForgeDeleteAppRoleRequest,
)
from app.application.models.requests.app.forge_grant_tier_request import (
    ForgeGrantTierRequest,
)
from app.application.models.requests.app.forge_list_app_roles_request import (
    ForgeListAppRolesRequest,
)
from app.application.models.requests.app.forge_list_apps_request import (
    ForgeListAppsRequest,
)
from app.application.models.requests.app.forge_member_batch_request import (
    ForgeMemberBatchRequest,
)
from app.application.models.requests.app.forge_publish_app_request import (
    ForgePublishAppRequest,
)
from app.application.models.requests.app.forge_set_role_preference_request import (
    ForgeSetRolePreferenceRequest,
)
from app.application.models.requests.app.forge_share_report_request import (
    ForgeShareReportRequest,
)
from app.application.models.requests.app.forge_sweep_request import ForgeSweepRequest
from app.application.models.responses.app.forge_add_member_roles_response import (
    ForgeAddMemberRolesResponse,
)
from app.application.models.responses.app.forge_add_role_users_response import (
    ForgeAddRoleUsersResponse,
)
from app.application.models.responses.app.forge_create_app_response import (
    ForgeCreateAppResponse,
)
from app.application.models.responses.app.forge_create_app_role_response import (
    ForgeCreateAppRoleResponse,
)
from app.application.models.responses.app.forge_create_template_app_response import (
    ForgeCreateTemplateAppResponse,
)
from app.application.models.responses.app.forge_delete_app_role_response import (
    ForgeDeleteAppRoleResponse,
)
from app.application.models.responses.app.forge_grant_tier_response import (
    ForgeGrantTierResponse,
)
from app.application.models.responses.app.forge_list_app_roles_response import (
    ForgeListAppRolesResponse,
)
from app.application.models.responses.app.forge_list_apps_response import (
    ForgeListAppsResponse,
)
from app.application.models.responses.app.forge_member_batch_response import (
    ForgeMemberBatchResponse,
)
from app.application.models.responses.app.forge_publish_app_response import (
    ForgePublishAppResponse,
)
from app.application.models.responses.app.forge_set_role_preference_response import (
    ForgeSetRolePreferenceResponse,
)
from app.application.models.responses.app.forge_share_report_response import (
    ForgeShareReportResponse,
)
from app.application.models.responses.app.forge_sweep_response import (
    ForgeSweepResponse,
)
from app.application.use_cases.app.forge_add_member_roles import ForgeAddMemberRoles
from app.application.use_cases.app.forge_add_role_users import ForgeAddRoleUsers
from app.application.use_cases.app.forge_create_app import ForgeCreateApp
from app.application.use_cases.app.forge_create_app_role import ForgeCreateAppRole
from app.application.use_cases.app.forge_create_template_app import (
    ForgeCreateTemplateApp,
)
from app.application.use_cases.app.forge_delete_app_role import ForgeDeleteAppRole
from app.application.use_cases.app.forge_grant_tier import ForgeGrantTier
from app.application.use_cases.app.forge_list_app_roles import ForgeListAppRoles
from app.application.use_cases.app.forge_list_apps import ForgeListApps
from app.application.use_cases.app.forge_member_batch import ForgeMemberBatch
from app.application.use_cases.app.forge_publish_app import ForgePublishApp
from app.application.use_cases.app.forge_set_role_preference import (
    ForgeSetRolePreference,
)
from app.application.use_cases.app.forge_share_report import ForgeShareReport
from app.application.use_cases.app.forge_sweep import ForgeSweep
from app.domain.value_objects.kinds import FlowKindArg, SweepScope, Tier, TierKind
from app.infrastructure.mcp.tools import _shared


def register(mcp: FastMCP) -> None:
    """Register every app-family tool.

    Args:
        mcp: The server `create_server()` is building.
    """
    _register_roles(mcp)
    _register_apps(mcp)


def _register_roles(mcp: FastMCP) -> None:
    """AppRole tools: add role users, grant tier, set role preference, share report,
    member batch, add member roles. Filled by the app family writer (Stage D)."""

    @mcp.tool(title="Grant flow members", annotations=_shared.LIVE_ADD)
    async def forge_member_batch(
        target_flow_id: str,
        source_flow_id: str | None = None,
        kind: FlowKindArg = "process",
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeMemberBatchResponse:
        """LIVE (dev only, KF_APP): grant AppRole members on `target_flow_id` — MEMBERS FIRST per
        CLAUDE.md Permissions (assignees cannot be written before members exist; publish then fails
        MetadataError). Run this BEFORE forge_build_workflow's `roles` assignments; the granted
        `role_ids` in the result are exactly the ids that belong there.

        Two sources, tried in order: (1) harvest from an existing flow in KF_APP — `source_flow_id`
        names it, or omit to auto-discover the first other flow of `kind` with at least one member;
        (2) when neither is available, grant the app's OWN AppRoles instead, discovered at the
        ACCOUNT level (`Role: "DataAdmin"`, `Permission: ["InitiateItems"]` — proven live 2026-08-07 as
        the exact grant that lets the initiator submit their own draft; `Permission: []` 200s the grant
        but still leaves the initiator refused). Only when BOTH sources come up empty does this report
        harvested=[]/role_ids=[] with an explanatory `note` rather than failing — a caller must be able
        to tell "nothing to grant yet" apart from a real error. That empty case is NOT a dead end and
        needs no human: forge_create_app_role makes an app-scoped AppRole in one call, after which
        re-running this works (forge_add_member_roles does both at once).

        The account-level path always reports `roles_seen` (app-scoped AppRoles the account list
        returned) next to `roles_granted` and `roles_unusable`, so "granted 1 of the 2 roles that
        exist" can never be silent — seen == granted + unusable, always.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeMemberBatchRequest(
                target_flow_id=target_flow_id,
                source_flow_id=source_flow_id,
                kind=kind,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeMemberBatch(
                resources.flow, resources.app
            ),
        )

    @mcp.tool(title="Create and grant app roles", annotations=_shared.LIVE_ADD)
    async def forge_add_member_roles(
        target_flow_id: str,
        roles: dict[str, str],
        kind: FlowKindArg = "process",
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeAddMemberRolesResponse:
        """LIVE (dev only, KF_APP): grant AppRoles onto `target_flow_id`, CREATING each role scoped to
        KF_APP first if it does not already exist there. `roles` is `{role_id: display_name}`; matching
        is by NAME — an existing KF_APP-scoped role with that name is reused (idempotent), else one is
        created via `POST /app_role/2/{acct}` (proven live 2026-08-08; CORRECTS the old CLAUDE.md claim
        that only the builder UI creates roles). member/batch rejects any role NOT scoped to KF_APP
        (KISSFLOW_ERROR_00051), so foreign roles cannot be re-granted directly — they must be recreated
        here. Grant is Role=DataAdmin, Permission=["InitiateItems"]. Run BEFORE forge_build_workflow.
        Returns `resolved` = `{display_name: a00_role_id}` so the caller can remap step->name onto
        step->a00_id for build_workflow's `roles=`/step assignees.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeAddMemberRolesRequest(
                target_flow_id=target_flow_id,
                roles=roles,
                kind=kind,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeAddMemberRoles(
                resources.flow, resources.app
            ),
        )

    @mcp.tool(title="Create app role", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_create_app_role(
        name: str,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeCreateAppRoleResponse:
        """LIVE (dev only): create an AppRole scoped to `app_id` (defaults to KF_APP). PROVEN live
        2026-08-08: `POST /app_role/2/{acct}` body `{"Name": name, "_application_id": app_id}` -> 200
        `{"_id": "RoDy...", "Name": name}`. A role MUST be scoped to KF_APP before member/batch will
        bind it onto one of the app's flows (00051 otherwise). For the idempotent create-then-grant
        path prefer `forge_add_member_roles` (reuses an existing same-name role); this standalone is for
        explicit one-off creation. Returns the new role `_id`.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreateAppRoleRequest(
                name=name,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeCreateAppRole(resources.app),
        )

    @mcp.tool(title="Delete app role", annotations=_shared.LIVE_REPLACE_ONCE)
    async def forge_delete_app_role(
        role_id: str,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeDeleteAppRoleResponse:
        """LIVE (dev only): delete an AppRole by id. PROVEN live 2026-08-08: `DELETE /app_role/2/{acct}/
        {role_id}` -> 200 `{"status":"success"}`; re-GET 403s `RoleDoesNotExistsError`, confirming real
        deletion. Use to clean up throwaway roles from probes/failed builds. Verify deletion via the
        list route (`forge_list_app_roles`), never the delete response alone (CLAUDE.md Page DELETE
        warns the same soft-200 trap).
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeDeleteAppRoleRequest(
                role_id=role_id,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeDeleteAppRole(resources.app),
        )

    @mcp.tool(title="List app roles", annotations=_shared.LIVE_READ)
    async def forge_list_app_roles(
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeListAppRolesResponse:
        """READ-ONLY (dev only): list the AppRoles scoped to `app_id` (defaults to KF_APP).

        The account route (`GET /app_role/2/{acct}/list`, paged) is LEAKAGE-PRONE — it returns every
        AppRole in the ACCOUNT (356 of them in the probe tenant), which is why this tool always
        filters to ONE application, the same scope `forge_create_app_role` writes at. Matches on
        either scope signal the list records carry (`Applications[]._id` or the top-level
        `_application_id`), so a freshly created role is not silently dropped.

        This is the LIST route `forge_delete_app_role` tells you to verify a deletion against, and
        the one to check for an existing same-name role before minting another: a write response
        alone proves nothing (CLAUDE.md "THE RULE"). Returns `roles` as a list of `{_id, Name}`.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeListAppRolesRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeListAppRoles(resources.app),
        )

    @mcp.tool(title="Add users to a role", annotations=_shared.LIVE_ADD)
    async def forge_add_role_users(
        role_id: str,
        user_query: str | None = None,
        user_ids: list[dict[str, Any]] | None = None,
        groups: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "Groups to grant, as assignee-shaped dicts carrying an _id, "
                    "e.g. "
                    '[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}] '
                    "for the whole-tenant grant. Rides the same write as "
                    "`user_ids` but under its own wire key: a group placed in "
                    "`user_ids` is refused UserDoesNotExistError. Read-back is "
                    "weaker than for users — see the tool description. REFUSED "
                    "unless confirm_group_notification=True, because granting "
                    "a group EMAILS every member."
                )
            ),
        ] = None,
        confirm_group_notification: Annotated[
            bool,
            Field(
                description=(
                    "Required to be True before any `groups` grant will be "
                    "written. Granting a group makes Kissflow email every "
                    "member of it, and the mail cannot be recalled — on a "
                    "whole-tenant group that is everyone in the account. Leave "
                    "False and grant a single developer with `user_query` "
                    "when testing."
                )
            ),
        ] = False,
        force_regrant_groups: Annotated[
            bool,
            Field(
                description=(
                    "Overrides the GroupCount-based duplicate-group refusal. "
                    "When the role detail already reports GroupCount > 0, a "
                    "repeat `groups` grant is refused and reported under "
                    "`groups_refused` — this tenant exposes no group LIST, so "
                    "a re-grant cannot be proven new and re-sending it would "
                    "re-email every member (the 2026-08-20 fan-out). Pass "
                    "True only when granting a genuinely DIFFERENT group to a "
                    "role that already carries one. Still requires "
                    "confirm_group_notification=True in the same call."
                )
            ),
        ] = False,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeAddRoleUsersResponse:
        """LIVE write (dev only): grant one or more users onto an AppRole (#52). Give EITHER
        `user_query` (a name/email substring searched via `GET /user/2/{acct}/assignee?q=...`) OR
        `user_ids` (assignee objects `{_id, Kind, Email, Name}` a caller already resolved elsewhere)
        — or `groups`, at least one of the three is required. Existing members are never dropped: the
        write merges onto the role's current `Members`, never replaces it.

        `groups` grants a GROUP rather than a person, e.g. `[{"_id": "everyone", "Kind": "Group",
        "Name": "Everyone"}]` — the whole-tenant grant. Groups ride the SAME write under their own
        key: a group object placed in `user_ids` is refused `UserDoesNotExistError`, because the
        endpoint validates that array as users only. ⚠️ Read-back for groups is WEAKER than for
        users: this tenant exposes a nullable `GroupCount` on the role detail but no group LIST, so a
        granted group is verified by that count MOVING, lands in `groups_unverified` when it does not,
        and `groups_note` states which happened. For the same reason this call cannot promise to
        preserve groups that were already on the role — it cannot enumerate them.

        🚨 A GROUP GRANT EMAILS EVERY MEMBER OF THAT GROUP, and the mail cannot be recalled — on a
        whole-tenant group ("everyone") that is every person in the account. This is the only effect
        on this surface that reaches PEOPLE rather than the graph, so it fails CLOSED: `groups` is
        REFUSED unless `confirm_group_notification=True` is passed in the same call. NEVER test this
        tool with a group. Test it by granting ONE developer: `user_query="<your name>"`.

        ⚠️ Asymmetric wire keys (CLAUDE.md Pages, RESOLVED 2026-08-12): the role reads back under
        `Members` but must be WRITTEN under `Users` — a body carrying `Members` instead 200s and
        silently no-ops; this tool writes the correct key for you. Verified by re-reading
        `Members`/`UserCount`; `not_found` covers both a `user_query` with zero matches and a
        candidate that was written but failed to verify on read-back.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeAddRoleUsersRequest(
                role_id=role_id,
                user_query=user_query,
                user_ids=user_ids,
                groups=groups,
                confirm_group_notification=confirm_group_notification,
                force_regrant_groups=force_regrant_groups,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeAddRoleUsers(resources.app),
        )

    @mcp.tool(title="Grant permission tier", annotations=_shared.LIVE_REPLACE)
    async def forge_grant_tier(
        kind: TierKind,
        flow_id: str,
        role_id: str,
        tier: Tier,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeGrantTierResponse:
        """LIVE write (dev only, KF_APP): grant an AppRole a named permission TIER on a flow
        (shapes/app_role_grant.json note 0, browser-proven 2026-08-12). `kind` is "process" (tiers:
        "No access" | "Initiate" | "Manage") or "case" (adds "Read-only" | "Edit"). "No access" is a
        REAL removal (`DELETE .../member/{role_id}`), never a Permission:[] grant — that shape is
        itself the "Initiate" tier on a process. An unknown `(kind, tier)` pair is refused loudly,
        naming the valid set for that kind, rather than guessing the nearest tier.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeGrantTierRequest(
                kind=kind,
                flow_id=flow_id,
                role_id=role_id,
                tier=tier,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeGrantTier(
                resources.flow, resources.app
            ),
        )

    @mcp.tool(title="Set role default page", annotations=_shared.LIVE_REPLACE)
    async def forge_set_role_preference(
        role_id: str,
        default_page: str | None = None,
        default_navigation: str | None = None,
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeSetRolePreferenceResponse:
        """LIVE write (dev only): set an AppRole's own default page/navigation
        (`PUT /app_role/2/{acct}/{role_id}?_application_id={app}` body
        `{"Preference": {"DefaultPage": ..., "DefaultNavigation": ...}}`). The sentinel string
        `"Default"` is valid for either key ("use the platform default"). At least one of
        `default_page`/`default_navigation` is required. Reuses the SAME write route as
        forge_add_role_users, so existing membership is never dropped by this call. Verified by
        re-reading the role's own `Preference` block.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSetRolePreferenceRequest(
                role_id=role_id,
                default_page=default_page,
                default_navigation=default_navigation,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeSetRolePreference(resources.app),
        )


# ============================================================================
# _register_roles ends above this block; _register_apps starts below it.
# This block is spacing, not documentation: it exists only so that a writer
# filling _register_roles and a writer filling _register_apps touch lines
# far enough apart that git merges their two changes without a conflict. Do
# not delete it to "clean up" the file -- shrinking it defeats its one
# purpose. Twenty-plus lines, deliberately, matching every other group
# boundary in this file and its eight siblings under
# infrastructure/mcp/tools/.
#
# NEVER GRANT A GROUP TO TEST ANYTHING (see CLAUDE.md > Members first).
# Granting a group to an AppRole or to app membership makes Kissflow notify
# EVERY MEMBER of that group, and membership writes are add-only -- there is
# no removal route. To test membership, grant one named developer.
# ============================================================================


def _register_apps(mcp: FastMCP) -> None:
    """Application tools: create app, create template app, publish app.
    Filled by the app family writer (Stage D)."""

    @mcp.tool(title="Create application", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_create_app(name: str, *, ctx: Context) -> ForgeCreateAppResponse:
        """LIVE (dev only): create a NEW application (`POST /flow/2/{acct}/application`), verified via
        the application LIST route — proven live 2026-08-06 (see the Node G DEV report's probe
        matrix). Deletion needs archive-first, same rule as a process; use
        forge_delete_flow(kind="application", ...).
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreateAppRequest(name=name),
            build_use_case=lambda resources: ForgeCreateApp(app=resources.app),
        )

    @mcp.tool(title="List applications", annotations=_shared.LIVE_READ)
    async def forge_list_apps(*, ctx: Context) -> ForgeListAppsResponse:
        """LIVE (dev only): list the applications this credential can see (`GET
        /flow/2/{acct}/application`). Needs NO app selected — this is how a user discovers which
        app_id to pass into the other app-scoped tools. Returns `apps` as a list of `{_id, Name}`.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=ForgeListAppsRequest,
            build_use_case=lambda resources: ForgeListApps(app=resources.app),
        )

    @mcp.tool(title="Publish application", annotations=_shared.LIVE_ADD)
    async def forge_publish_app(
        app_id: str, *, ctx: Context
    ) -> ForgePublishAppResponse:
        """LIVE publish (dev only): compile an APPLICATION's draft to its live version, WITH a
        genuine post-publish read-back (THE RULE: a 200 from publish proves nothing by itself) — the
        fresh `meta_version` plus any `Runtime_`-prefixed node id found on the app draft, when one is
        present (⚠️ that shape is UNCAPTURED on this tenant — `runtime_id` is honestly `None` with a
        note when absent, never guessed). Equivalent to `forge_publish(kind="application", ...)` plus
        this extra read-back.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgePublishAppRequest(
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id)
            ),
            build_use_case=lambda resources: ForgePublishApp(app=resources.app),
        )

    @mcp.tool(title="Create template app", annotations=_shared.LIVE_ADD_ONCE)
    async def forge_create_template_app(
        name: Annotated[
            str,
            Field(
                description=(
                    "Display name for the new application — the only argument. A duplicate name surfaces "  # noqa: E501
                    "the platform's FlowNameAlreadyExists error loud; pick another name, never auto-rename."  # noqa: E501
                )
            ),
        ],
        *,
        ctx: Context,
    ) -> ForgeCreateTemplateAppResponse:
        """LIVE (dev only): ONE call — create a fresh Template App carrying the transplanted source
        template process (ADR-0006, spec #10), published end to end, and return its builder URL.
        Runs as the CALLING user's own Kissflow identity (the key pair on the request headers over
        HTTP; the env pair on stdio) — never a shared credential. `name` is the only
        argument; a duplicate app name surfaces the platform's FlowNameAlreadyExists loud (no
        auto-rename). The response carries the post-publish doctor read-back (`doctor`), the member
        grant audit (`members`), and `app_url`/`process_url`. `app_url` uses a derived,
        not-yet-live-verified route pattern — `url_verified: False`. A failed run archives+deletes the
        half-built app (and its created AppRole) rather than leaving junk in the tenant.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeCreateTemplateAppRequest(name=name),
            build_use_case=lambda resources: ForgeCreateTemplateApp(
                app=resources.app,
                flow=resources.flow,
                base_url=ctx.lifespan_context["settings"].base_url,
            ),
        )

    @mcp.tool(title="Share flow report", annotations=_shared.LIVE_ADD)
    async def forge_share_report(
        flow_id: str,
        report_id: str,
        members: list[dict[str, Any]],
        app_id: str | None = None,
        *,
        ctx: Context,
    ) -> ForgeShareReportResponse:
        """LIVE write (dev only, KF_APP): grant members on a flow REPORT (CLAUDE.md Permissions:
        "Flow REPORTS have the same member surface" as a flow — same member/batch body shape, Role
        "Member" ok). A report with zero members renders "You don't have access to this component" in
        any page chart that uses it. No documented GET route exists for a report's own member list, so
        this is honestly reported as `verified: null` (not independently read-back checked), unlike
        every write-verifying tool above.
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeShareReportRequest(
                flow_id=flow_id,
                report_id=report_id,
                members=members,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeShareReport(flow=resources.flow),
        )

    @mcp.tool(title="Inventory sweep", annotations=_shared.LIVE_READ)
    async def forge_sweep(
        scope: SweepScope, app_id: str | None = None, *, ctx: Context
    ) -> ForgeSweepResponse:
        """READ-ONLY (dev only): full-inventory discovery sweep. `scope` is one of
        "apps"|"flows"|"pages"|"roles"|"lists"|"all". `app_id` defaults to the configured `KF_APP`.
        Every leakage-prone route (CLAUDE.md: `list_flows`/`list_lists` return the WHOLE ACCOUNT
        without `_application_id`) is already scoped inside the client this sweep uses. Each
        requested sub-scope lands in exactly one bucket per the result's own `status`: `read` (with
        its item count + inventory), `error` (never swallowed), or `skipped` ("pages" only, when no
        app_id is available at all).
        """  # noqa: E501
        return await _shared.run_use_case(
            ctx,
            build_request=lambda: ForgeSweepRequest(
                scope=scope,
                app_id=ctx.lifespan_context["settings"].resolve_app_id(app_id),
            ),
            build_use_case=lambda resources: ForgeSweep(
                app=resources.app, flow=resources.flow, page=resources.page
            ),
        )
