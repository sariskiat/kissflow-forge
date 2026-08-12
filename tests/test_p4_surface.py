"""Offline unit tests for the issue #55 tracer-bullet surface — new/extended forge_* tools.

Same NO-NETWORK contract as tests/test_client.py: KfClient's HTTP verb is intercepted by a Fake
subclass, so the real read-verify-write orchestration logic in kfforge.client runs for real.
"""
from __future__ import annotations

from typing import Any

from test_client import DEV, FakeClient, _bare_process_draft

from kfforge.client import Err, RoleUsersReport, apply_add_role_users


def _bare_draft(version: str = "v1") -> dict[str, Any]:
    return _bare_process_draft(version)


# ---- forge_add_role_users (#1) --------------------------------------------------------------


class RoleUsersClient(FakeClient):
    """FakeClient + the three new KfClient methods forge_add_role_users needs."""

    def __init__(self, app_roles: list[dict[str, Any]]) -> None:
        super().__init__(_bare_draft())
        self.app_roles = app_roles
        self.assignee_results: dict[str, list[dict[str, Any]]] = {}
        self.put_role_calls: list[tuple[str, dict[str, Any], str | None]] = []

    def get_assignee(self, query: str):  # type: ignore[override]
        return self.assignee_results.get(query, [])

    def put_app_role(self, role_id: str, body: dict[str, Any], app_id: str | None = None):  # type: ignore[override]
        self.put_role_calls.append((role_id, body, app_id))
        for r in self.app_roles:
            if r.get("_id") == role_id:
                for k, v in body.items():
                    if k != "Users":
                        r[k] = v
                r["Members"] = list(body.get("Users") or [])
                r["UserCount"] = len(r["Members"])
        return {"ok": True}


def test_add_role_users_by_query_grants_and_verifies() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}])
    c.assignee_results["ann"] = [{"_id": "U1", "Kind": "User", "Email": "ann@x.com", "Name": "Ann"}]
    rep = apply_add_role_users(c, "R1", user_query="ann")
    assert isinstance(rep, RoleUsersReport)
    assert rep.added == ("U1",)
    assert rep.already_present == () and rep.not_found == ()
    assert rep.user_count == 1
    assert rep.as_tool_result()["isError"] is False
    # the write key must be "Users", never "Members" (asymmetric wire keys)
    role_id, body, _app = c.put_role_calls[0]
    assert role_id == "R1"
    assert "Users" in body and "Members" not in body


def test_add_role_users_existing_member_is_already_present_no_write() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer",
                          "Members": [{"_id": "U1", "Kind": "User", "Name": "Ann"}], "UserCount": 1}])
    rep = apply_add_role_users(c, "R1", user_ids=[{"_id": "U1", "Kind": "User", "Name": "Ann"}])
    assert isinstance(rep, RoleUsersReport)
    assert rep.added == () and rep.already_present == ("U1",) and rep.not_found == ()
    assert c.put_role_calls == [], "an already-present user must never trigger a write"


def test_add_role_users_query_with_no_match_reports_not_found() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}])
    rep = apply_add_role_users(c, "R1", user_query="nobody")
    assert isinstance(rep, RoleUsersReport)
    assert rep.added == () and rep.not_found == ("nobody",)
    assert rep.as_tool_result()["isError"] is True
    assert c.put_role_calls == []


def test_add_role_users_requires_query_or_ids() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}])
    got = apply_add_role_users(c, "R1")
    assert isinstance(got, Err) and got.kind == "verify"


def test_add_role_users_existing_members_carried_over_never_dropped() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer",
                          "Members": [{"_id": "U0", "Kind": "User", "Name": "Old"}], "UserCount": 1}])
    c.assignee_results["ann"] = [{"_id": "U1", "Kind": "User", "Name": "Ann"}]
    rep = apply_add_role_users(c, "R1", user_query="ann")
    assert isinstance(rep, RoleUsersReport)
    assert rep.added == ("U1",)
    live_ids = {m["_id"] for m in c.app_roles[0]["Members"]}
    assert live_ids == {"U0", "U1"}, "granting a new user must never drop an existing member"
