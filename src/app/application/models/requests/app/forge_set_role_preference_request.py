"""Request DTO for `forge_set_role_preference`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeSetRolePreferenceRequest(BaseModel):
    """One `forge_set_role_preference` call.

    At least one of `default_page`/`default_navigation` is required -- a
    business rule (not a shape rule: both are individually optional),
    checked in the use case, same as today's `apply_set_role_preference`.

    Attributes:
        role_id: The AppRole's id.
        default_page: The default page to set (or the sentinel `"Default"`),
            or `None` to leave it.
        default_navigation: The default navigation to set (or the sentinel
            `"Default"`), or `None` to leave it.
        app_id: The resolved application id.
    """

    role_id: str
    default_page: str | None = None
    default_navigation: str | None = None
    app_id: str
