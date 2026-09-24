"""Response DTO for `forge_set_role_preference`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeSetRolePreferenceResponse(BaseModel):
    """The result of one `forge_set_role_preference` call.

    Attributes:
        role_id: The AppRole's id.
        default_page: The default page written, or `None` when it was not
            given.
        default_navigation: The default navigation written, or `None` when
            it was not given.
        verified: Always `True` on a normal return (an unverified write
            raises `ApplicationError` instead, review rule 7).
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    role_id: str
    default_page: str | None
    default_navigation: str | None
    verified: bool
    snapshot_version: str | None = None
