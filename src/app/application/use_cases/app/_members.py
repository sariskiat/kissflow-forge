"""Member-grant orchestration `forge_member_batch` and `forge_add_member_roles` share.

Ported from `app.infrastructure.kissflow.client`'s `discover_member_source`,
`_apply_own_app_roles`, `apply_member_batch` and `apply_member_roles` (spec
G11): the same read-verify-write shapes, now driving `FlowRepository` /
`AppRepository` with an explicit `app_id` instead of `KfClient`'s ambient
config, and raising `RepositoryError` (from the port) instead of returning
`Err`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError, RepositoryError
from app.application.interfaces.app import AppRepository
from app.application.interfaces.flow import FlowRepository
from app.domain.value_objects.kinds import FlowKind

# Proven live 2026-08-07 (carried over unchanged from `client.py`): only
# Permission=["InitiateItems"] actually lets the initiator advance their own
# item -- Permission=[] 200s the grant but still leaves them refused.
_ACCOUNT_GRANT_ROLE = "DataAdmin"
_ACCOUNT_GRANT_PERMISSION = ("InitiateItems",)

_MEMBER_KEYS = ("_id", "Name", "Kind", "Role", "Permission")


@dataclass(frozen=True)
class MemberOutcome:
    """One member-grant call's full output-invariant audit.

    Every candidate role lands in exactly one counted bucket -- `applied`
    (granted) and `roles_unusable` (seen but not grantable) partition every
    record `roles_seen` counted; `verified` and `missing` partition
    `applied` by what the read-back actually showed. Ports
    `app.infrastructure.kissflow.client.MemberReport`.
    """

    target_flow_id: str
    source_flow_id: str | None
    harvested: tuple[str, ...] = ()
    applied: tuple[str, ...] = ()
    verified: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    note: str | None = None
    role_ids: tuple[str, ...] = ()
    resolved: tuple[tuple[str, str], ...] = ()
    roles_seen: int = 0
    roles_unusable: tuple[str, ...] = field(default=())

    @property
    def roles_granted(self) -> int:
        """The count of roles this call actually applied."""
        return len(self.applied)


def member_outcome_as_dict(outcome: MemberOutcome) -> dict[str, Any]:
    """The wire-shaped dict one `MemberOutcome` embeds in a tool's response.

    Shared by `forge_create_template_app`'s own embedded `members` field and
    (field by field, not via this helper) `forge_member_batch`/
    `forge_add_member_roles`'s response DTOs -- the SAME shape
    `client.MemberReport.as_tool_result()` produced, minus `isError` (review
    fix 8: one copy of this shape, not the near-duplicate `_template.
    MemberGrantReport.as_tool_result()` this module replaces).

    Args:
        outcome: One member-grant call's outcome.

    Returns:
        The 12-key dict: `target_flow_id`, `source_flow_id`, `harvested`,
        `applied`, `verified`, `missing`, `note`, `role_ids`, `resolved`,
        `roles_seen`, `roles_granted`, `roles_unusable`.
    """
    return {
        "target_flow_id": outcome.target_flow_id,
        "source_flow_id": outcome.source_flow_id,
        "harvested": list(outcome.harvested),
        "applied": list(outcome.applied),
        "verified": list(outcome.verified),
        "missing": list(outcome.missing),
        "note": outcome.note,
        "role_ids": list(outcome.role_ids),
        "resolved": dict(outcome.resolved),
        "roles_seen": outcome.roles_seen,
        "roles_granted": outcome.roles_granted,
        "roles_unusable": list(outcome.roles_unusable),
    }


def raise_if_incomplete(outcome: MemberOutcome, tool_name: str) -> None:
    """Refuse a grant that did not fully verify on read-back (review rule 7).

    Args:
        outcome: The outcome of a member-grant call.
        tool_name: The tool name, named in the raised message.

    Raises:
        ApplicationError: `outcome.missing` is non-empty, `code=VERIFY_FAILED`.
    """
    if not outcome.missing:
        return
    raise ApplicationError(
        f"{tool_name}: granted but missing on read-back: "
        f"{', '.join(outcome.missing)} "
        f"(verified {len(outcome.verified)} of {len(outcome.applied)} granted)",
        code=VERIFY_FAILED,
    )


def _record_label(r: Any) -> str:
    """A short, human-readable label for one raw member record, for a
    `roles_unusable` entry."""
    if isinstance(r, dict):
        return str(r.get("_id") or r.get("Name") or "<blank>")
    return repr(r)


def _normalize_member(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Defensive subset to the 5 documented member/batch keys.

    A harvested record missing the load-bearing `Role` key cannot be
    meaningfully reapplied.

    Args:
        raw: One member record read off a source flow's roster.

    Returns:
        The record narrowed to `_MEMBER_KEYS`, or `None` when it carries no
        `Role`.
    """
    if not isinstance(raw, dict) or not raw.get("Role"):
        return None
    out = {k: raw[k] for k in _MEMBER_KEYS if k in raw}
    out.setdefault("Kind", "AppRole")
    return out


async def discover_member_source(
    flow: FlowRepository, app_id: str, kind: FlowKind, exclude_flow_id: str
) -> str | None:
    """Find the first other flow of `kind` in `app_id` with at least one member.

    Args:
        flow: The flow port.
        app_id: The application to search in.
        kind: The flow kind to search.
        exclude_flow_id: Never match this flow (the grant's own target).

    Returns:
        The first matching flow's id, or `None` when no such flow is found
        -- an empty app is a legitimate tenant state, not a failure. A
        candidate whose own member read fails is skipped, not fatal.
    """
    flows = await flow.list_flows(app_id, kind)
    for f in flows:
        fid = f.get("_id") if isinstance(f, dict) else None
        if not isinstance(fid, str) or fid == exclude_flow_id:
            continue
        try:
            members = await flow.get_members(app_id, kind, fid)
        except RepositoryError:
            continue
        if members:
            return fid
    return None


async def apply_own_app_roles(
    flow: FlowRepository,
    app: AppRepository,
    app_id: str,
    target_flow_id: str,
    kind: FlowKind,
) -> MemberOutcome:
    """Fall back to granting the app's own AppRoles when no sibling flow has members.

    Args:
        flow: The flow port (the grant itself lands on the target flow).
        app: The app port (the account-level AppRole discovery).
        app_id: The application both roles and the target flow belong to.
        target_flow_id: The flow to grant members onto.
        kind: The target flow's kind.

    Returns:
        The grant's `MemberOutcome`.
    """
    roles = await app.list_app_roles(app_id)
    usable = [
        r for r in roles if isinstance(r, dict) and r.get("_id") and r.get("Name")
    ]
    unusable = tuple(
        sorted(
            (
                f"{r.get('_id') or r.get('Name') or '<blank>'} "
                f"(no {'Name' if r.get('_id') else '_id'} on the account list record)"
                if isinstance(r, dict)
                else f"{r!r} (not a record — the account list returned a non-dict)"
            )
            for r in roles
            if not (isinstance(r, dict) and r.get("_id") and r.get("Name"))
        )
    )
    if not usable:
        return MemberOutcome(
            target_flow_id=target_flow_id,
            source_flow_id=None,
            roles_seen=len(roles),
            roles_unusable=unusable,
            note=(
                f"no existing flow with members found in KF_APP to harvest "
                f"from, and the account-level AppRole list has no usable "
                f"role scoped to app {app_id!r} either (saw {len(roles)} "
                f"app-scoped record(s)) — this is NOT a dead end and needs "
                f"no human: call forge_create_app_role to create one (POST "
                f"/app_role/2/{{acct}}, PROVEN live 2026-08-08 — it scopes "
                f"the role to KF_APP in a single call), then re-run "
                f"forge_member_batch. forge_add_member_roles does both in "
                f"one call."
            ),
        )

    members = [
        {
            "_id": r["_id"],
            "Name": r["Name"],
            "Kind": "AppRole",
            "Role": _ACCOUNT_GRANT_ROLE,
            "Permission": list(_ACCOUNT_GRANT_PERMISSION),
        }
        for r in usable
    ]
    role_ids = tuple(str(r["_id"]) for r in usable)
    names = tuple(str(r["Name"]) for r in usable)

    await flow.post_member_batch(app_id, kind, target_flow_id, members)

    read_back = await flow.get_members(app_id, kind, target_flow_id)
    live_ids = {str(m.get("_id")) for m in read_back if isinstance(m, dict)}
    verified = tuple(r for r in role_ids if r in live_ids)
    missing = tuple(r for r in role_ids if r not in live_ids)

    note = (
        f"saw {len(roles)} AppRole(s) scoped to app {app_id!r} at the account level, "
        f"granted {len(members)} (no sibling flow had members to harvest) — "
        f"Role={_ACCOUNT_GRANT_ROLE!r} Permission={list(_ACCOUNT_GRANT_PERMISSION)!r}: "
        f"{', '.join(names)}"
    )
    if unusable:
        note += f"; {len(unusable)} seen but NOT granted: {', '.join(unusable)}"
    else:
        note += (
            "; a role you created and do not see counted here was not on the "
            "account list when this ran — re-run forge_member_batch"
        )

    return MemberOutcome(
        target_flow_id=target_flow_id,
        source_flow_id=None,
        harvested=names,
        applied=role_ids,
        verified=verified,
        missing=missing,
        role_ids=role_ids,
        roles_seen=len(roles),
        roles_unusable=unusable,
        note=note,
    )


async def harvest_from_source(
    flow: FlowRepository,
    app_id: str,
    target_flow_id: str,
    source_flow_id: str,
    kind: FlowKind,
) -> MemberOutcome:
    """Harvest AppRole members off `source_flow_id` and grant them onto the target.

    Args:
        flow: The flow port.
        app_id: The application both flows belong to.
        target_flow_id: The flow to grant members onto.
        source_flow_id: The flow to harvest members from.
        kind: Both flows' kind.

    Returns:
        The grant's `MemberOutcome`.
    """
    raw = await flow.get_members(app_id, kind, source_flow_id)
    normalized = [n for r in raw if (n := _normalize_member(r)) is not None]
    harvested = tuple(str(n.get("Role")) for n in normalized)
    unusable = tuple(
        sorted(
            f"{_record_label(r)} (no Role on the harvested member record)"
            for r in raw
            if _normalize_member(r) is None
        )
    )
    role_ids = tuple(str(n["_id"]) for n in normalized if n.get("_id"))
    if not normalized:
        return MemberOutcome(
            target_flow_id=target_flow_id,
            source_flow_id=source_flow_id,
            roles_seen=len(raw),
            roles_unusable=unusable,
            note=(
                f"source flow {source_flow_id!r} has no AppRole members to harvest "
                f"(saw {len(raw)} member record(s), none usable)"
                + (f": {', '.join(unusable)}" if unusable else "")
                + " — forge_create_app_role then forge_member_batch, or "
                "forge_add_member_roles, grants one without a source flow at all"
            ),
        )

    await flow.post_member_batch(app_id, kind, target_flow_id, normalized)

    read_back = await flow.get_members(app_id, kind, target_flow_id)
    live_roles = {str(m.get("Role")) for m in read_back if isinstance(m, dict)}
    verified = tuple(r for r in harvested if r in live_roles)
    missing = tuple(r for r in harvested if r not in live_roles)

    note = None
    if unusable:
        note = (
            f"saw {len(raw)} member record(s) on {source_flow_id!r}, granted "
            f"{len(harvested)}; {len(unusable)} seen but NOT granted: "
            f"{', '.join(unusable)}"
        )

    return MemberOutcome(
        target_flow_id=target_flow_id,
        source_flow_id=source_flow_id,
        harvested=harvested,
        applied=harvested,
        verified=verified,
        missing=missing,
        role_ids=role_ids,
        roles_seen=len(raw),
        roles_unusable=unusable,
        note=note,
    )


async def create_then_grant_roles(
    app: AppRepository,
    flow: FlowRepository,
    app_id: str,
    target_flow_id: str,
    roles: dict[str, str],
    kind: FlowKind,
) -> MemberOutcome:
    """Grant AppRoles onto `target_flow_id`, creating each by name first if needed.

    `roles` is keyed by an arbitrary caller-side id; the real match key is
    the display NAME, scoped to `app_id` (idempotent: an existing
    same-name role scoped to this app is reused, never duplicated).

    Args:
        app: The app port (role lookup and creation).
        flow: The flow port (the grant itself).
        app_id: The application every role is scoped to.
        target_flow_id: The flow to grant the roles onto.
        roles: `{caller_id: display_name}`.
        kind: The target flow's kind.

    Returns:
        The grant's `MemberOutcome`, with `resolved` carrying
        `(display_name, role_id)` pairs, each role scoped to `app_id`.
    """
    existing = await app.list_app_roles(app_id)
    # Snapshot the target flow's current members before granting -- the old
    # `apply_member_roles` never did, but `post_member_batch` below is this
    # function's only write on the flow port, and CLAUDE.md's write order
    # (snapshot before any write) applies here the same as everywhere else.
    await flow.get_members(app_id, kind, target_flow_id)

    by_name: dict[str, str] = {}
    for r in existing:
        if not isinstance(r, dict):
            continue
        name, rid = r.get("Name"), r.get("_id")
        if isinstance(name, str) and isinstance(rid, str):
            by_name[name] = rid

    resolved_by_id: dict[str, str] = {}  # role_id -> display name
    created: list[str] = []
    for _requested_id, name in roles.items():
        if name in by_name:
            resolved_by_id[by_name[name]] = name
            continue
        new_id = await app.create_app_role(name, app_id)
        resolved_by_id[new_id] = name
        created.append(f"{name}={new_id}")

    members = [
        {
            "_id": rid,
            "Name": name,
            "Kind": "AppRole",
            "Role": _ACCOUNT_GRANT_ROLE,
            "Permission": list(_ACCOUNT_GRANT_PERMISSION),
        }
        for rid, name in resolved_by_id.items()
    ]
    role_ids = tuple(resolved_by_id)
    names = tuple(resolved_by_id.values())

    await flow.post_member_batch(app_id, kind, target_flow_id, members)

    read_back = await app.list_app_roles(app_id)
    live_ids = {str(r.get("_id")) for r in read_back if isinstance(r, dict)}
    verified = tuple(r for r in role_ids if r in live_ids)
    missing = tuple(r for r in role_ids if r not in live_ids)

    note = f"granted {len(members)} KF_APP-scoped AppRole(s): {', '.join(names)}"
    if created:
        note += f"; created {len(created)} ({', '.join(created)})"

    return MemberOutcome(
        target_flow_id=target_flow_id,
        source_flow_id=None,
        harvested=names,
        applied=role_ids,
        verified=verified,
        missing=missing,
        role_ids=role_ids,
        resolved=tuple((name, rid) for rid, name in resolved_by_id.items()),
        # `roles_seen` counts what DISCOVERY received before any filter
        # (`MemberOutcome`'s own docstring); this path never discovers
        # candidates, it grants exactly the caller-named `roles`, so it
        # stays at the field's own default `0` -- old `apply_member_roles`
        # (`client.py:4366-4376`) never passed it either, and its own
        # `roles_seen` field comment (`client.py:4008-4013`) names this
        # exact path as one of the two that leave it at 0.
        note=note,
    )
