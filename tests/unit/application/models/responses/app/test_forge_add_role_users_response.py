"""Spec for app.application.models.responses.app.forge_add_role_users_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_add_role_users_response import (
    ForgeAddRoleUsersResponse,
)


def _response() -> ForgeAddRoleUsersResponse:
    return ForgeAddRoleUsersResponse(
        role_id="R1",
        added=["U1"],
        already_present=[],
        not_found=[],
        user_count=1,
        groups_added=[],
        groups_already_present=[],
        groups_unverified=[],
        groups_refused=[],
        group_count=None,
    )


def test_groups_note_defaults_to_none() -> None:
    assert _response().groups_note is None


def test_snapshot_version_defaults_to_none() -> None:
    assert _response().snapshot_version is None


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    assert _response().model_dump(mode="json") == {
        "role_id": "R1",
        "added": ["U1"],
        "already_present": [],
        "not_found": [],
        "user_count": 1,
        "groups_added": [],
        "groups_already_present": [],
        "groups_unverified": [],
        "groups_refused": [],
        "group_count": None,
        "snapshot_version": None,
    }


def test_model_dump_leaves_out_groups_note_when_it_is_empty() -> None:
    """Matches the old `RoleUsersReport.as_tool_result()`: the key is absent, not
    `None` -- a caller that checks `"groups_note" in result` must see the same
    shape before and after this refactor (payload parity, common brief item 2)."""
    assert "groups_note" not in _response().model_dump(mode="json")


def test_model_dump_carries_groups_note_when_it_is_set() -> None:
    response = _response().model_copy(update={"groups_note": "verified by count"})
    dumped = response.model_dump(mode="json")
    assert "groups_note" in dumped
    assert dumped["groups_note"] == "verified by count"


def test_model_validate_round_trips() -> None:
    original = _response()
    got = ForgeAddRoleUsersResponse.model_validate(original.model_dump(mode="json"))
    assert got == original


def test_model_validate_round_trips_with_a_groups_note_set() -> None:
    original = _response().model_copy(update={"groups_note": "verified by count"})
    got = ForgeAddRoleUsersResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
