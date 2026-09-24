"""Response DTO for `forge_add_member_roles`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeAddMemberRolesResponse(BaseModel):
    """The result of one `forge_add_member_roles` call.

    Fields mirror `app.infrastructure.kissflow.client.MemberReport.as_tool_result()`,
    minus `isError` (a non-empty `missing` is a raised `ApplicationError`
    instead, review rule 7).

    Attributes:
        target_flow_id: The flow the roles were granted onto.
        source_flow_id: Always `None` -- this tool never harvests from a
            sibling flow.
        harvested: The display names of every role granted.
        applied: The role ids granted.
        verified: The subset of `applied` confirmed present on read-back.
        missing: Always empty on a normal return (a non-empty `missing`
            raises instead).
        note: A human-readable note on what happened, or `None`.
        role_ids: The app-scoped AppRole ids granted.
        resolved: `{display_name: role_id}`, so a caller can remap a
            step -> name table onto step -> role id for
            `forge_build_workflow`'s step assignees.
        roles_seen: Every existing app-scoped role seen before matching.
        roles_granted: The count of roles actually granted.
        roles_unusable: Always empty -- this tool has no discovery step to
            report unusable candidates from.
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    target_flow_id: str
    source_flow_id: str | None
    harvested: list[str]
    applied: list[str]
    verified: list[str]
    missing: list[str]
    note: str | None
    role_ids: list[str]
    resolved: dict[str, str]
    roles_seen: int
    roles_granted: int
    roles_unusable: list[str]
    snapshot_version: str | None = None
