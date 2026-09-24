"""Request DTO for `forge_create_list`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeCreateListRequest(BaseModel):
    """`forge_create_list`'s arguments, the app id already resolved.

    Attributes:
        name: The word list's display name.
        values: The complete new set of legal values (REPLACE semantics).
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
    """

    name: str
    values: list[str]
    app_id: str
