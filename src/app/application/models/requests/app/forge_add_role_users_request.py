"""Request DTO for `forge_add_role_users`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ForgeAddRoleUsersRequest(BaseModel):
    """One `forge_add_role_users` call.

    Attributes:
        role_id: The AppRole's id.
        user_query: A free-text assignee search, or `None`.
        user_ids: Assignee dicts (`{_id, Kind, Email, Name}`) the caller
            already resolved, or `None`.
        groups: Group grants, as assignee-shaped dicts carrying an `_id`,
            or `None`. Refused unless `confirm_group_notification` is
            `True` (a business rule, checked in the use case: granting a
            group emails every member of it and cannot be undone).
        confirm_group_notification: Required `True` before any `groups`
            grant is written.
        force_regrant_groups: Overrides the GroupCount-based duplicate-group
            refusal.
        app_id: The resolved application id.
    """

    role_id: str
    user_query: str | None = None
    user_ids: list[dict[str, Any]] | None = None
    groups: list[dict[str, Any]] | None = None
    confirm_group_notification: bool = False
    force_regrant_groups: bool = False
    app_id: str
