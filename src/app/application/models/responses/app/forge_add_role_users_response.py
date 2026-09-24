"""Response DTO for `forge_add_role_users`."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler


class ForgeAddRoleUsersResponse(BaseModel):
    """The result of one `forge_add_role_users` call.

    Fields mirror
    `app.infrastructure.kissflow.client.RoleUsersReport.as_tool_result()`,
    minus `isError` (a non-empty `not_found` or `groups_unverified` is a
    raised `ApplicationError` instead, review rule 7).

    Attributes:
        role_id: The AppRole's id.
        added: The user ids granted and confirmed on read-back.
        already_present: Candidate user ids already on the role.
        not_found: Always empty on a normal return (a non-empty
            `not_found` raises instead).
        user_count: The role's `UserCount` after this call.
        groups_added: Group ids granted and confirmed (by list or by
            `GroupCount` movement).
        groups_already_present: Candidate group ids already on the role.
        groups_unverified: Always empty on a normal return (a non-empty
            `groups_unverified` raises instead).
        groups_refused: Group ids refused under the duplicate-group guard.
        group_count: The role's `GroupCount` after this call.
        groups_note: A note on the group verification method, or a refusal
            reason, or `None`.
        snapshot_version: Always `None` -- this write has no versioned
            draft to snapshot.
    """

    role_id: str
    added: list[str]
    already_present: list[str]
    not_found: list[str]
    user_count: int | None
    groups_added: list[str]
    groups_already_present: list[str]
    groups_unverified: list[str]
    groups_refused: list[str]
    group_count: int | None
    groups_note: str | None = None
    snapshot_version: str | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_groups_note(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Serialize with `groups_note` left out of the dict when it is falsy.

        Matches `RoleUsersReport.as_tool_result()`'s own conditional key --
        the old dict only ever carried `groups_note` when there was a note
        to give (`if self.groups_note: out["groups_note"] = ...`), never a
        bare `None`. A `@model_serializer` (not a `model_dump()` override)
        so the same shape holds for every serialization path this DTO goes
        through, not just a direct `model_dump()` call.

        Args:
            handler: The default pydantic-core serializer for this model.

        Returns:
            The serialized dict, with `groups_note` present only when it is
            a non-empty string.
        """
        data = handler(self)
        if not data.get("groups_note"):
            data.pop("groups_note", None)
        return data
