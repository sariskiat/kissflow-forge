"""Request DTO for `forge_delete_app_role`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeDeleteAppRoleRequest(BaseModel):
    """One `forge_delete_app_role` call.

    Attributes:
        role_id: The AppRole's id.
        app_id: The resolved application id. The delete route itself is
            account-level, not app-scoped, but an app must still be
            resolvable (today's `_client()` behaviour).
    """

    role_id: str
    app_id: str
