"""Response DTO for `forge_list_app_roles`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ForgeListAppRolesResponse(BaseModel):
    """The result of one `forge_list_app_roles` call. Read-only: no
    `snapshot_version`.

    Attributes:
        roles: Every matching role, as `{_id, Name}`.
        count: `len(roles)`.
        app_id: The resolved application scope.
    """

    roles: list[dict[str, Any]]
    count: int
    app_id: str
