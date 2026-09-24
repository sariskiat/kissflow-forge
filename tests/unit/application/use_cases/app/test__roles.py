"""Spec for app.application.use_cases.app._roles.

Ports every old test of `apply_add_role_users` (the group-notification guard first),
`apply_grant_tier` and `apply_set_role_preference` from `tests/test_client.py` and
`tests/test_p4_surface.py` onto the async, port-driven shapes. An old `Err("verify")`
refusal on bad input is now `ApplicationError(code=REFUSED)`; an old `Err("http")` is
the port's own `RepositoryError`; an old report with `isError: true` is now an
outcome whose `raise_if_*` check raises `ApplicationError(code=VERIFY_FAILED)`
(review rule 7).
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from tests.fakes.app import FakeAppRepository
from tests.fakes.app_roles import EVERYONE, _reviewer_app, _RoleApp, _TierFlow

from app.application.exceptions import (
    REFUSED,
    VERIFY_FAILED,
    ApplicationError,
    RepositoryError,
)
from app.application.use_cases.app._roles import (
    _TIER_MAP,
    RoleUsersOutcome,
    _existing_group_list,
    _role_write_body,
    add_role_users,
    grant_tier,
    raise_if_incomplete,
    raise_if_unverified_preference,
    raise_if_unverified_tier,
    set_role_preference,
)
from app.domain.value_objects.kinds import Tier, TierKind

APP_ID = "App1"


async def _add(app: _RoleApp, **kwargs: Any) -> RoleUsersOutcome:
    args: dict[str, Any] = {
        "user_query": None,
        "user_ids": None,
        "groups": None,
        "confirm_group_notification": False,
        "force_regrant_groups": False,
    }
    args.update(kwargs)
    return await add_role_users(
        app,
        APP_ID,
        "R1",
        args["user_query"],
        args["user_ids"],
        args["groups"],
        args["confirm_group_notification"],
        args["force_regrant_groups"],
    )


# =====================================================================================
# The group-notification guard: `groups` is refused unless confirm_group_notification.
# =====================================================================================


@pytest.mark.asyncio
async def test_group_grant_is_refused_without_explicit_confirmation() -> None:
    """A group grant NOTIFIES every member, cannot be recalled, and cannot be undone
    (membership writes are add-only). It is the one effect on this surface that
    reaches PEOPLE rather than the graph, so it fails CLOSED."""
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await _add(app, groups=[EVERYONE])

    assert exc_info.value.code == REFUSED
    assert "Everyone" in exc_info.value.message, "must name what it refused to grant"
    assert "CANNOT BE UNDONE" in exc_info.value.message
    assert "user_query" in exc_info.value.message, "must name the safe way to test"
    assert "confirm_group_notification=True" in exc_info.value.message
    assert app.body is None, "a refusal must not write first"
    assert app.calls == [], "a refusal must not even read the role first"


@pytest.mark.asyncio
async def test_group_grant_is_refused_even_alongside_a_user() -> None:
    """The guard is on `groups`, not on the whole call: a user riding along does not
    lift it."""
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await _add(
            app,
            user_ids=[{"_id": "U1", "Kind": "User", "Name": "Ann"}],
            groups=[EVERYONE],
        )

    assert exc_info.value.code == REFUSED
    assert app.body is None


@pytest.mark.asyncio
async def test_group_grant_proceeds_once_confirmed() -> None:
    """The flag is a speed bump, not a wall -- an intended grant still works."""
    app = _RoleApp()

    outcome = await _add(app, groups=[EVERYONE], confirm_group_notification=True)

    assert outcome.groups_added == ("everyone",)
    assert app.body is not None and app.body["Groups"]


@pytest.mark.asyncio
async def test_add_role_users_writes_groups_under_their_own_key() -> None:
    """A group object placed in `Users` is refused UserDoesNotExistError, so the body
    must carry BOTH keys -- Users for people, Groups for groups."""
    app = _RoleApp()

    outcome = await _add(app, groups=[EVERYONE], confirm_group_notification=True)

    assert app.body is not None
    assert app.body["Groups"] == [EVERYONE]
    assert app.body["Users"] == [], "a group must never be smuggled into Users"
    assert outcome.groups_added == ("everyone",)
    raise_if_incomplete(outcome, "forge_add_role_users")  # the old isError False


@pytest.mark.asyncio
async def test_granting_a_single_user_needs_no_confirmation() -> None:
    """The safe path stays frictionless: adding one named person notifies only them."""
    app = _RoleApp()
    app.assignees["Somchai"] = [{"_id": "U1", "Kind": "User", "Name": "Somchai"}]

    await _add(app, user_query="Somchai")

    assert app.body is not None
    assert app.body["Users"] == [{"_id": "U1", "Kind": "User", "Name": "Somchai"}]
    assert "Groups" not in app.body, "a user-only grant must never write Groups"


@pytest.mark.asyncio
async def test_add_role_users_reports_a_group_it_cannot_prove_landed() -> None:
    """THE RULE on the weaker group read-back: GroupCount is the only signal. If it
    does not move, the group is WRITTEN BUT UNPROVEN -- never a success (rule 7)."""
    app = _RoleApp(group_count=None)

    outcome = await _add(app, groups=[EVERYONE], confirm_group_notification=True)

    assert outcome.groups_added == () and outcome.groups_unverified == ("everyone",)
    assert "UNPROVEN" in (outcome.groups_note or "")
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.code == VERIFY_FAILED
    assert "groups_unverified: everyone" in exc_info.value.message


@pytest.mark.asyncio
async def test_add_role_users_refuses_a_malformed_group_before_any_write() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await _add(app, groups=[{"Name": "Everyone"}], confirm_group_notification=True)

    assert exc_info.value.code == REFUSED
    assert "_id" in exc_info.value.message
    assert app.body is None, "a refusal must not write first"
    # Byte-for-byte against `client.py:4681`. `apply_add_role_users` was a
    # public function, so lesson 5 (name the public caller) does not apply:
    # the OLD public name is the one this message keeps (review fix 5).
    bad = {"Name": "Everyone"}
    old = (
        f"apply_add_role_users: each group must be an assignee-shaped dict with an "
        f"_id, e.g. {{'_id': 'everyone', 'Kind': 'Group', 'Name': 'Everyone'}} — got "
        f"{bad!r}"
    )
    assert exc_info.value.message == old


@pytest.mark.asyncio
async def test_add_role_users_group_notification_names_the_groups() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as named:
        await _add(app, groups=[{"_id": "gid_only"}, "not_a_dict"])
    assert named.value.code == REFUSED
    assert "gid_only" in named.value.message

    with pytest.raises(ApplicationError) as unnamed:
        await _add(app, groups=["invalid"])
    assert unnamed.value.code == REFUSED
    assert "<unnamed>" in unnamed.value.message


@pytest.mark.asyncio
async def test_add_role_users_still_requires_at_least_one_grant() -> None:
    app = _RoleApp()

    with pytest.raises(ApplicationError) as exc_info:
        await _add(app)

    assert exc_info.value.code == REFUSED
    assert "groups" in exc_info.value.message
    assert app.calls == []
    # Byte-for-byte against `client.py:4634` (`apply_add_role_users` was a
    # public function; review fix 5 reverses an earlier "use the tool name"
    # instruction for this exact message).
    assert exc_info.value.message == (
        "apply_add_role_users: give user_query, user_ids or groups"
    )


# ---- the GroupCount duplicate-group guard ----


@pytest.mark.asyncio
async def test_group_regrant_is_blocked_when_group_count_already_present() -> None:
    """No group LIST on this tenant, so the guard gates on GroupCount: once it shows a
    group present, a second identical grant is refused, never resent (2026-08-20)."""
    app = _RoleApp()
    first = await _add(app, groups=[EVERYONE], confirm_group_notification=True)
    assert first.groups_added == ("everyone",)
    assert app.body is not None and app.body.get("Groups")
    app.body = None  # reset so a second write would be visible

    second = await _add(app, groups=[EVERYONE], confirm_group_notification=True)

    assert app.body is None, "GroupCount shows a group present -- must not rewrite"
    # A refused group lands in its OWN bucket, never groups_already_present.
    assert second.groups_refused == ("everyone",)
    assert second.groups_already_present == ()
    assert "force_regrant_groups" in (second.groups_note or "")
    raise_if_incomplete(second, "forge_add_role_users")  # the old isError False


@pytest.mark.asyncio
async def test_group_regrant_refusal_survives_a_mixed_call_with_new_users() -> None:
    """A mixed call (a new user alongside the blocked group) exits through the final
    report, and the refused group must still land in `groups_refused` there."""
    app = _RoleApp(group_count=1)

    outcome = await _add(
        app,
        user_ids=[{"_id": "U9", "Kind": "User", "Name": "Somchai"}],
        groups=[EVERYONE],
        confirm_group_notification=True,
    )

    assert app.body is not None, "the user grant must still be written"
    assert "Groups" not in app.body, "the blocked group must not ride along"
    assert outcome.groups_refused == ("everyone",)
    assert outcome.groups_added == () and outcome.groups_already_present == ()
    assert "force_regrant_groups" in (outcome.groups_note or "")


@pytest.mark.asyncio
async def test_group_regrant_proceeds_with_explicit_override() -> None:
    app = _RoleApp()
    await _add(app, groups=[EVERYONE], confirm_group_notification=True)
    app.body = None

    await _add(
        app,
        groups=[EVERYONE],
        confirm_group_notification=True,
        force_regrant_groups=True,
    )

    assert app.body is not None and app.body.get("Groups"), "override still writes"


@pytest.mark.asyncio
async def test_the_override_alone_never_lifts_the_confirmation_guard() -> None:
    app = _RoleApp(group_count=1)

    with pytest.raises(ApplicationError) as exc_info:
        await _add(app, groups=[EVERYONE], force_regrant_groups=True)

    assert exc_info.value.code == REFUSED
    assert app.body is None


# ---- group read-back ----


@pytest.mark.asyncio
async def test_add_role_users_with_existing_and_live_group_list() -> None:
    app = _RoleApp(extra={"Groups": [{"_id": "g_old", "Kind": "Group"}]})
    app.readback = {
        "_id": "R1",
        "Name": "Role",
        "Members": [],
        "UserCount": 0,
        "Groups": [
            {"_id": "g_old", "Kind": "Group"},
            {"_id": "g_new", "Kind": "Group"},
        ],
        "GroupCount": 2,
    }

    outcome = await _add(
        app,
        groups=[
            {"_id": "g_old", "Kind": "Group"},
            {"_id": "g_new", "Kind": "Group"},
            {"_id": "g_missing", "Kind": "Group"},
        ],
        confirm_group_notification=True,
    )

    assert outcome.groups_already_present == ("g_old",)
    assert outcome.groups_added == ("g_new",)
    assert outcome.groups_unverified == ("g_missing",)
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.code == VERIFY_FAILED
    assert "g_missing" in exc_info.value.message


@pytest.mark.asyncio
async def test_add_role_users_no_existing_groups_note() -> None:
    app = _RoleApp(group_count=0)
    app.readback = {
        "_id": "R1",
        "Name": "Role",
        "Members": [],
        "UserCount": 0,
        "GroupCount": 1,
    }

    outcome = await _add(app, groups=[EVERYONE], confirm_group_notification=True)

    assert outcome.groups_added == ("everyone",)
    assert "verified by GroupCount 0 -> 1 only" in (outcome.groups_note or "")


@pytest.mark.asyncio
async def test_add_role_users_live_groups_with_no_initial_existing_groups_note() -> (
    None
):
    app = _RoleApp(group_count=0)
    app.readback = {
        "_id": "R1",
        "Name": "Role",
        "Members": [],
        "UserCount": 0,
        "Groups": [{"_id": "g_new", "Kind": "Group"}],
        "GroupCount": 1,
    }

    outcome = await _add(
        app, groups=[{"_id": "g_new", "Kind": "Group"}], confirm_group_notification=True
    )

    assert outcome.groups_added == ("g_new",)
    assert "existing groups could not be enumerated" in (outcome.groups_note or "")


# =====================================================================================
# forge_add_role_users: users (tests/test_p4_surface.py, tests/test_client.py)
# =====================================================================================


@pytest.mark.asyncio
async def test_add_role_users_by_query_grants_and_verifies() -> None:
    app = _RoleApp()
    app.assignees["ann"] = [
        {"_id": "U1", "Kind": "User", "Email": "ann@x.com", "Name": "Ann"}
    ]

    outcome = await _add(app, user_query="ann")

    assert outcome.added == ("U1",)
    assert outcome.already_present == () and outcome.not_found == ()
    assert outcome.user_count == 1
    raise_if_incomplete(outcome, "forge_add_role_users")  # the old isError False
    # the write key must be "Users", never "Members" (asymmetric wire keys)
    put = next(c for c in app.calls if c[0] == "put_app_role")
    put_app, put_role, put_body = put[1]
    assert (put_app, put_role) == (APP_ID, "R1")
    assert "Users" in put_body and "Members" not in put_body


@pytest.mark.asyncio
async def test_add_role_users_existing_member_is_already_present_no_write() -> None:
    app = _RoleApp(members=[{"_id": "U1", "Kind": "User", "Name": "Ann"}])

    outcome = await _add(app, user_ids=[{"_id": "U1", "Kind": "User", "Name": "Ann"}])

    assert outcome.added == () and outcome.already_present == ("U1",)
    assert outcome.not_found == ()
    assert app.body is None, "an already-present user must never trigger a write"


@pytest.mark.asyncio
async def test_add_role_users_query_with_no_match_reports_not_found() -> None:
    app = _RoleApp()

    outcome = await _add(app, user_query="nobody")

    assert outcome.added == () and outcome.not_found == ("nobody",)
    assert app.body is None
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.code == VERIFY_FAILED
    assert "not_found: nobody" in exc_info.value.message


@pytest.mark.asyncio
async def test_add_role_users_existing_members_carried_over_never_dropped() -> None:
    app = _RoleApp(members=[{"_id": "U0", "Kind": "User", "Name": "Old"}])
    app.assignees["ann"] = [{"_id": "U1", "Kind": "User", "Name": "Ann"}]

    outcome = await _add(app, user_query="ann")

    assert outcome.added == ("U1",)
    live_ids = {m["_id"] for m in app.detail["Members"]}
    assert live_ids == {"U0", "U1"}, "a new user must never drop an existing member"


@pytest.mark.asyncio
async def test_add_role_users_readback_unverified_user() -> None:
    app = _RoleApp()
    app.users_land = False

    outcome = await _add(app, user_ids=[{"_id": "U1", "Kind": "User", "Name": "Ann"}])

    assert outcome.added == ()
    assert outcome.not_found == ("U1",)
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.code == VERIFY_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "nth", "kwargs"),
    [
        ("get_app_role", 1, {"user_query": "Somchai"}),
        ("get_assignee", 1, {"user_query": "Somchai"}),
        ("put_app_role", 1, {"user_ids": [{"_id": "U1", "Kind": "User"}]}),
        ("get_app_role", 2, {"user_ids": [{"_id": "U1", "Kind": "User"}]}),
    ],
    ids=["role_get", "assignee_get", "put", "readback"],
)
async def test_add_role_users_port_error_propagates(
    method: str, nth: int, kwargs: dict[str, Any]
) -> None:
    """An old `Err("http")` from the client is now the port's own `RepositoryError`,
    left to propagate (common brief, item 3)."""
    app = _RoleApp()
    app.assignees["Somchai"] = [{"_id": "U1", "Kind": "User", "Name": "Somchai"}]
    app.raise_on[method] = nth

    with pytest.raises(RepositoryError, match=f"{method} failed"):
        await _add(app, **kwargs)


def test_raise_if_incomplete_names_every_non_empty_bucket() -> None:
    outcome = RoleUsersOutcome(
        role_id="R1", not_found=("nobody",), groups_unverified=("everyone",)
    )
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.message == (
        "forge_add_role_users: not_found: nobody; groups_unverified: everyone"
    )


def test_raise_if_incomplete_names_what_landed_too() -> None:
    """Old payload (`client.py:4594-4610`): the FULL report dict, `added` and
    `groups_note` included, went out even when `isError` was `True`. A group
    write EMAILS EVERY MEMBER of the group the moment it lands -- a caller
    who reads a bare "not_found"/"groups_unverified" message as "nothing
    happened" and retries would email the group again. The raised message
    must say what already landed, exactly as `raise_if_write_failed` folds
    in `collateral`."""
    outcome = RoleUsersOutcome(
        role_id="R1",
        added=("U1",),
        not_found=("U2",),
        groups_added=("G1",),
        groups_unverified=("G2",),
        groups_note=(
            "WRITTEN BUT UNPROVEN: no group list on the role detail and "
            "GroupCount did not move (2 -> 2). Confirm in the builder UI "
            "before relying on it — a 200 from the write proves nothing "
            "(THE RULE)"
        ),
    )
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.code == VERIFY_FAILED
    msg = exc_info.value.message
    assert "not_found: U2" in msg
    assert "groups_unverified: G2" in msg
    assert "added=['U1']" in msg
    assert "groups_added=['G1']" in msg
    assert outcome.groups_note is not None
    assert outcome.groups_note in msg


def test_raise_if_incomplete_omits_the_landed_suffix_when_nothing_landed() -> None:
    outcome = RoleUsersOutcome(role_id="R1", not_found=("nobody",))
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_incomplete(outcome, "forge_add_role_users")
    assert exc_info.value.message == "forge_add_role_users: not_found: nobody"


# ---- the write body ----


def test_role_write_body_moves_members_to_users_and_drops_private_keys() -> None:
    body = _role_write_body(
        {"_id": "R1", "_meta": 1, "Name": "Tech", "Members": [{"_id": "U1"}]}
    )
    assert body == {"Name": "Tech", "Users": [{"_id": "U1"}]}


def test_existing_group_list_reads_either_key_and_never_invents_one() -> None:
    assert _existing_group_list({"Groups": [{"_id": "g1"}, {"Name": "x"}]}) == [
        {"_id": "g1"}
    ]
    assert _existing_group_list({"GroupMembers": [{"_id": "g2"}]}) == [{"_id": "g2"}]
    assert _existing_group_list({"GroupCount": 3}) == []


# =====================================================================================
# forge_grant_tier (tests/test_p4_surface.py)
# =====================================================================================


def test_the_tier_map_matches_the_closed_sets_the_tool_schema_carries() -> None:
    """The anti-drift guard from `tests/test_mcp_boundary.py`: `TierKind`/`Tier` are
    hand-written Literals (the tool schema's enums), so this is what stops them
    diverging from the map the use case actually grants from."""
    assert set(get_args(TierKind)) == set(_TIER_MAP)
    assert set(get_args(Tier)) == {
        tier for by_tier in _TIER_MAP.values() for tier in by_tier
    }


def _posted(flow: _TierFlow) -> list[dict[str, Any]]:
    return [c for c in flow.calls if c[0] == "post_member_batch"][0][1][3]


@pytest.mark.asyncio
async def test_grant_tier_process_manage_grants_dataadmin_initiateitems() -> None:
    flow = _TierFlow()
    outcome = await grant_tier(
        flow, _reviewer_app(), APP_ID, "process", "F1", "R1", "Manage"
    )
    assert outcome.verified is True
    raise_if_unverified_tier(outcome, "forge_grant_tier")  # the old isError False
    member = _posted(flow)[0]
    assert member["Role"] == "DataAdmin" and member["Permission"] == ["InitiateItems"]


@pytest.mark.asyncio
async def test_grant_tier_process_initiate_is_member_with_empty_permission() -> None:
    flow = _TierFlow()
    outcome = await grant_tier(
        flow, _reviewer_app(), APP_ID, "process", "F1", "R1", "Initiate"
    )
    assert outcome.verified is True
    member = _posted(flow)[0]
    assert member["Role"] == "Member" and member["Permission"] == []


@pytest.mark.asyncio
async def test_grant_tier_no_access_deletes_the_member_route() -> None:
    flow = _TierFlow()
    flow.members = [{"_id": "R1", "Role": "DataAdmin", "Permission": ["InitiateItems"]}]
    outcome = await grant_tier(
        flow, _reviewer_app(), APP_ID, "process", "F1", "R1", "No access"
    )
    assert outcome.verified is True
    assert [c for c in flow.calls if c[0] == "delete_member"] == [
        ("delete_member", (APP_ID, "process", "F1", "R1"), {})
    ]
    assert [c for c in flow.calls if c[0] == "post_member_batch"] == [], (
        "No access must never go through member/batch"
    )


@pytest.mark.asyncio
async def test_grant_tier_case_adds_read_only_and_edit_tiers() -> None:
    flow = _TierFlow()
    outcome = await grant_tier(
        flow, _reviewer_app(), APP_ID, "case", "F1", "R1", "Read-only"
    )
    assert outcome.verified is True
    assert _posted(flow)[0]["Role"] == "Viewer"


@pytest.mark.asyncio
async def test_grant_tier_a_tier_invalid_for_the_kind_is_refused_first() -> None:
    """`Read-only` is a real `Tier` (legal for `case`), so only this business rule --
    not the DTO's closed sets -- refuses it on `process`. The refusal names the valid
    set for that kind (`tests/test_tool_claims.py`'s `forge_grant_tier` row)."""
    flow = _TierFlow()
    app = _reviewer_app()

    with pytest.raises(ApplicationError) as exc_info:
        await grant_tier(flow, app, APP_ID, "process", "F1", "R1", "Read-only")

    assert exc_info.value.code == REFUSED
    assert "Read-only" in exc_info.value.message
    assert "valid" in exc_info.value.message
    assert flow.calls == [] and app.calls == []


@pytest.mark.asyncio
async def test_grant_tier_an_unverified_grant_is_verify_failed() -> None:
    flow = _TierFlow()
    flow.drop_grants = True
    outcome = await grant_tier(
        flow, _reviewer_app(), APP_ID, "process", "F1", "R1", "Manage"
    )
    assert outcome.verified is False
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_unverified_tier(outcome, "forge_grant_tier")
    assert exc_info.value.code == VERIFY_FAILED


@pytest.mark.asyncio
async def test_grant_tier_a_role_with_no_name_is_verify_failed() -> None:
    flow = _TierFlow()
    app = FakeAppRepository()
    app.results["get_app_role"] = [{"_id": "R1"}]

    with pytest.raises(ApplicationError) as exc_info:
        await grant_tier(flow, app, APP_ID, "process", "F1", "R1", "Manage")

    assert exc_info.value.code == VERIFY_FAILED
    assert "has no resolvable Name" in exc_info.value.message
    # Byte-for-byte against `client.py:5229` (`apply_grant_tier` was a public
    # function; review fix 5).
    assert (
        exc_info.value.message == "apply_grant_tier: role 'R1' has no resolvable Name"
    )


# =====================================================================================
# forge_set_role_preference (tests/test_p4_surface.py)
# =====================================================================================


@pytest.mark.asyncio
async def test_set_role_preference_writes_default_page_and_navigation() -> None:
    app = _RoleApp()
    outcome = await set_role_preference(app, APP_ID, "R1", "Page_123", "Navigation001")
    assert outcome.verified is True
    assert app.detail["Preference"] == {
        "DefaultPage": "Page_123",
        "DefaultNavigation": "Navigation001",
    }


@pytest.mark.asyncio
async def test_set_role_preference_default_sentinel_is_accepted() -> None:
    app = _RoleApp()
    outcome = await set_role_preference(app, APP_ID, "R1", "Default", None)
    assert outcome.verified is True
    assert app.detail["Preference"]["DefaultPage"] == "Default"


@pytest.mark.asyncio
async def test_set_role_preference_never_drops_existing_members() -> None:
    app = _RoleApp(members=[{"_id": "U0", "Kind": "User", "Name": "Old"}])
    await set_role_preference(app, APP_ID, "R1", "Page_1", None)
    assert app.detail["Members"] == [{"_id": "U0", "Kind": "User", "Name": "Old"}]


@pytest.mark.asyncio
async def test_set_role_preference_requires_at_least_one_key() -> None:
    app = _RoleApp()
    with pytest.raises(ApplicationError) as exc_info:
        await set_role_preference(app, APP_ID, "R1", None, None)
    assert exc_info.value.code == REFUSED
    assert app.calls == []
    # Byte-for-byte against `client.py:5863` (`apply_set_role_preference` was
    # a public function; review fix 5).
    assert exc_info.value.message == (
        "apply_set_role_preference: give default_page or default_navigation"
    )


@pytest.mark.asyncio
async def test_set_role_preference_an_unverified_write_is_verify_failed() -> None:
    app = _RoleApp()
    app.readback = {"_id": "R1", "Name": "Tech", "Members": [], "Preference": {}}
    outcome = await set_role_preference(app, APP_ID, "R1", "Page_1", None)
    assert outcome.verified is False
    with pytest.raises(ApplicationError) as exc_info:
        raise_if_unverified_preference(outcome, "forge_set_role_preference")
    assert exc_info.value.code == VERIFY_FAILED
