"""Request DTO for `forge_create_app_role`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeCreateAppRoleRequest(BaseModel):
    """One `forge_create_app_role` call.

    Attributes:
        name: The AppRole's display name. The same name can exist on
            multiple role ids; this call always creates a new one.
        app_id: The resolved application id to scope the new role to.
    """

    name: str
    app_id: str
