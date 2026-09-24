"""Response DTO for `forge_member_batch`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeMemberBatchResponse(BaseModel):
    """The result of one `forge_member_batch` call.

    Fields mirror `app.infrastructure.kissflow.client.MemberReport.as_tool_result()`,
    minus `isError` (a non-empty `missing` is a raised `ApplicationError`
    instead, review rule 7).

    Attributes:
        target_flow_id: The flow members were granted onto.
        source_flow_id: The flow members were harvested from, or `None`
            when the account-level AppRole fallback was used.
        harvested: The role ids/names found on the source (or discovered at
            the account level).
        applied: The role ids/names this call attempted to grant.
        verified: The subset of `applied` confirmed present on read-back.
        missing: Always empty on a normal return (a non-empty `missing`
            raises instead).
        note: A human-readable note on what happened, or `None`.
        role_ids: The actual AppRole `_id`s granted.
        resolved: `{display_name: role_id}` for roles this call created or
            reused by name.
        roles_seen: Every candidate record seen, before any filter.
        roles_granted: The count of roles actually granted.
        roles_unusable: Candidates seen but not grantable, with the reason.
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
