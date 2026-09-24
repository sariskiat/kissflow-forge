"""Request DTO for `forge_list_app_roles`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeListAppRolesRequest(BaseModel):
    """One `forge_list_app_roles` call.

    Attributes:
        app_id: The resolved application id to list AppRoles scoped to.
    """

    app_id: str
