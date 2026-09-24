"""Response DTO for `forge_create_list`."""

from __future__ import annotations

from pydantic import BaseModel


class ForgeCreateListResponse(BaseModel):
    """`forge_create_list`'s success result (the former `ListReport`).

    Attributes:
        list_id: The word list's id.
        name: The word list's display name.
        created: `False` when a list of that name already existed (reused).
        items: The requested item values.
        verified_items: Requested values confirmed present by read-back.
        missing_items: Requested values absent on read-back.
        snapshot_version: Always `None` -- a word list has no draft graph
            (spec G11's additive field).
    """

    list_id: str
    name: str
    created: bool
    items: list[str]
    verified_items: list[str]
    missing_items: list[str]
    snapshot_version: str | None = None
