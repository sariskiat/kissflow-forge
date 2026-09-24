"""AppRole-write orchestration `forge_add_role_users`, `forge_grant_tier` and
`forge_set_role_preference` share.

Ported from `app.infrastructure.kissflow.client`'s `_role_write_body`,
`_existing_group_list`, the `_validate_role_*` / `_partition_*` / `_gate_*` /
`_verify_*` family, `apply_add_role_users` and `apply_grant_tier` (spec G11):
the same read-verify-write shapes, now driving `AppRepository` /
`FlowRepository` with an explicit `app_id`, and raising `ApplicationError`
instead of returning `Err`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.application.exceptions import (
    REFUSED,
    VERIFY_FAILED,
    ApplicationError,
)
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.domain.value_objects.kinds import Tier, TierKind

# =====================================================================================
# forge_add_role_users
# =====================================================================================


@dataclass(frozen=True)
class RoleUsersOutcome:
    """Output-invariant audit for `forge_add_role_users`: every candidate user
    lands in `added`, `already_present`, or `not_found`; every candidate group
    lands in `groups_added`, `groups_already_present`, `groups_unverified` or
    `groups_refused`. Ports `app.infrastructure.kissflow.client.RoleUsersReport`.
    """

    role_id: str
    added: tuple[str, ...] = ()
    already_present: tuple[str, ...] = ()
    not_found: tuple[str, ...] = ()
    user_count: int | None = None
    groups_added: tuple[str, ...] = ()
    groups_already_present: tuple[str, ...] = ()
    groups_unverified: tuple[str, ...] = ()
    groups_refused: tuple[str, ...] = ()
    group_count: int | None = None
    groups_note: str | None = None


def raise_if_incomplete(outcome: RoleUsersOutcome, tool_name: str) -> None:
    """Refuse a grant that left a user unresolved or a group unverified (review rule 7).

    A group grant EMAILS EVERY MEMBER of the group the moment it lands
    (CLAUDE.md > Members first) -- `outcome.added`/`outcome.groups_added`
    (what already landed) and `outcome.groups_note` (the old payload's own
    `groups_note`, `client.py:4594-4610`) are folded into the raised
    message so a caller reading this as "nothing happened" never retries a
    grant that already went out and re-notifies the group.

    Args:
        outcome: The outcome of an add-role-users call.
        tool_name: The tool name, named in the raised message.

    Raises:
        ApplicationError: `outcome.not_found` or `outcome.groups_unverified` is
            non-empty, `code=VERIFY_FAILED`.
    """
    problems: list[str] = []
    if outcome.not_found:
        problems.append(f"not_found: {', '.join(outcome.not_found)}")
    if outcome.groups_unverified:
        problems.append(f"groups_unverified: {', '.join(outcome.groups_unverified)}")
    if not problems:
        return
    landed: list[str] = []
    if outcome.added:
        landed.append(f"added={list(outcome.added)}")
    if outcome.groups_added:
        landed.append(f"groups_added={list(outcome.groups_added)}")
    landed_suffix = f" ({'; '.join(landed)})" if landed else ""
    note_suffix = f" — {outcome.groups_note}" if outcome.groups_note else ""
    raise ApplicationError(
        f"{tool_name}: " + "; ".join(problems) + landed_suffix + note_suffix,
        code=VERIFY_FAILED,
    )


def _role_write_body(detail: dict[str, Any]) -> dict[str, Any]:
    """Non-underscore keys off a `get_app_role` detail, ready to write back.

    The write endpoint reuses the same record shape the read endpoint
    returns, but with one asymmetric key: it reads back under `Members` but
    must be written under `Users` -- a body that carries `Members` instead
    200s and silently no-ops. `Members` is dropped from the body here and
    its entries carried over verbatim under `Users`.

    Args:
        detail: One `get_app_role` read.

    Returns:
        The write-ready body.
    """
    body = {k: v for k, v in detail.items() if not k.startswith("_")}
    members = body.pop("Members", None) or []
    body["Users"] = list(members)
    return body


def _existing_group_list(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Whatever group list an AppRole detail exposes, or `[]` when it exposes none.

    `[]` means "no list was exposed", not "there are no groups" -- callers
    also report `group_count` and a note rather than reading absence as
    emptiness.

    Args:
        detail: One `get_app_role` read.

    Returns:
        Every `Groups`/`GroupMembers` entry carrying an `_id`.
    """
    for key in ("Groups", "GroupMembers"):
        raw = detail.get(key)
        if isinstance(raw, list):
            return [g for g in raw if isinstance(g, dict) and g.get("_id")]
    return []


def _member_ids(members: Iterable[Any]) -> set[str]:
    return {str(m.get("_id")) for m in members if isinstance(m, dict)}


def _match_assignee_nodes(found: list[Any]) -> list[dict[str, Any]]:
    return [c for c in found if isinstance(c, dict) and c.get("_id")]


async def _resolve_role_user_query(
    app: AppRepository, user_query: str | None
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    if user_query is None:
        return [], ()
    found = await app.get_assignee(user_query)
    matched = _match_assignee_nodes(found)
    if matched:
        return matched, ()
    return [], (user_query,)


def _partition_user_candidates(
    candidates: list[dict[str, Any]],
    existing_members: list[dict[str, Any]],
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    existing_ids = _member_ids(existing_members)
    already: list[str] = []
    new_ones: list[dict[str, Any]] = []
    for c in candidates:
        cid = str(c.get("_id"))
        if cid in existing_ids:
            already.append(cid)
        else:
            new_ones.append(c)
    return tuple(already), new_ones


def _partition_candidate_groups(
    groups: list[dict[str, Any]] | None,
    existing_groups: list[dict[str, Any]],
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    existing_ids = _member_ids(existing_groups)
    already: list[str] = []
    new_groups: list[dict[str, Any]] = []
    for g in groups or ():
        gid = str(g.get("_id"))
        if gid in existing_ids:
            already.append(gid)
        else:
            new_groups.append(g)
    return tuple(already), new_groups


def _is_group_regrant_blocked(detail: dict[str, Any], force: bool) -> bool:
    if force:
        return False
    gc = detail.get("GroupCount")
    return isinstance(gc, int) and gc > 0


def _gate_group_regrant(
    new_groups: list[dict[str, Any]],
    detail: dict[str, Any],
    force: bool,
) -> tuple[list[dict[str, Any]], tuple[str, ...], str | None]:
    if not new_groups or not _is_group_regrant_blocked(detail, force):
        return new_groups, (), None
    refused = tuple(str(g["_id"]) for g in new_groups)
    note = (
        f"refused to re-issue the Groups write for {', '.join(refused)}: "
        f"GroupCount is already {detail['GroupCount']} on this role and no group "
        f"LIST exists to prove these are different groups, so a repeat grant is "
        f"assumed to be a duplicate and skipped to avoid re-broadcasting the "
        f"notification — pass force_regrant_groups=True to override"
    )
    return [], refused, note


def _group_display_name(g: Any) -> str:
    if isinstance(g, dict):
        return str(g.get("Name") or g.get("_id") or "")
    return ""


def _format_group_names(groups: list[dict[str, Any]]) -> str:
    names = [name for g in groups if (name := _group_display_name(g))]
    return ", ".join(names) or "<unnamed>"


def _validate_role_group_notification(
    groups: list[dict[str, Any]] | None,
    confirm: bool,
) -> None:
    if not groups or confirm:
        return
    named = _format_group_names(groups)
    raise ApplicationError(
        f"refusing to grant group(s) [{named}] without confirm_group_notification=True "
        f"— Kissflow FANS OUT A NOTIFICATION TO EVERY MEMBER the moment the grant "
        f"lands, and on a whole-tenant group that is every person in the account "
        f"(CLAUDE.md Members first: this happened, 2026-08-20). AND IT CANNOT BE "
        f"UNDONE: membership writes are ADD-ONLY — nine removal shapes were probed "
        f"live and none of them remove a group, so the only recovery is to build a "
        f"REPLACEMENT role, re-point the workflow assignees at it, rebuild the "
        f"visibility matrix that re-point wipes, and delete the polluted role. To "
        f"TEST this tool, grant ONE named developer instead: user_query='<your "
        f"name>'. Pass confirm_group_notification=True only after a human has "
        f"confirmed the actual recipient list, the same as sending mail.",
        code=REFUSED,
    )


def _is_valid_group_dict(g: Any) -> bool:
    return isinstance(g, dict) and bool(g.get("_id"))


def _validate_role_groups_shape(groups: list[dict[str, Any]] | None) -> None:
    for g in groups or ():
        if not _is_valid_group_dict(g):
            raise ApplicationError(
                f"apply_add_role_users: each group must be an assignee-shaped "
                f"dict with an _id, e.g. {{'_id': 'everyone', 'Kind': 'Group', "
                f"'Name': 'Everyone'}} — got {g!r}",
                code=REFUSED,
            )


def _validate_role_update_inputs(
    user_query: str | None,
    user_ids: list[dict[str, Any]] | None,
    groups: list[dict[str, Any]] | None,
    confirm_group_notification: bool,
) -> None:
    if not any((user_query is not None, bool(user_ids), bool(groups))):
        raise ApplicationError(
            "apply_add_role_users: give user_query, user_ids or groups", code=REFUSED
        )
    _validate_role_group_notification(groups, confirm_group_notification)
    _validate_role_groups_shape(groups)


def _verify_users_readback(
    new_ones: list[dict[str, Any]],
    read_back: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    live_ids = _member_ids(read_back.get("Members") or ())
    added: list[str] = []
    unverified: list[str] = []
    for c in new_ones:
        cid = str(c.get("_id"))
        if cid in live_ids:
            added.append(cid)
        else:
            unverified.append(cid)
    return tuple(added), tuple(unverified)


def _verify_groups_by_list(
    new_groups: list[dict[str, Any]],
    live_groups: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    added: list[str] = []
    unver: list[str] = []
    for g in new_groups:
        gid = str(g.get("_id"))
        if gid in live_groups:
            added.append(gid)
        else:
            unver.append(gid)
    return tuple(added), tuple(unver)


def _is_group_count_increased(count_before: Any, count_after: Any) -> bool:
    return (
        isinstance(count_before, int)
        and isinstance(count_after, int)
        and count_after > count_before
    )


def _group_ids(groups: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(g["_id"]) for g in groups)


def _eval_groups_by_count(
    new_groups: list[dict[str, Any]],
    count_before: Any,
    count_after: Any,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    if not new_groups:
        return (), (), None
    gids = _group_ids(new_groups)
    if _is_group_count_increased(count_before, count_after):
        return (
            gids,
            (),
            (
                f"verified by GroupCount {count_before} -> {count_after} only — this "
                f"tenant exposes no group LIST on the role detail, so membership is "
                f"proven by count movement, not by naming the group back"
            ),
        )
    return (
        (),
        gids,
        (
            f"WRITTEN BUT UNPROVEN: no group list on the role detail and GroupCount "
            f"did not move ({count_before!r} -> {count_after!r}). Confirm in the "
            f"builder UI before relying on it — a 200 from the write proves nothing "
            f"(THE RULE)"
        ),
    )


def _eval_groups_readback_note(
    new_groups: list[dict[str, Any]],
    count_before: Any,
    count_after: Any,
    live_groups: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    if live_groups:
        return *_verify_groups_by_list(new_groups, live_groups), None
    return _eval_groups_by_count(new_groups, count_before, count_after)


def _should_note_unenumerated_groups(
    new_groups: list[Any],
    existing_groups: list[Any],
    note: str | None,
) -> bool:
    return bool(new_groups) and not existing_groups and note is None


def _verify_groups_readback(
    new_groups: list[dict[str, Any]],
    existing_groups: list[dict[str, Any]],
    count_before: Any,
    read_back: dict[str, Any],
    blocked_note: str | None,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    live_groups = _member_ids(_existing_group_list(read_back))
    count_after = read_back.get("GroupCount")
    g_added, g_unver, note = _eval_groups_readback_note(
        new_groups, count_before, count_after, live_groups
    )
    if _should_note_unenumerated_groups(new_groups, existing_groups, note):
        note = (
            "existing groups could not be enumerated (no group list on the "
            "role detail), so this write cannot promise it preserved any "
            "that were already there"
        )
    return g_added, g_unver, note or blocked_note


async def add_role_users(
    app: AppRepository,
    app_id: str,
    role_id: str,
    user_query: str | None,
    user_ids: list[dict[str, Any]] | None,
    groups: list[dict[str, Any]] | None,
    confirm_group_notification: bool,
    force_regrant_groups: bool,
) -> RoleUsersOutcome:
    """Grant one or more users (and/or groups) onto an AppRole.

    Read the role detail -> resolve candidate assignees (`user_query` via
    `AppRepository.get_assignee`, and/or `user_ids` passed through verbatim)
    -> merge onto the role's existing `Members` (never dropping current
    membership) -> one `put_app_role` write under the write key `Users` ->
    read back and verify by `Members`/`UserCount`.

    A `groups` grant is refused unless `confirm_group_notification` is
    `True` -- granting a group notifies every member of it, and the
    notification cannot be recalled (see `_validate_role_group_notification`
    for the full guard).

    Args:
        app: The app port.
        app_id: The application to scope the write to.
        role_id: The AppRole's id.
        user_query: A free-text assignee search, or `None`.
        user_ids: Assignee dicts already resolved by the caller, or `None`.
        groups: Group grants, or `None`.
        confirm_group_notification: Required `True` before any `groups`
            grant is written.
        force_regrant_groups: Overrides the GroupCount-based duplicate-group
            refusal.

    Returns:
        The grant's `RoleUsersOutcome`.

    Raises:
        ApplicationError: No candidate was given at all, a `groups` grant
            was not confirmed, or a group dict is malformed -- all
            `code=REFUSED`.
    """
    _validate_role_update_inputs(
        user_query, user_ids, groups, confirm_group_notification
    )

    detail = await app.get_app_role(role_id)
    query_candidates, not_found = await _resolve_role_user_query(app, user_query)

    existing_members: list[dict[str, Any]] = list(detail.get("Members") or ())
    candidates = list(user_ids or ()) + query_candidates
    already, new_ones = _partition_user_candidates(candidates, existing_members)

    existing_groups = _existing_group_list(detail)
    groups_already, candidate_groups = _partition_candidate_groups(
        groups, existing_groups
    )
    new_groups, groups_refused, blocked_note = _gate_group_regrant(
        candidate_groups, detail, force_regrant_groups
    )

    if not new_ones and not new_groups:
        return RoleUsersOutcome(
            role_id=role_id,
            already_present=already,
            not_found=not_found,
            user_count=detail.get("UserCount"),
            groups_already_present=groups_already,
            groups_refused=groups_refused,
            group_count=detail.get("GroupCount"),
            groups_note=blocked_note,
        )

    count_before = detail.get("GroupCount")
    body = _role_write_body(detail)
    body["Users"] = existing_members + new_ones
    if new_groups or existing_groups:
        body["Groups"] = existing_groups + new_groups

    await app.put_app_role(app_id, role_id, body)

    read_back = await app.get_app_role(role_id)

    added, unverified_users = _verify_users_readback(new_ones, read_back)
    g_added, g_unver, groups_note = _verify_groups_readback(
        new_groups, existing_groups, count_before, read_back, blocked_note
    )

    return RoleUsersOutcome(
        role_id=role_id,
        added=added,
        already_present=already,
        not_found=not_found + unverified_users,
        user_count=read_back.get("UserCount"),
        groups_added=g_added,
        groups_already_present=groups_already,
        groups_unverified=g_unver,
        groups_refused=groups_refused,
        group_count=read_back.get("GroupCount"),
        groups_note=groups_note,
    )


# =====================================================================================
# forge_grant_tier
# =====================================================================================

# Tier -> (Role, Permission[]) wire map, flow-type-dependent. `None` means "No
# access" -- a real removal route (`delete_member`), not a member/batch grant
# with an empty Permission (which is itself a genuine tier, "Initiate" on a
# process).
_TIER_MAP: dict[str, dict[str, tuple[str, tuple[str, ...]] | None]] = {
    "process": {
        "No access": None,
        "Initiate": ("Member", ()),
        "Manage": ("DataAdmin", ("InitiateItems",)),
    },
    "case": {
        "No access": None,
        "Read-only": ("Viewer", ()),
        "Initiate": ("Initiator", ()),
        "Edit": ("Member", ()),
        "Manage": ("Admin", ()),
    },
}


@dataclass(frozen=True)
class TierOutcome:
    """The result of one `forge_grant_tier` call. Ports
    `app.infrastructure.kissflow.client.TierReport`."""

    flow_id: str
    kind: str
    role_id: str
    tier: str
    verified: bool


def raise_if_unverified_tier(outcome: TierOutcome, tool_name: str) -> None:
    """Refuse a tier grant that did not verify on read-back (review rule 7).

    Args:
        outcome: The outcome of a grant-tier call.
        tool_name: The tool name, named in the raised message.

    Raises:
        ApplicationError: `outcome.verified` is `False`, `code=VERIFY_FAILED`.
    """
    if outcome.verified:
        return
    raise ApplicationError(
        f"{tool_name}: grant of tier {outcome.tier!r} to role {outcome.role_id!r} "
        f"on flow {outcome.flow_id!r} did not verify on read-back",
        code=VERIFY_FAILED,
    )


async def grant_tier(
    flow: FlowRepository,
    app: AppRepository,
    app_id: str,
    kind: TierKind,
    flow_id: str,
    role_id: str,
    tier: Tier,
) -> TierOutcome:
    """Grant an AppRole a named permission tier on a flow.

    `kind` is already a closed `TierKind` (the request DTO refuses any other
    value before this runs); the `(kind, tier)` COMBINATION is the
    remaining business rule this function still refuses loudly, since a
    `Tier` that is legal for one kind is not always legal for the other.

    Args:
        flow: The flow port (the grant/removal itself).
        app: The app port (the role's own `Name`, needed to grant).
        app_id: The application the flow belongs to.
        kind: The flow kind.
        flow_id: The flow's id.
        role_id: The AppRole's id.
        tier: The tier to grant.

    Returns:
        The grant's `TierOutcome`.

    Raises:
        ApplicationError: `tier` is not valid for `kind`, `code=REFUSED`.
    """
    by_tier = _TIER_MAP[kind]
    if tier not in by_tier:
        raise ApplicationError(
            f"forge_grant_tier: unknown tier {tier!r} for kind {kind!r} — "
            f"valid: {sorted(by_tier)}",
            code=REFUSED,
        )
    mapped = by_tier[tier]

    # Snapshot before any write, on the port this call is about to write.
    await flow.get_members(app_id, kind, flow_id)

    if mapped is None:
        await flow.delete_member(app_id, kind, flow_id, role_id)
        read_back = await flow.get_members(app_id, kind, flow_id)
        verified = not any(
            isinstance(m, dict) and str(m.get("_id")) == role_id for m in read_back
        )
        return TierOutcome(
            flow_id=flow_id, kind=kind, role_id=role_id, tier=tier, verified=verified
        )

    role_name, permission = mapped
    role_detail = await app.get_app_role(role_id)
    name = role_detail.get("Name")
    if not isinstance(name, str):
        raise ApplicationError(
            f"apply_grant_tier: role {role_id!r} has no resolvable Name",
            code=VERIFY_FAILED,
        )

    member = {
        "_id": role_id,
        "Name": name,
        "Kind": "AppRole",
        "Role": role_name,
        "Permission": list(permission),
    }
    await flow.post_member_batch(app_id, kind, flow_id, [member])

    read_back = await flow.get_members(app_id, kind, flow_id)
    verified = any(
        isinstance(m, dict)
        and str(m.get("_id")) == role_id
        and m.get("Role") == role_name
        and sorted(m.get("Permission") or []) == sorted(permission)
        for m in read_back
    )
    return TierOutcome(
        flow_id=flow_id, kind=kind, role_id=role_id, tier=tier, verified=verified
    )


# =====================================================================================
# forge_set_role_preference
# =====================================================================================


@dataclass(frozen=True)
class RolePreferenceOutcome:
    """The result of one `forge_set_role_preference` call. Ports
    `app.infrastructure.kissflow.client.RolePreferenceReport`."""

    role_id: str
    default_page: str | None
    default_navigation: str | None
    verified: bool


def raise_if_unverified_preference(
    outcome: RolePreferenceOutcome, tool_name: str
) -> None:
    """Refuse a preference write that did not verify on read-back (review rule 7).

    Args:
        outcome: The outcome of a set-role-preference call.
        tool_name: The tool name, named in the raised message.

    Raises:
        ApplicationError: `outcome.verified` is `False`, `code=VERIFY_FAILED`.
    """
    if outcome.verified:
        return
    raise ApplicationError(
        f"{tool_name}: preference write for role {outcome.role_id!r} did not "
        f"verify on read-back (default_page={outcome.default_page!r}, "
        f"default_navigation={outcome.default_navigation!r})",
        code=VERIFY_FAILED,
    )


async def set_role_preference(
    app: AppRepository,
    app_id: str,
    role_id: str,
    default_page: str | None,
    default_navigation: str | None,
) -> RolePreferenceOutcome:
    """Set an AppRole's own default page/navigation.

    Reuses the same `put_app_role` write route `add_role_users` uses, and
    the same `_role_write_body` helper, so setting only a preference never
    accidentally drops existing membership. At least one of `default_page`/
    `default_navigation` must be given.

    Args:
        app: The app port.
        app_id: The application to scope the write to.
        role_id: The AppRole's id.
        default_page: The default page to set, or `None` to leave it.
        default_navigation: The default navigation to set, or `None` to
            leave it.

    Returns:
        The write's `RolePreferenceOutcome`.

    Raises:
        ApplicationError: Neither `default_page` nor `default_navigation`
            was given, `code=REFUSED`.
    """
    if default_page is None and default_navigation is None:
        raise ApplicationError(
            "apply_set_role_preference: give default_page or default_navigation",
            code=REFUSED,
        )

    detail = await app.get_app_role(role_id)

    body = _role_write_body(detail)
    pref = dict(body.get("Preference") or {})
    if default_page is not None:
        pref["DefaultPage"] = default_page
    if default_navigation is not None:
        pref["DefaultNavigation"] = default_navigation
    body["Preference"] = pref

    await app.put_app_role(app_id, role_id, body)

    read_back = await app.get_app_role(role_id)
    live_pref = read_back.get("Preference") or {}
    verified = all(
        live_pref.get(k) == v
        for k, v in (
            ("DefaultPage", default_page),
            ("DefaultNavigation", default_navigation),
        )
        if v is not None
    )
    return RolePreferenceOutcome(
        role_id=role_id,
        default_page=default_page,
        default_navigation=default_navigation,
        verified=verified,
    )
