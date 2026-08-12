"""Offline unit tests for the issue #55 tracer-bullet surface — new/extended forge_* tools.

Same NO-NETWORK contract as tests/test_client.py: KfClient's HTTP verb is intercepted by a Fake
subclass, so the real read-verify-write orchestration logic in kfforge.client runs for real.
"""
from __future__ import annotations

from typing import Any

from test_client import DEV, FakeClient, _bare_process_draft

from kfforge.client import (
    Err,
    FlowCreateReport,
    RolePreferenceReport,
    RoleUsersReport,
    TierReport,
    apply_add_role_users,
    apply_dataset_records,
    apply_grant_tier,
    apply_set_role_preference,
    create_flow_any,
    publish_application_verified,
)


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


# ---- forge_grant_tier (#2) --------------------------------------------------------------------


class TierClient(FakeClient):
    def __init__(self, app_roles: list[dict[str, Any]]) -> None:
        super().__init__(_bare_draft())
        self.app_roles = app_roles
        self.deleted_members: list[tuple[str, str, str]] = []

    def delete_member(self, kind, flow_id, role_id):  # type: ignore[override]
        self.deleted_members.append((kind, flow_id, role_id))
        self.members[(kind, flow_id)] = [
            m for m in self.members.get((kind, flow_id), []) if m.get("_id") != role_id
        ]
        return {"status": "success"}


def test_grant_tier_process_manage_grants_dataadmin_initiateitems() -> None:
    c = TierClient([{"_id": "R1", "Name": "Reviewer"}])
    rep = apply_grant_tier(c, "process", "F1", "R1", "Manage")
    assert isinstance(rep, TierReport)
    assert rep.verified is True and rep.as_tool_result()["isError"] is False
    kind, flow_id, members = c.member_batches[0]
    assert members[0]["Role"] == "DataAdmin" and members[0]["Permission"] == ["InitiateItems"]


def test_grant_tier_process_initiate_is_member_with_empty_permission() -> None:
    c = TierClient([{"_id": "R1", "Name": "Reviewer"}])
    rep = apply_grant_tier(c, "process", "F1", "R1", "Initiate")
    assert isinstance(rep, TierReport) and rep.verified is True
    members = c.member_batches[0][2]
    assert members[0]["Role"] == "Member" and members[0]["Permission"] == []


def test_grant_tier_no_access_deletes_the_member_route() -> None:
    c = TierClient([{"_id": "R1", "Name": "Reviewer"}])
    c.members[("process", "F1")] = [{"_id": "R1", "Role": "DataAdmin", "Permission": ["InitiateItems"]}]
    rep = apply_grant_tier(c, "process", "F1", "R1", "No access")
    assert isinstance(rep, TierReport) and rep.verified is True
    assert c.deleted_members == [("process", "F1", "R1")]
    assert c.member_batches == [], "No access must never go through member/batch"


def test_grant_tier_case_adds_read_only_and_edit_tiers() -> None:
    c = TierClient([{"_id": "R1", "Name": "Reviewer"}])
    rep = apply_grant_tier(c, "case", "F1", "R1", "Read-only")
    assert isinstance(rep, TierReport) and rep.verified is True
    assert c.member_batches[0][2][0]["Role"] == "Viewer"


def test_grant_tier_unknown_kind_rejected_before_any_write() -> None:
    c = TierClient([{"_id": "R1", "Name": "Reviewer"}])
    got = apply_grant_tier(c, "form", "F1", "R1", "Manage")  # type: ignore[arg-type]
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.member_batches == [] and c.deleted_members == []


def test_grant_tier_unknown_tier_rejected_before_any_write() -> None:
    c = TierClient([{"_id": "R1", "Name": "Reviewer"}])
    got = apply_grant_tier(c, "process", "F1", "R1", "Superuser")
    assert isinstance(got, Err) and got.kind == "verify"
    assert "Superuser" in got.message
    assert c.member_batches == []


# ---- forge_create_flow (#3) -------------------------------------------------------------------


class CreateFlowClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(_bare_draft())
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter}"

    def create_flow(self, kind, name):  # type: ignore[override]
        return self._next_id(kind)

    def create_list(self, name):  # type: ignore[override]
        return {"_id": self._next_id("List"), "Type": "List", "Status": "Live", "Name": name}

    def create_dataset(self, name):  # type: ignore[override]
        return {"_id": self._next_id("Dataset"), "Type": "Dataset", "Status": "Live", "Name": name}

    def create_case(self, name, item_type, prefix):  # type: ignore[override]
        return {"_id": self._next_id("Case"), "Type": "Case", "Status": "Live", "Name": name,
                "ItemType": item_type, "Prefix": prefix}


def test_create_flow_process_starts_draft() -> None:
    c = CreateFlowClient()
    rep = create_flow_any(c, "process", "Expense Approval")
    assert isinstance(rep, FlowCreateReport)
    assert rep.status == "Draft" and rep.born_live is False and rep.flow_id


def test_create_flow_list_is_born_live() -> None:
    c = CreateFlowClient()
    rep = create_flow_any(c, "list", "Priority")
    assert isinstance(rep, FlowCreateReport)
    assert rep.status == "Live" and rep.born_live is True


def test_create_flow_dataset_is_born_live() -> None:
    c = CreateFlowClient()
    rep = create_flow_any(c, "dataset", "Vendors")
    assert isinstance(rep, FlowCreateReport)
    assert rep.status == "Live" and rep.born_live is True


def test_create_flow_case_requires_item_type_and_prefix() -> None:
    c = CreateFlowClient()
    got = create_flow_any(c, "case", "Support Tickets")
    assert isinstance(got, Err) and got.kind == "verify"
    assert "item_type" in got.message and "prefix" in got.message


def test_create_flow_case_with_extra_succeeds() -> None:
    c = CreateFlowClient()
    rep = create_flow_any(c, "case", "Support Tickets",
                          extra={"item_type": "Board", "prefix": "SUP"})
    assert isinstance(rep, FlowCreateReport)
    assert rep.status == "Live" and rep.born_live is True


def test_create_flow_unknown_kind_rejected() -> None:
    c = CreateFlowClient()
    got = create_flow_any(c, "wizardry", "x")
    assert isinstance(got, Err) and got.kind == "verify"


# ---- forge_publish_app (#4) --------------------------------------------------------------------


class PublishAppClient(FakeClient):
    def __init__(self, app_draft: dict[str, Any]) -> None:
        super().__init__(_bare_draft())
        self.app_draft = app_draft
        self.publish_calls: list[str] = []

    def publish_app(self, app_id):  # type: ignore[override]
        self.publish_calls.append(app_id)
        return None

    def get_app_draft(self, app_id):  # type: ignore[override]
        return self.app_draft


def test_publish_app_reads_back_meta_version_no_runtime_node() -> None:
    c = PublishAppClient({"Root": "M1", "_meta_version": "v9", "M1": {"Id": "M1"}})
    rep = publish_application_verified(c, "App1")
    assert rep["published"] is True and rep["isError"] is False
    assert rep["meta_version"] == "v9"
    assert rep["runtime_id"] is None and rep["note"]
    assert c.publish_calls == ["App1"]


def test_publish_app_surfaces_a_runtime_node_when_present() -> None:
    c = PublishAppClient({"Root": "M1", "_meta_version": "v9", "M1": {"Id": "M1"},
                          "Runtime_abc123": {"Id": "Runtime_abc123"}})
    rep = publish_application_verified(c, "App1")
    assert rep["runtime_id"] == "Runtime_abc123"
    assert "note" not in rep or rep.get("note") is None


def test_publish_app_propagates_publish_failure() -> None:
    class Failing(PublishAppClient):
        def publish_app(self, app_id):  # type: ignore[override]
            return Err("http", "boom", 500)

    c = Failing({"Root": "M1", "_meta_version": "v9", "M1": {"Id": "M1"}})
    got = publish_application_verified(c, "App1")
    assert isinstance(got, Err)


# ---- forge_dataset_records (#5) ----------------------------------------------------------------


class DatasetRecordClient(FakeClient):
    def __init__(self) -> None:
        super().__init__(_bare_draft())
        self.records: list[dict[str, Any]] = []
        self.dup_names: set[str] = set()

    def create_dataset_record(self, flow_id, record):  # type: ignore[override]
        name = record.get("Name")
        if name in self.dup_names:
            return Err("http", "DuplicateKeyException: Name already exists", status=409)
        self.dup_names.add(name)
        self.records.append(record)
        return {"_id": f"Rec_{len(self.records)}", **record}

    def list_dataset_records(self, flow_id):  # type: ignore[override]
        return {"Columns": ["Name"], "Data": list(self.records)}


def test_dataset_records_create_lands_and_counts() -> None:
    c = DatasetRecordClient()
    rep = apply_dataset_records(c, "F1", "create", record={"Name": "Acme Corp"})
    assert rep["isError"] is False
    assert rep["created"] == 1 and rep["listed"] == 0 and rep["failed"] == 0


def test_dataset_records_create_requires_a_record() -> None:
    c = DatasetRecordClient()
    got = apply_dataset_records(c, "F1", "create")
    assert isinstance(got, Err) and got.kind == "verify"


def test_dataset_records_duplicate_name_is_a_clean_err() -> None:
    c = DatasetRecordClient()
    apply_dataset_records(c, "F1", "create", record={"Name": "Acme Corp"})
    got = apply_dataset_records(c, "F1", "create", record={"Name": "Acme Corp"})
    assert isinstance(got, Err)
    assert "Acme Corp" in got.message and "duplicate" in got.message.lower()


def test_dataset_records_list_returns_columns_and_rows() -> None:
    c = DatasetRecordClient()
    apply_dataset_records(c, "F1", "create", record={"Name": "Acme Corp"})
    rep = apply_dataset_records(c, "F1", "list")
    assert rep["isError"] is False
    assert rep["listed"] == 1 and rep["columns"] == ["Name"]


def test_dataset_records_unknown_op_rejected() -> None:
    c = DatasetRecordClient()
    got = apply_dataset_records(c, "F1", "update", record={"Name": "x"})
    assert isinstance(got, Err) and got.kind == "verify"


# ---- forge_set_role_preference (#6) -------------------------------------------------------------


def test_set_role_preference_writes_default_page_and_navigation() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}])
    rep = apply_set_role_preference(c, "R1", default_page="Page_123",
                                    default_navigation="Navigation001")
    assert isinstance(rep, RolePreferenceReport)
    assert rep.verified is True
    live = c.app_roles[0]["Preference"]
    assert live == {"DefaultPage": "Page_123", "DefaultNavigation": "Navigation001"}


def test_set_role_preference_default_sentinel_is_accepted() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}])
    rep = apply_set_role_preference(c, "R1", default_page="Default")
    assert isinstance(rep, RolePreferenceReport) and rep.verified is True
    assert c.app_roles[0]["Preference"]["DefaultPage"] == "Default"


def test_set_role_preference_never_drops_existing_members() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer",
                          "Members": [{"_id": "U0", "Kind": "User", "Name": "Old"}], "UserCount": 1}])
    apply_set_role_preference(c, "R1", default_page="Page_1")
    assert c.app_roles[0]["Members"] == [{"_id": "U0", "Kind": "User", "Name": "Old"}]


def test_set_role_preference_requires_at_least_one_key() -> None:
    c = RoleUsersClient([{"_id": "R1", "Name": "Reviewer", "Members": [], "UserCount": 0}])
    got = apply_set_role_preference(c, "R1")
    assert isinstance(got, Err) and got.kind == "verify"
