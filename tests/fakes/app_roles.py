"""App-role fakes shared by `forge_add_role_users`, `forge_grant_tier` and
`forge_set_role_preference` tests (spec G7/G14: no test imports a sibling test
module -- these used to live in `tests/unit/application/use_cases/app/test__roles.py`
and be imported from there by name).
"""

from __future__ import annotations

from typing import Any

from tests.fakes.app import FakeAppRepository
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import RepositoryError

EVERYONE = {"_id": "everyone", "Kind": "Group", "Name": "Everyone"}


class _RoleApp(FakeAppRepository):
    """`tests/test_client.py`'s `_FakeRoleClient` as an `AppRepository` fake.

    An AppRole whose detail exposes `Members` and a nullable `GroupCount` but no group
    LIST -- the shape the live tenant returns. A write replaces `Members` with the
    body's `Users` (unless `users_land` is off) and, when `GroupCount` is an int, moves
    it to the number of `Groups` written. `readback`, when set, is what every read
    after the first returns instead (the old tests' `fake_get_role` with `calls > 1`).
    `raise_on` makes the Nth call of a method raise `RepositoryError`, the port's own
    translation of an old `Err("http")`.
    """

    def __init__(
        self,
        *,
        group_count: int | None = 0,
        members: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.detail: dict[str, Any] = {
            "_id": "R1",
            "Name": "Tech",
            "Members": list(members or []),
            "UserCount": len(members or []),
            "GroupCount": group_count,
        }
        self.detail.update(extra or {})
        self.body: dict[str, Any] | None = None
        self.assignees: dict[str, list[dict[str, Any]]] = {}
        self.users_land = True
        self.readback: dict[str, Any] | None = None
        self.raise_on: dict[str, int] = {}
        self._seen: dict[str, int] = {}

    def _maybe_fail(self, name: str) -> None:
        self._seen[name] = self._seen.get(name, 0) + 1
        if self.raise_on.get(name) == self._seen[name]:
            raise RepositoryError(f"{name} failed")

    async def get_app_role(self, role_id: str) -> dict[str, Any]:
        self._record("get_app_role", (role_id,), {})
        self._maybe_fail("get_app_role")
        if self.readback is not None and self._seen["get_app_role"] > 1:
            return dict(self.readback)
        return dict(self.detail)

    async def get_assignee(self, query: str) -> list[dict[str, Any]]:
        self._record("get_assignee", (query,), {})
        self._maybe_fail("get_assignee")
        return list(self.assignees.get(query, []))

    async def put_app_role(
        self, app_id: str, role_id: str, body: dict[str, Any]
    ) -> Any:
        self._record("put_app_role", (app_id, role_id, body), {})
        self._maybe_fail("put_app_role")
        self.body = body
        for key, value in body.items():
            if key not in ("Users", "Groups"):
                self.detail[key] = value
        if self.users_land:
            users = list(body.get("Users") or [])
            self.detail["Members"] = users
            self.detail["UserCount"] = len(users)
        count = self.detail.get("GroupCount")
        if isinstance(count, int) and body.get("Groups"):
            self.detail["GroupCount"] = len(body["Groups"])
        return {"ok": True}


class _TierFlow(FakeFlowRepository):
    """A flow whose member roster reflects every grant and removal."""

    def __init__(self) -> None:
        super().__init__()
        self.members: list[dict[str, Any]] = []
        self.drop_grants = False

    async def get_members(
        self, app_id: str, kind: Any, flow_id: str
    ) -> list[dict[str, Any]]:
        self._record("get_members", (app_id, kind, flow_id), {})
        return list(self.members)

    async def post_member_batch(
        self, app_id: str, kind: Any, flow_id: str, members: list[dict[str, Any]]
    ) -> Any:
        self._record("post_member_batch", (app_id, kind, flow_id, members), {})
        if not self.drop_grants:
            self.members = list(members)
        return {"ok": True}

    async def delete_member(
        self, app_id: str, kind: Any, flow_id: str, role_id: str
    ) -> Any:
        self._record("delete_member", (app_id, kind, flow_id, role_id), {})
        self.members = [m for m in self.members if m.get("_id") != role_id]
        return {"status": "success"}


def _reviewer_app() -> FakeAppRepository:
    app = FakeAppRepository()
    app.results["get_app_role"] = [{"_id": "R1", "Name": "Reviewer"}]
    return app
