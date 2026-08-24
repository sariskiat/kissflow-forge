"""Unit tests for the live-write client. NO network: transport is stubbed."""
from __future__ import annotations

from typing import Any

import pytest

from kfforge.client import (
    ApplyReport,
    RoleUsersReport,
    apply_add_role_users,
    BranchConditionReport,
    DeleteFieldsReport,
    Err,
    EventReport,
    FullFieldsReport,
    GotoGateReport,
    KfClient,
    KfConfig,
    MemberReport,
    RenameFieldsReport,
    RequiredReport,
    StyleReport,
    TableReport,
    WorkflowReport,
    apply_branch_conditions,
    apply_dataset_records,
    apply_field_events,
    apply_fields,
    apply_fields_and_layout,
    apply_fields_full,
    apply_goto_gate,
    apply_layout,
    apply_member_batch,
    apply_member_roles,
    apply_report_members,
    apply_required,
    apply_section_style,
    apply_step_permissions,
    apply_table,
    apply_workflow,
    create_application_verified,
    create_flow_any,
    create_process,
    delete_anything,
    delete_fields,
    discover_member_source,
    rename_form_fields,
    run_doctor,
)
from kfforge.graph import apply_changes as _apply_changes
from kfforge.graph import build_workflow as _build_workflow
from kfforge.graph import ensure_process_def as _ensure_process_def
from kfforge.types import FieldSpec, FieldType

DEV = KfConfig(key_id="k", key_secret="s", account="Acc", domain="dev-x.example.com", app_id="App")


def _bare_form_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "M", "FlowType": "Form"},
    }


def _bare_process_draft(version: str = "v1") -> dict:
    return {
        "Root": "M1",
        "_meta_version": version,
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
    }


class FakeClient(KfClient):
    """KfClient with the HTTP verb intercepted — exercises the real read-verify-write logic.

    Extended (Node G) with in-memory stand-ins for every NEW KfClient method the P2 orchestration
    functions call: lists/items, flow member rosters, page/application inventories. Every new
    attribute defaults to empty, so none of the ORIGINAL tests below (which only ever touch
    get_draft/put_draft/publish) observe any behavior change.
    """

    def __init__(self, draft: dict) -> None:
        super().__init__(DEV)
        self.draft = draft
        self.published = False
        self.puts = 0
        # run_doctor
        self.list_items: dict[str, list[str]] = {}
        self.fail_list_ids: set[str] = set()
        # member batch
        self.flows: dict[str, list[dict[str, Any]]] = {}
        self.members: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.member_batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        self.report_member_batches: list[tuple[str, str, list[dict[str, Any]]]] = []
        # account-level AppRoles (Node L)
        self.app_roles: list[dict[str, Any]] = []
        # applications / pages
        self.applications: dict[str, dict[str, Any]] = {}
        self.archived_apps: set[str] = set()
        self.pages: dict[str, dict[str, dict[str, Any]]] = {}
        self._app_counter = 0
        self._role_counter = 0

    def get_draft(self, kind, flow_id):  # type: ignore[override]
        return self.draft

    def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
        live = self.draft.get("_meta_version")
        if expect_version is not None and live != expect_version:
            return Err("conflict", f"expected {expect_version!r}, live {live!r}")
        self.puts += 1
        new["_meta_version"] = "v2"
        self.draft = new
        return new

    def publish(self, kind, flow_id):  # type: ignore[override]
        self.published = True

    # --- run_doctor ---
    def get_list_items(self, list_id):  # type: ignore[override]
        if list_id in self.fail_list_ids:
            return Err("http", f"list {list_id} fetch failed")
        return self.list_items.get(list_id, [])

    # --- word lists (#13) ---
    def list_lists(self):  # type: ignore[override]
        return [{"_id": lid, "Name": name} for name, lid in getattr(self, "word_lists", {}).items()]

    def create_list(self, name):  # type: ignore[override]
        if not hasattr(self, "word_lists"):
            self.word_lists: dict[str, str] = {}
        lid = f"{name.replace(' ', '_')}_X1"
        self.word_lists[name] = lid
        return {"_id": lid, "Type": "List", "Status": "Live", "Name": name}

    def set_list_items(self, list_id, items):  # type: ignore[override]
        dropped = getattr(self, "drop_list_values", set())
        self.list_items[list_id] = [v for v in items if v not in dropped]  # REPLACE semantics
        return {"ListItems": self.list_items[list_id]}

    # --- member batch ---
    def list_flows(self, kind):  # type: ignore[override]
        return self.flows.get(kind, [])

    def get_members(self, kind, flow_id):  # type: ignore[override]
        return self.members.get((kind, flow_id), [])

    def list_app_roles(self, app_id=None):  # type: ignore[override]
        if app_id is None:
            return list(self.app_roles)
        # mirror the REAL KfClient.list_app_roles scope match: either the top-level
        # `_application_id` scalar OR an `Applications[]` entry (a created role may carry only the
        # scalar — the bug apply_member_roles used to duplicate on).
        return [r for r in self.app_roles
                if r.get("_application_id") == app_id
                or app_id in {a.get("_id") for a in (r.get("Applications") or [])}]

    def get_app_role(self, role_id):  # type: ignore[override]
        return next((r for r in self.app_roles if r.get("_id") == role_id), {"_id": role_id})

    def create_app_role(self, name, app_id=None):  # type: ignore[override]
        # mirror the live POST /app_role/2/{acct} contract: returns a fresh _id, scopes to app_id.
        self._role_counter += 1
        rid = f"RoNew{self._role_counter}"
        scope = app_id if app_id is not None else self._cfg.app_id
        self.app_roles.append({"_id": rid, "Name": name,
                               "Applications": [{"_id": scope, "Type": "Application"}],
                               "_application_id": scope})
        return rid

    def delete_app_role(self, role_id):  # type: ignore[override]
        self.app_roles = [r for r in self.app_roles if r.get("_id") != role_id]
        return {"status": "success"}

    def post_member_batch(self, kind, flow_id, members):  # type: ignore[override]
        self.member_batches.append((kind, flow_id, list(members)))
        self.members[(kind, flow_id)] = list(members)
        return {"ok": True}

    def post_report_member_batch(self, flow_id, report_id, members):  # type: ignore[override]
        self.report_member_batches.append((flow_id, report_id, list(members)))
        return {"ok": True}

    def delete_flow(self, kind, flow_id, archive_first=True):  # type: ignore[override]
        self.flows[kind] = [f for f in self.flows.get(kind, []) if f.get("_id") != flow_id]

    # --- applications ---
    def create_application(self, name):  # type: ignore[override]
        self._app_counter += 1
        aid = f"App_{self._app_counter}"
        self.applications[aid] = {"_id": aid, "Name": name}
        return aid

    def list_applications(self):  # type: ignore[override]
        return list(self.applications.values())

    def archive_application(self, app_id):  # type: ignore[override]
        self.archived_apps.add(app_id)

    def delete_application(self, app_id, archive_first=True):  # type: ignore[override]
        if archive_first:
            self.archive_application(app_id)
        self.applications.pop(app_id, None)

    # --- pages ---
    def list_pages(self, app_id):  # type: ignore[override]
        return list(self.pages.get(app_id, {}).values())

    def delete_page(self, app_id, page_id):  # type: ignore[override]
        self.pages.get(app_id, {}).pop(page_id, None)


def test_prod_domain_is_refused() -> None:
    """The dev-guard is the whole safety story — a non-dev domain must never build a config."""
    got = KfConfig(key_id="k", key_secret="s", account="A", domain="kissflow.com", app_id="App")
    assert "dev-" not in got.domain  # sanity: the fixture really is a prod-shaped domain
    with pytest.MonkeyPatch.context() as mp:
        for k, v in {"KF_DEV_ACCESS_KEY_ID": "k", "KF_DEV_ACCESS_KEY_SECRET": "s",
                     "KF_DEV_ACCOUNT_ID": "A", "KF_DEV_DOMAIN": "acme.kissflow.com"}.items():
            mp.setenv(k, v)
        err = KfConfig.from_env()
    assert isinstance(err, Err) and err.kind == "config"


def test_missing_env_returns_err_not_keyerror() -> None:
    with pytest.MonkeyPatch.context() as mp:
        for k in ("KF_DEV_ACCESS_KEY_ID", "KF_DEV_ACCESS_KEY_SECRET",
                  "KF_DEV_ACCOUNT_ID", "KF_DEV_DOMAIN"):
            mp.delenv(k, raising=False)
        got = KfConfig.from_env()
    assert isinstance(got, Err) and got.kind == "config"


def test_apply_fields_adds_and_verifies() -> None:
    c = FakeClient(_bare_form_draft())
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXTAREA)])
    assert isinstance(rep, ApplyReport)
    assert rep.added == ("alpha",) and rep.verified == ("alpha",)
    assert rep.missing == () and rep.skipped == ()
    assert rep.as_tool_result()["isError"] is False


def test_apply_fields_is_idempotent_and_writes_nothing_second_time() -> None:
    c = FakeClient(_bare_form_draft())
    spec = [FieldSpec(name="alpha", type=FieldType.TEXT)]
    apply_fields(c, "form", "F1", spec)
    rep = apply_fields(c, "form", "F1", spec)
    assert isinstance(rep, ApplyReport)
    assert rep.added == () and rep.skipped == ("alpha",) and rep.verified == ("alpha",)
    assert c.puts == 1, "re-applying an existing field must not issue a second PUT"


def test_conflict_when_draft_moved_under_us() -> None:
    c = FakeClient(_bare_form_draft())
    got = c.put_draft("form", "F1", _bare_form_draft(), expect_version="stale")
    assert isinstance(got, Err) and got.kind == "conflict"


def test_bad_field_type_is_rejected_before_any_write() -> None:
    c = FakeClient(_bare_form_draft())
    got = apply_fields(c, "form", "F1",
                       [FieldSpec(name="x", type="Formula")])  # type: ignore[arg-type]
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0, "an invalid change set must never reach the network"


def test_publish_is_skipped_when_a_field_is_missing_on_read_back() -> None:
    """Output-invariant audit: never publish a draft that failed verification."""
    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            return new  # accepted, but self.draft is NOT updated -> read-back lacks the field

    c = Dropping(_bare_form_draft())
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="ghost", type=FieldType.TEXT)], publish=True)
    assert isinstance(rep, ApplyReport)
    assert rep.missing == ("ghost",) and rep.published is False
    assert rep.as_tool_result()["isError"] is True
    assert c.published is False


# =====================================================================================
# Node G (P2 server surface) — offline unit tests for the new live-orchestration functions.
# Same FakeClient(read-verify-write intercepted) pattern as everything above.
# =====================================================================================

# ---- apply_fields_and_layout ---------------------------------------------------------------

def test_apply_fields_and_layout_adds_fields_and_lands_the_named_section() -> None:
    c = FakeClient(_bare_form_draft())
    rep = apply_fields_and_layout(
        c, "form", "F1",
        [FieldSpec(name="alpha", type=FieldType.TEXT), FieldSpec(name="beta", type=FieldType.TEXT)],
        groups=[("Group A", ["alpha", "beta"])],
    )
    assert isinstance(rep, ApplyReport)
    assert rep.verified == ("alpha", "beta") and rep.missing == ()

    top_row = c.draft["M1"]["Model::Row"][0]
    section = c.draft[c.draft[top_row]["Row::Column"][0]]
    assert section["Name"] == "Group A"


def test_apply_fields_and_layout_no_groups_adds_fields_without_regrouping() -> None:
    c = FakeClient(_bare_form_draft())
    rep = apply_fields_and_layout(
        c, "form", "F1",
        [FieldSpec(name="alpha", type=FieldType.TEXT)],
        groups=None,
    )
    assert isinstance(rep, ApplyReport)
    assert rep.verified == ("alpha",) and rep.missing == ()
    assert c.puts == 1


def test_apply_fields_and_layout_no_op_does_not_put_when_no_added_and_no_groups() -> None:
    c = FakeClient(_bare_form_draft())
    spec = [FieldSpec(name="alpha", type=FieldType.TEXT)]
    apply_fields_and_layout(c, "form", "F1", spec, groups=None)
    assert c.puts == 1

    rep = apply_fields_and_layout(c, "form", "F1", spec, groups=None)
    assert isinstance(rep, ApplyReport)
    assert rep.added == () and rep.skipped == ("alpha",)
    assert c.puts == 1


def test_apply_fields_and_layout_publishes_when_requested_and_clean() -> None:
    c = FakeClient(_bare_form_draft())
    rep = apply_fields_and_layout(
        c, "form", "F1",
        [FieldSpec(name="alpha", type=FieldType.TEXT)],
        publish=True,
    )
    assert isinstance(rep, ApplyReport)
    assert rep.published is True
    assert c.published is True


def test_apply_fields_and_layout_publish_failure_returns_err() -> None:
    class FailPublish(FakeClient):
        def publish(self, kind, flow_id):  # type: ignore[override]
            return Err("http", "publish rejected")

    c = FailPublish(_bare_form_draft())
    got = apply_fields_and_layout(
        c, "form", "F1",
        [FieldSpec(name="alpha", type=FieldType.TEXT)],
        publish=True,
    )
    assert isinstance(got, Err) and got.kind == "http"


def test_apply_fields_and_layout_initial_get_draft_error_returns_err() -> None:
    class FailGet(FakeClient):
        def get_draft(self, kind, flow_id):  # type: ignore[override]
            return Err("http", "draft fetch failed")

    c = FailGet(_bare_form_draft())
    got = apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    assert isinstance(got, Err) and got.kind == "http"


def test_apply_fields_and_layout_put_draft_error_returns_err() -> None:
    class FailPut(FakeClient):
        def put_draft(
            self, kind, flow_id, new, expect_version
        ):  # type: ignore[override]
            return Err("conflict", "draft changed under us")

    c = FailPut(_bare_form_draft())
    got = apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    assert isinstance(got, Err) and got.kind == "conflict"


def test_apply_fields_and_layout_read_back_error_returns_err() -> None:
    class FailReadBack(FakeClient):
        def __init__(self, draft: dict) -> None:
            super().__init__(draft)
            self._calls = 0

        def get_draft(self, kind, flow_id):  # type: ignore[override]
            self._calls += 1
            if self._calls > 1:
                return Err("http", "read-back failed")
            return self.draft

    c = FailReadBack(_bare_form_draft())
    got = apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    assert isinstance(got, Err) and got.kind == "http"


def test_apply_fields_and_layout_not_implemented_error_caught_as_verify_err(
    monkeypatch,
) -> None:
    def fake_apply_changes(draft, specs):
        raise NotImplementedError("unsupported field type")

    monkeypatch.setattr("kfforge.client.apply_changes", fake_apply_changes)
    c = FakeClient(_bare_form_draft())
    got = apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)]
    )
    assert isinstance(got, Err) and got.kind == "verify"
    assert "offline apply rejected" in got.message


def test_apply_fields_and_layout_always_writes_when_groups_given_even_with_zero_new_fields() -> None:
    """Unlike plain apply_fields, a re-layout with no new fields must still PUT — a section move
    is a real change even when every field already existed."""
    c = FakeClient(_bare_form_draft())
    spec = [FieldSpec(name="alpha", type=FieldType.TEXT)]
    apply_fields_and_layout(c, "form", "F1", spec, groups=[("Solo", ["alpha"])])
    assert c.puts == 1

    rep = apply_fields_and_layout(c, "form", "F1", spec, groups=[("Renamed", ["alpha"])])
    assert isinstance(rep, ApplyReport)
    assert rep.added == () and rep.skipped == ("alpha",), "no NEW field on the second call"
    assert c.puts == 2, "the regroup must still write even though nothing was added"

    top_row = c.draft["M1"]["Model::Row"][0]
    section = c.draft[c.draft[top_row]["Row::Column"][0]]
    assert section["Name"] == "Renamed"


def test_apply_fields_and_layout_offline_rejection_never_reaches_put() -> None:
    c = FakeClient(_bare_form_draft())
    got = apply_fields_and_layout(c, "form", "F1", [FieldSpec(name="x", type="Nope")])  # type: ignore[arg-type]
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


# ---- apply_table -----------------------------------------------------------------------------

def test_apply_table_creates_and_verifies_columns() -> None:
    c = FakeClient(_bare_form_draft())
    rep = apply_table(c, "form", "F1", "Rounds",
                      [("Round", "Number"), ("Notes", "Text")], max_rows=3)
    assert isinstance(rep, TableReport)
    assert rep.created is True
    assert rep.verified_columns == ("Round", "Notes") and rep.missing_columns == ()
    assert rep.as_tool_result()["isError"] is False
    assert c.puts == 1


def test_apply_table_is_idempotent_and_writes_nothing_second_time() -> None:
    c = FakeClient(_bare_form_draft())
    cols = [("Round", "Number")]
    apply_table(c, "form", "F1", "Rounds", cols)
    rep = apply_table(c, "form", "F1", "Rounds", cols)
    assert isinstance(rep, TableReport)
    assert rep.created is False
    assert c.puts == 1, "re-applying an existing table must not issue a second PUT"


def test_apply_table_offline_rejection_never_reaches_put() -> None:
    c = FakeClient(_bare_form_draft())
    got = apply_table(c, "form", "F1", "Rounds", [("Bad Col", "NotAType")])
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


# ---- apply_workflow --------------------------------------------------------------------------

def test_apply_workflow_reports_assigned_vs_unassigned_and_verifies_step_names() -> None:
    c = FakeClient(_bare_process_draft())
    rep = apply_workflow(c, "F1", [("Draft", "Role_A"), ("Review", None)])
    assert isinstance(rep, WorkflowReport)
    assert rep.verified_steps == ("Draft", "Review") and rep.missing_steps == ()
    assert rep.assigned == ("Draft",) and rep.unassigned == ("Review",)
    assert rep.as_tool_result()["isError"] is False


def test_apply_workflow_offline_rejection_never_reaches_put() -> None:
    c = FakeClient(_bare_process_draft())
    got = apply_workflow(c, "F1", [])  # build_workflow requires at least the implicit chain to work with
    # an empty steps list is legal for build_workflow (Start -> End only); assert it does NOT error
    assert isinstance(got, WorkflowReport)
    assert got.steps == () and c.puts == 1


# ---- apply_goto_gate --------------------------------------------------------------------------

def _process_with_boolean_field() -> dict:
    draft = _ensure_process_def(_bare_process_draft(), ("Review",))
    return _apply_changes(draft, [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])


def test_apply_goto_gate_wires_and_verifies_the_loop_condition() -> None:
    c = FakeClient(_process_with_boolean_field())
    rep = apply_goto_gate(c, "F1", target_activity_name="Review", field_name="Done Flag")
    assert isinstance(rep, GotoGateReport)
    assert rep.verified is True and rep.goto_activity_id is not None
    assert rep.as_tool_result()["isError"] is False


def test_apply_goto_gate_unknown_target_step_rejected_before_any_write() -> None:
    c = FakeClient(_process_with_boolean_field())
    got = apply_goto_gate(c, "F1", target_activity_name="Nope", field_name="Done Flag")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_goto_gate_unknown_field_rejected_before_any_write() -> None:
    c = FakeClient(_process_with_boolean_field())
    got = apply_goto_gate(c, "F1", target_activity_name="Review", field_name="Nope")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_goto_gate_non_boolean_field_rejected_by_gate_polarity() -> None:
    draft = _ensure_process_def(_bare_process_draft(), ("Review",))
    draft = _apply_changes(draft, [FieldSpec(name="Choice", type=FieldType.SELECT,
                                             referred_list="List_Sample01")])
    c = FakeClient(draft)
    got = apply_goto_gate(c, "F1", target_activity_name="Review", field_name="Choice")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


# ---- apply_goto_gate — branch_name (Node M, conditional routing) ------------------------------

def _process_with_branches(deciding_field_type: FieldType = FieldType.SELECT) -> dict:
    """1 root step -> a 2-branch Parallel (1 step each) -> a Select (or Text) deciding field."""
    draft = _build_workflow(
        _bare_process_draft(), [("Intake", None)],
        parallel=("Route", [("Branch A", [("Shared Step", None)]),
                            ("Branch B", [("Shared Step", None)])]),
        parallel_after=0,
    )
    kwargs: dict[str, Any] = {}
    if deciding_field_type == FieldType.SELECT:
        kwargs["referred_list"] = "List_Sample01"
    return _apply_changes(draft, [FieldSpec(name="Track", type=deciding_field_type, **kwargs)])


def test_apply_goto_gate_with_branch_name_scopes_target_into_that_branch() -> None:
    """Both branches carry a step named "Shared Step" -- without branch_name this is ambiguous;
    WITH it, the GotoTask must land inside the NAMED branch, never the other one."""
    draft = _process_with_branches()
    branch_a_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch A")
    branch_b_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch B")
    draft = _apply_changes(draft, [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    c = FakeClient(draft)

    rep = apply_goto_gate(c, "F1", target_activity_name="Shared Step", field_name="Done Flag",
                          branch_name="Branch A")
    assert isinstance(rep, GotoGateReport)
    assert rep.verified is True and rep.branch_name == "Branch A"
    assert rep.as_tool_result()["isError"] is False

    goto_id = rep.goto_activity_id
    assert goto_id is not None
    assert c.draft[goto_id]["ProcessDef"] == branch_a_pd_id
    assert goto_id in c.draft[branch_a_pd_id]["ProcessDef::Activity"]
    assert goto_id not in c.draft[branch_b_pd_id]["ProcessDef::Activity"]


def test_apply_goto_gate_unknown_branch_name_rejected_before_any_write() -> None:
    draft = _apply_changes(_process_with_branches(), [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    c = FakeClient(draft)
    got = apply_goto_gate(c, "F1", target_activity_name="Shared Step", field_name="Done Flag",
                          branch_name="No Such Branch")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_goto_gate_branch_name_target_not_in_that_branch_rejected() -> None:
    draft = _apply_changes(_process_with_branches(), [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    c = FakeClient(draft)
    got = apply_goto_gate(c, "F1", target_activity_name="Intake", field_name="Done Flag",
                          branch_name="Branch A")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_goto_gate_no_branch_name_is_unchanged_from_before_the_parameter_existed() -> None:
    """A plain, unambiguous root-chain call with no branch_name must behave exactly as it always
    did — the new parameter must never change default behavior."""
    c = FakeClient(_process_with_boolean_field())
    rep = apply_goto_gate(c, "F1", target_activity_name="Review", field_name="Done Flag")
    assert isinstance(rep, GotoGateReport)
    assert rep.verified is True and rep.branch_name is None
    assert rep.as_tool_result()["branch_name"] is None


def test_apply_goto_gate_ambiguous_target_without_branch_name_rejected_before_any_write() -> None:
    """Node M review (2026-08-07): a step name that repeats across branches, resolved with NO
    branch_name, used to silently pick whichever match dict iteration found first and report a
    clean `verified: True` — a wrong graph with a clean report. Both branches in
    _process_with_branches() carry a step literally named "Shared Step"; this must now be a loud,
    pre-write rejection that names both candidate branches, not a silent pick."""
    draft = _apply_changes(_process_with_branches(), [FieldSpec(name="Done Flag", type=FieldType.BOOLEAN)])
    c = FakeClient(draft)
    got = apply_goto_gate(c, "F1", target_activity_name="Shared Step", field_name="Done Flag")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0
    assert "ambiguous" in got.message
    assert "Branch A" in got.message and "Branch B" in got.message
    assert "branch_name" in got.message


# ---- apply_branch_conditions (Node M, conditional routing) ------------------------------------

def test_apply_branch_conditions_wires_and_verifies_both_branches() -> None:
    c = FakeClient(_process_with_branches())
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]

    rep = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha", "Branch B": "Beta"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.verified == ("Branch A", "Branch B") and rep.missing == ()
    assert rep.as_tool_result()["isError"] is False


def test_apply_branch_conditions_writes_the_correct_owner_key_and_ast_shape() -> None:
    draft = _process_with_branches()
    branch_a_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch A")
    field_id = next(k for k, v in draft.items()
                    if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Track")
    c = FakeClient(draft)
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]

    apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha"})

    expr_ids = c.draft[branch_a_pd_id]["ProcessDef::Expression"]
    assert len(expr_ids) == 1
    expr = c.draft[expr_ids[0]]
    assert expr["ProcessDef"] == branch_a_pd_id, "owner key must be ProcessDef, a branch condition"
    root_id = expr["Expression::Node"][0]
    root = c.draft[root_id]
    lhs_id, rhs_id = root["Node::Node"]
    assert c.draft[lhs_id]["Type"] == "Field" and c.draft[lhs_id]["Field"] == field_id
    assert c.draft[rhs_id]["Type"] == "Static" and c.draft[rhs_id]["Value"] == "Alpha"


def test_apply_branch_conditions_rejects_literal_not_in_real_options_before_any_write() -> None:
    """CLAUDE.md's own war story: a branch that never fires over one mis-cased/unreal literal —
    caught HERE, before the write, never discovered live."""
    c = FakeClient(_process_with_branches())
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]

    got = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Not A Real Option"})
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_branch_conditions_unknown_branch_name_rejected_before_any_write() -> None:
    c = FakeClient(_process_with_branches())
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]
    got = apply_branch_conditions(c, "F1", "Track", {"No Such Branch": "Alpha"})
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_branch_conditions_unknown_field_rejected_before_any_write() -> None:
    c = FakeClient(_process_with_branches())
    got = apply_branch_conditions(c, "F1", "No Such Field", {"Branch A": "Alpha"})
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_branch_conditions_requires_exactly_one_parallel_gateway() -> None:
    c = FakeClient(_process_with_boolean_field())  # a plain sequential process, no Parallel at all
    got = apply_branch_conditions(c, "F1", "Done Flag", {"Branch A": "Alpha"})
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_branch_conditions_text_field_skips_option_validation() -> None:
    """A Text-typed deciding field has no ReferredList to validate against — the literal is
    written as given (expr.build_branch_condition's own options=None contract), never blocked for
    lack of a live list, matching the field types _BRANCH_FIELD_DATA_TYPE actually supports."""
    c = FakeClient(_process_with_branches(deciding_field_type=FieldType.TEXT))
    rep = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Anything At All"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.verified == ("Branch A",) and rep.missing == ()


def test_apply_branch_conditions_is_idempotent_replacing_not_accumulating() -> None:
    """Re-running with a DIFFERENT literal for the same branch must REPLACE the condition, never
    stack a second one on the same ProcessDef."""
    draft = _process_with_branches()
    branch_a_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch A")
    c = FakeClient(draft)
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]

    apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha"})
    rep = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Beta"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.verified == ("Branch A",)

    expr_ids = c.draft[branch_a_pd_id]["ProcessDef::Expression"]
    assert len(expr_ids) == 1, f"expected exactly one condition on Branch A, got {len(expr_ids)}"
    root_id = c.draft[expr_ids[0]]["Expression::Node"][0]
    _lhs_id, rhs_id = c.draft[root_id]["Node::Node"]
    assert c.draft[rhs_id]["Value"] == "Beta"


def test_apply_branch_conditions_only_touches_the_named_branches() -> None:
    """A branch NOT named in branch_literals must be left completely alone."""
    draft = _process_with_branches()
    branch_b_pd_id = next(v["Id"] for v in draft.values()
                          if isinstance(v, dict) and v.get("Kind") == "ProcessDef"
                          and v.get("Name") == "Branch B")
    c = FakeClient(draft)
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]

    apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha"})
    assert "ProcessDef::Expression" not in c.draft[branch_b_pd_id]


# ---- apply_branch_conditions — uncovered (Node M review, fail-OPEN hazard) ---------------------
# A value matching NO branch condition does not park and does not error: it silently skips the
# WHOLE Parallel and the item completes with no work done (verified live 2026-08-07). `uncovered`
# is the audit bucket that states this instead of letting a caller discover it later.

def test_apply_branch_conditions_reports_uncovered_real_options() -> None:
    c = FakeClient(_process_with_branches())
    c.list_items["List_Sample01"] = ["Alpha", "Beta", "Gamma"]

    rep = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha", "Branch B": "Beta"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.uncovered == ("Gamma",)
    assert rep.as_tool_result()["uncovered"] == ["Gamma"]


def test_apply_branch_conditions_uncovered_is_never_an_error() -> None:
    """A caller may genuinely want a value to end the case with no work done -- uncovered must
    never flip isError on its own, only missing does."""
    c = FakeClient(_process_with_branches())
    c.list_items["List_Sample01"] = ["Alpha", "Beta", "Gamma"]

    rep = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.uncovered != ()
    assert rep.missing == ()
    assert rep.as_tool_result()["isError"] is False


def test_apply_branch_conditions_uncovered_accounts_for_branches_this_call_never_touched() -> None:
    """uncovered must reflect the FULL branch set on the gateway, not just this call's own
    branch_literals -- otherwise a value an EARLIER call already covered on a different branch
    would false-alarm here every time that other branch is left untouched."""
    c = FakeClient(_process_with_branches())
    c.list_items["List_Sample01"] = ["Alpha", "Beta"]

    apply_branch_conditions(c, "F1", "Track", {"Branch A": "Alpha"})
    rep = apply_branch_conditions(c, "F1", "Track", {"Branch B": "Beta"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.uncovered == (), (
        "Branch A's earlier condition still covers Alpha -- must not be reported as uncovered "
        "just because THIS call only touched Branch B"
    )


def test_apply_branch_conditions_uncovered_is_empty_for_a_text_field() -> None:
    """A Text-typed deciding field has no enumerable option universe -- uncovered is () meaning
    "nothing checked," never a false claim of full coverage."""
    c = FakeClient(_process_with_branches(deciding_field_type=FieldType.TEXT))
    rep = apply_branch_conditions(c, "F1", "Track", {"Branch A": "Anything At All"})
    assert isinstance(rep, BranchConditionReport)
    assert rep.uncovered == ()


# ---- apply_field_events -----------------------------------------------------------------------

def test_apply_field_events_wires_and_verifies() -> None:
    draft = _apply_changes(_bare_form_draft(), [FieldSpec(name="Source", type=FieldType.TEXT)])
    field_id = next(k for k, v in draft.items()
                    if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Source")
    c = FakeClient(draft)
    script = f"(async () => {{ kf.form.setFieldValue('{field_id}', 'x'); }})();"
    rep = apply_field_events(c, "F1", {"Source": [("onChange", script)]})
    assert isinstance(rep, EventReport)
    assert rep.verified == ("Source",) and rep.missing == ()


def test_apply_field_events_offline_rejection_never_reaches_put() -> None:
    draft = _apply_changes(_bare_form_draft(), [FieldSpec(name="Source", type=FieldType.TEXT)])
    c = FakeClient(draft)
    got = apply_field_events(c, "F1", {"NoSuchField": [("onChange", "1;")]})
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


# ---- apply_section_style ----------------------------------------------------------------------

def test_apply_section_style_wires_and_verifies() -> None:
    draft = _apply_changes(_bare_form_draft(), [FieldSpec(name="A", type=FieldType.TEXT)])
    c = FakeClient(draft)
    rep = apply_section_style(c, "F1", {"M": {"Section.Bg.Color": "Color.Info.300"}})
    assert isinstance(rep, StyleReport)
    assert rep.verified == ("M",) and rep.missing == ()


def test_apply_section_style_unknown_section_rejected_before_any_write() -> None:
    draft = _apply_changes(_bare_form_draft(), [FieldSpec(name="A", type=FieldType.TEXT)])
    c = FakeClient(draft)
    got = apply_section_style(c, "F1", {"NoSuchSection": {"Section.Bg.Color": "Color.Info.300"}})
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


# ---- run_doctor -------------------------------------------------------------------------------

def test_run_doctor_reads_real_list_options_for_every_select_field() -> None:
    draft = {
        "Root": "M1", "_meta_version": "v1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form",
              "Model::Field": ["Fld1"]},
        "Fld1": {"Id": "Fld1", "Kind": "Field", "Type": "Select", "Name": "Choice",
                "Model": "M1", "ReferredList": "List_1"},
    }
    c = FakeClient(draft)
    c.list_items["List_1"] = ["Yes", "No"]
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert got["list_ids_checked"] == ["List_1"]
    assert got["list_fetch_errors"] == {}
    assert "checked" in got and isinstance(got["checked"], dict)


def test_run_doctor_records_a_list_fetch_failure_without_crashing() -> None:
    draft = {
        "Root": "M1", "_meta_version": "v1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form",
              "Model::Field": ["Fld1"]},
        "Fld1": {"Id": "Fld1", "Kind": "Field", "Type": "Select", "Name": "Choice",
                "Model": "M1", "ReferredList": "List_Broken"},
    }
    c = FakeClient(draft)
    c.fail_list_ids = {"List_Broken"}
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert got["list_ids_checked"] == []
    assert "List_Broken" in got["list_fetch_errors"]


def _draft_with_an_approle_assignee() -> dict:
    """A one-step process whose UserTask carries a real AppRole assignee — the exact condition
    CLAUDE.md > Members first says publish rejects when the flow has NO members."""
    return {
        "Root": "M1", "_meta_version": "v1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": "P", "FlowType": "Process"},
        "Activity_A1": {"Id": "Activity_A1", "Kind": "Activity", "NodeType": "UserTask",
                        "Name": "Review", "Activity::Resource": ["Resource_R1"]},
        "Resource_R1": {"Id": "Resource_R1", "Kind": "Resource", "Activity": "Activity_A1",
                        "ValueType": "AppRole", "Value": "Ro_lead_0003",
                        "DisplayValue": "Lead"},
    }


def test_run_doctor_fails_when_an_approle_assignee_has_no_members() -> None:
    """Rule D (2026-08-19 diagnosis): the blind spot `verify.doctor` cannot close from the graph.
    Membership does not live in the draft at all, so the module (pure, offline) can only see that
    a Resource EXISTS. The TOOL can read the live roster — and an assignee with an empty roster is
    a documented bare-MetadataError publish failure."""
    c = FakeClient(_draft_with_an_approle_assignee())
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert got["isError"] is True
    assert any("ZERO members" in p for p in got["problems"]), got["problems"]
    assert got["checked"]["members"] == 1
    assert got["members_found"] == 0


def test_run_doctor_is_quiet_when_the_roster_is_populated() -> None:
    c = FakeClient(_draft_with_an_approle_assignee())
    c.members[("process", "F1")] = [{"_id": "Ro_lead_0003", "Name": "Lead", "Kind": "AppRole",
                                     "Role": "Member", "Permission": "InitiateItems"}]
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert not any("ZERO members" in p for p in got["problems"]), got["problems"]
    assert got["checked"]["members"] == 1 and got["members_found"] == 1


def test_run_doctor_never_reads_members_for_a_flow_with_no_approle_assignee() -> None:
    """No assignee, no membership requirement to check — the bucket still reports it LOOKED (0),
    and no round trip is spent."""
    class _NoMembers(FakeClient):
        def get_members(self, kind, flow_id):  # type: ignore[override]
            raise AssertionError("run_doctor read the member roster with no AppRole assignee")

    c = _NoMembers(_bare_process_draft())
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert got["checked"]["members"] == 0
    assert got["members_found"] is None


def test_run_doctor_records_a_member_fetch_failure_without_falsely_passing() -> None:
    """A roster this tool could not read is recorded, never silently treated as populated.

    G4: recording the error in its own key was only half of it — the audit went on reporting a
    clean bill of health for a claim it never managed to check. An unreadable roster is UNKNOWN,
    not healthy, so it lands in `unvalidated`, the module's own bucket for exactly this ("never
    silently accepted, never silently flagged"), following the `list_fetch_errors` precedent: the
    fetch failure is recorded AND the claim that depended on it stops counting as validated."""
    class _Broken(FakeClient):
        def get_members(self, kind, flow_id):  # type: ignore[override]
            return Err("http", "member roster fetch failed")

    c = _Broken(_draft_with_an_approle_assignee())
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert got["member_fetch_error"] == "member roster fetch failed"
    assert not any("ZERO members" in p for p in got["problems"]), got["problems"]

    unvalidated = got["unvalidated"]
    assert any("member" in u and "member roster fetch failed" in u for u in unvalidated), \
        f"the un-checkable membership claim landed in NO bucket: {got}"
    assert got["members_found"] is None                    # never counted as populated


def test_run_doctor_leaves_the_membership_claim_out_of_unvalidated_when_it_was_read() -> None:
    """The other half of G4's bucket rule: a roster that WAS read is validated, so nothing about
    membership belongs in `unvalidated` — the entry must mean "could not check", not "checked"."""
    c = FakeClient(_draft_with_an_approle_assignee())
    c.members[("process", "F1")] = [{"_id": "Ro_lead_0003", "Name": "Lead", "Kind": "AppRole",
                                     "Role": "Member", "Permission": "InitiateItems"}]
    got = run_doctor(c, "F1")
    assert isinstance(got, dict)
    assert not any("member" in u for u in got["unvalidated"]), got["unvalidated"]


# ---- apply_layout: the pure validation runs BEFORE the live GET -------------------------------

def test_apply_layout_refuses_an_invalid_span_before_paying_for_the_get() -> None:
    """E3: `apply_exact_layout` validated the spec only AFTER the draft had been fetched, so a
    caller with an off-grid span paid a round trip to be told no. Ordering, not correctness — the
    refusal itself was always right."""
    class _NoRead(FakeClient):
        def get_draft(self, kind, flow_id):  # type: ignore[override]
            raise AssertionError("apply_layout fetched the draft before validating the spec")

    c = _NoRead(_bare_form_draft())
    got = apply_layout(c, "F1", {"S": [[("a", 0, 99)]]})
    assert isinstance(got, Err) and got.kind == "verify"
    assert "6-unit" in got.message
    assert c.puts == 0


# ---- member batch: discover_member_source / apply_member_batch -------------------------------

def test_discover_member_source_finds_the_first_other_flow_with_members() -> None:
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = [{"_id": "F_target"}, {"_id": "F_empty"}, {"_id": "F_source"}]
    c.members[("process", "F_empty")] = []
    c.members[("process", "F_source")] = [{"Role": "Ro_x"}]
    got = discover_member_source(c, "process", exclude_flow_id="F_target")
    assert got == "F_source"


def test_discover_member_source_returns_none_not_err_on_an_empty_app() -> None:
    """A fresh KF_APP with zero flows is a legitimate tenant state (proven live 2026-08-06), not
    a failure — this must be None, never an Err."""
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []
    got = discover_member_source(c, "process", exclude_flow_id="F_target")
    assert got is None


def test_apply_member_batch_reports_a_clear_note_when_nothing_can_be_harvested() -> None:
    """No sibling flow to harvest from AND the account-level AppRole list has nothing scoped to
    this app either (c.app_roles defaults to []) -- the fully-empty case, still reported not
    raised."""
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.harvested == () and rep.applied == () and rep.role_ids == ()
    assert rep.note is not None and "no existing flow" in rep.note
    assert rep.as_tool_result()["isError"] is False, "an empty tenant is not an error state"
    assert c.member_batches == [], "nothing to post must mean nothing gets posted"


# ---- member batch: account-level AppRole fallback (Node L, 2026-08-07) -----------------------
# Proven live: the account-level `/app_role/2/{acct}/list` route DOES list AppRoles (CORRECTING
# the older belief that no such route exists) -- when no sibling flow has members to harvest,
# apply_member_batch now grants the app's OWN AppRoles from that route instead of just reporting
# an empty harvest. Role="DataAdmin", Permission=["InitiateItems"] is the exact grant proven live
# to let the initiator submit their own draft (Permission=[] 200s the grant but the initiator
# still gets refused, 403 KISSFLOW_ERROR_050302).

def test_apply_member_batch_falls_back_to_account_level_app_roles() -> None:
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []  # nothing to auto-discover
    c.app_roles = [
        {"_id": "RoA", "Name": "Admin", "Applications": [{"_id": "App", "Type": "Application"}]},
        {"_id": "RoB", "Name": "User", "Applications": [{"_id": "App", "Type": "Application"}]},
        {"_id": "RoC", "Name": "Other App's Role",
         "Applications": [{"_id": "SomeOtherApp", "Type": "Application"}]},
    ]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.source_flow_id is None
    assert rep.role_ids == ("RoA", "RoB"), "only roles scoped to THIS app (config's app_id)"
    assert rep.harvested == ("Admin", "User")
    assert rep.verified == ("RoA", "RoB") and rep.missing == ()
    assert rep.note is not None and "account level" in rep.note
    assert rep.as_tool_result()["isError"] is False
    assert rep.as_tool_result()["role_ids"] == ["RoA", "RoB"]

    assert len(c.member_batches) == 1
    posted_kind, posted_flow, posted_members = c.member_batches[0]
    assert posted_kind == "process" and posted_flow == "F_target"
    assert posted_members == [
        {"_id": "RoA", "Name": "Admin", "Kind": "AppRole", "Role": "DataAdmin",
         "Permission": ["InitiateItems"]},
        {"_id": "RoB", "Name": "User", "Kind": "AppRole", "Role": "DataAdmin",
         "Permission": ["InitiateItems"]},
    ]


# ---- apply_member_roles: create-then-grant (2026-08-08) -------------------------------------
# The standing blocker on multi-role assignees was the belief that AppRoles are UI-only — no API
# route CREATES one. PROVEN FALSE live 2026-08-08: `POST /app_role/2/{acct}` creates a role scoped
# to KF_APP, and member/batch then binds it (a foreign-app-scoped role is rejected with 00051).
# apply_member_roles now reuses an existing same-name KF_APP role (idempotent) or creates one, then
# grants. `resolved` carries {display_name: a00_role_id} so a build script can remap step->name onto
# step->a00_id for build_workflow.

def test_apply_member_roles_reuses_existing_same_name_role_and_grants() -> None:
    c = FakeClient(_bare_process_draft())
    c.app_roles = [{"_id": "RoExist", "Name": "FDE",
                    "Applications": [{"_id": c._cfg.app_id, "Type": "Application"}]}]
    rep = apply_member_roles(c, "F_target", {"RoForeign": "FDE"})
    assert isinstance(rep, MemberReport)
    assert rep.missing == () and rep.as_tool_result()["isError"] is False
    resolved = rep.as_tool_result()["resolved"]
    assert resolved == {"FDE": "RoExist"}, "reuse the existing KF_APP-scoped FDE, ignore foreign id"
    assert rep.role_ids == ("RoExist",)
    assert len(c.member_batches) == 1
    posted = c.member_batches[0][2]
    assert posted == [{"_id": "RoExist", "Name": "FDE", "Kind": "AppRole",
                       "Role": "DataAdmin", "Permission": ["InitiateItems"]}]
    assert rep.note is not None and "created 0" not in rep.note  # nothing created, reused instead


def test_apply_member_roles_reuses_a_scalar_scoped_role_no_duplicate() -> None:
    """The Cowork bug (#6) end to end: an existing same-name role scoped ONLY by the top-level
    `_application_id` scalar (no `Applications[]` entry) must be REUSED, not duplicated, and it must
    read back verified, not `missing`. Before the scope-filter fix, apply_member_roles never saw
    its own role, created a second one, and reported the grant `missing`."""
    c = FakeClient(_bare_process_draft())
    c.app_roles = [{"_id": "RoScalar", "Name": "Admin", "_application_id": c._cfg.app_id,
                    "Applications": []}]  # scalar-only scope, empty Applications
    before = len(c.app_roles)

    rep = apply_member_roles(c, "F_target", {"RoForeign": "Admin"})
    assert isinstance(rep, MemberReport)
    assert len(c.app_roles) == before, "must REUSE the scalar-scoped role, not create a duplicate"
    assert rep.role_ids == ("RoScalar",)
    assert rep.missing == () and "RoScalar" in rep.verified
    assert rep.as_tool_result()["isError"] is False
    assert rep.note is not None and "created 0" not in rep.note


def test_apply_member_roles_creates_missing_role_scoped_to_app_then_grants() -> None:
    c = FakeClient(_bare_process_draft())
    c.app_roles = []  # nothing exists yet -> both must be created scoped to KF_APP
    rep = apply_member_roles(c, "F_target", {"RoX": "Requester", "RoY": "CoE Lead"})
    assert isinstance(rep, MemberReport)
    assert rep.missing == () and rep.as_tool_result()["isError"] is False
    resolved = rep.as_tool_result()["resolved"]
    assert set(resolved.keys()) == {"Requester", "CoE Lead"}
    new_ids = list(resolved.values())
    assert all(r.startswith("RoNew") for r in new_ids), "fresh ids from the fake create_app_role"
    # the created roles are scoped to KF_APP (so a later member/batch will accept them)
    for rid in new_ids:
        ro = next(r for r in c.app_roles if r["_id"] == rid)
        assert ro["_application_id"] == c._cfg.app_id
    assert rep.note is not None and "created 2" in rep.note
    # exactly one member/batch post with both granted roles
    assert len(c.member_batches) == 1
    posted = {m["Name"]: m["_id"] for m in c.member_batches[0][2]}
    assert posted == resolved



def test_apply_member_batch_account_level_fallback_reports_missing_on_partial_readback() -> None:
    """Output-invariant audit: a role POSTed but absent on read-back lands in `missing`, never
    silently unaccounted for."""
    class Dropping(FakeClient):
        def post_member_batch(self, kind, flow_id, members):  # type: ignore[override]
            self.member_batches.append((kind, flow_id, list(members)))
            self.members[(kind, flow_id)] = list(members)[:1]  # only the first one "lands"
            return {"ok": True}

    c = Dropping(_bare_process_draft())
    c.flows["process"] = []
    c.app_roles = [
        {"_id": "RoA", "Name": "Admin", "Applications": [{"_id": "App", "Type": "Application"}]},
        {"_id": "RoB", "Name": "User", "Applications": [{"_id": "App", "Type": "Application"}]},
    ]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.verified == ("RoA",) and rep.missing == ("RoB",)
    assert rep.as_tool_result()["isError"] is True


def test_apply_member_batch_explicit_source_skips_the_account_level_fallback() -> None:
    """An explicit source_flow_id, even one with zero members, must NOT silently fall through to
    the account-level grant — the caller asked for THAT flow specifically."""
    c = FakeClient(_bare_process_draft())
    c.app_roles = [{"_id": "RoA", "Name": "Admin",
                    "Applications": [{"_id": "App", "Type": "Application"}]}]
    c.members[("process", "F_explicit")] = []
    rep = apply_member_batch(c, "F_target", source_flow_id="F_explicit")
    assert isinstance(rep, MemberReport)
    assert rep.source_flow_id == "F_explicit"
    assert rep.role_ids == () and rep.harvested == ()
    assert c.member_batches == []


def test_apply_member_batch_explicit_source_with_no_members_is_reported_not_raised() -> None:
    c = FakeClient(_bare_process_draft())
    c.members[("process", "F_explicit")] = []
    rep = apply_member_batch(c, "F_target", source_flow_id="F_explicit")
    assert isinstance(rep, MemberReport)
    assert rep.source_flow_id == "F_explicit"
    assert rep.harvested == () and "no AppRole members" in (rep.note or "")


def test_apply_member_batch_harvests_normalizes_and_verifies() -> None:
    c = FakeClient(_bare_process_draft())
    c.members[("process", "F_source")] = [
        {"_id": "m1", "Name": "Front Desk", "Kind": "AppRole", "Role": "Ro_front_001",
         "Permission": "Editable", "_created_at": "2026-01-01"},
        {"_id": "m2", "Name": "Junk"},  # no Role -> must be dropped, not posted
    ]
    rep = apply_member_batch(c, "F_target", source_flow_id="F_source")
    assert isinstance(rep, MemberReport)
    assert rep.harvested == ("Ro_front_001",)
    assert rep.applied == ("Ro_front_001",)
    assert rep.verified == ("Ro_front_001",) and rep.missing == ()
    assert len(c.member_batches) == 1
    posted_kind, posted_flow, posted_members = c.member_batches[0]
    assert posted_kind == "process" and posted_flow == "F_target"
    assert posted_members == [{"_id": "m1", "Name": "Front Desk", "Kind": "AppRole",
                               "Role": "Ro_front_001", "Permission": "Editable"}]
    # role_ids must be populated on the HARVEST path too, not just the account-level fallback:
    # callers (the lifecycle suite among them) read it to pick a step assignee, and which path
    # granted membership depends on whether a sibling flow happens to exist.
    assert rep.role_ids == ("m1",)


# ---- apply_report_members ---------------------------------------------------------------------

def test_apply_report_members_posts_and_reports_unverified_honestly() -> None:
    c = FakeClient(_bare_process_draft())
    members = [{"_id": "m1", "Name": "Lead", "Kind": "AppRole", "Role": "Ro_lead", "Permission": "Member"}]
    got = apply_report_members(c, "F1", "Rep1", members)
    assert isinstance(got, dict)
    assert got["verified"] is None, "no documented read-back route -- must not fake True"
    assert got["isError"] is False
    assert c.report_member_batches == [("F1", "Rep1", members)]


# ---- KfClient._page_draft_url (issue #19) ------------------------------------------------------
# kf_get_flow_schema(flow_kind="page", ...) used to route through the GENERIC _draft_url, which
# emits /metadata/2/{acct}/page/{page_id}/draft -- missing the application/{app_id} segment a page
# draft actually lives under (CLAUDE.md Pages: "GET/PUT /metadata/2/{acct}/application/{app}/
# page/{page_id}/draft"). The correct builder, _page_draft_url, already existed but had no caller
# on the kf_get_flow_schema tool surface. This pins the URL shape directly, offline, no network --
# the seam this ticket names.

def test_page_draft_url_carries_the_application_segment() -> None:
    c = KfClient(DEV)
    url = c._page_draft_url("App_Other", "Page_1")
    assert url == f"{DEV.base}/metadata/2/{DEV.account}/application/App_Other/page/Page_1/draft"


def test_page_draft_url_uses_the_explicit_app_id_never_a_hard_coded_kf_app() -> None:
    """DEV.app_id ('App') stands in for KF_APP here -- a page in ANY OTHER app must produce a URL
    carrying THAT app's id, never silently substituting the configured default (the generalisation
    constraint, spec #38: any app, not one)."""
    c = KfClient(DEV)
    url = c._page_draft_url("SomeOtherApp", "Page_1")
    assert "SomeOtherApp" in url
    assert f"/application/{DEV.app_id}/" not in url, "must not fall back to the configured KF_APP"


def test_get_page_draft_calls_the_page_draft_url_not_the_generic_one() -> None:
    class _RouteRecordingClient(KfClient):
        def __init__(self) -> None:
            super().__init__(DEV)
            self.urls: list[str] = []

        def _json(self, method: str, url: str, data: Any = None) -> Any:  # type: ignore[override]
            self.urls.append(url)
            return {"Root": "Pg1"}

    c = _RouteRecordingClient()
    got = c.get_page_draft("App_Other", "Page_1")
    assert got == {"Root": "Pg1"}
    assert c.urls == [f"{DEV.base}/metadata/2/{DEV.account}/application/App_Other/page/Page_1/draft"]


# ---- create_application_verified / delete_anything --------------------------------------------

def test_create_application_verified_happy_path() -> None:
    c = FakeClient(_bare_process_draft())
    got = create_application_verified(c, "Sample App")
    assert isinstance(got, dict)
    assert got["verified"] is True and got["app_id"] is not None
    assert got["app_id"] in c.applications


def test_delete_anything_page_requires_app_id() -> None:
    c = FakeClient(_bare_process_draft())
    got = delete_anything(c, "page", "Page_1", app_id=None)
    assert got["isError"] is True and "app_id" in got["error"]


def test_delete_anything_page_verifies_via_list_route() -> None:
    c = FakeClient(_bare_process_draft())
    c.pages["App_1"] = {"Page_1": {"_id": "Page_1", "Name": "X"}}
    got = delete_anything(c, "page", "Page_1", app_id="App_1")
    assert got["deleted"] is True and got["verified"] is True and got["isError"] is False
    assert "Page_1" not in c.pages["App_1"]


def test_delete_anything_application_archives_first_then_verifies() -> None:
    c = FakeClient(_bare_process_draft())
    aid = c.create_application("Throwaway")
    got = delete_anything(c, "application", aid)
    assert got["deleted"] is True and got["verified"] is True
    assert aid in c.archived_apps
    assert aid not in c.applications


def test_delete_anything_process_archives_and_deletes() -> None:
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = [{"_id": "F1"}]
    got = delete_anything(c, "process", "F1")
    assert got["deleted"] is True and got["verified"] is True
    assert c.flows["process"] == []


# ---- KfClient.list_app_roles / get_app_role (Node L, 2026-08-07) ------------------------------
# Account-level AppRole listing, proven live: 356 AppRoles in the probe tenant, 2 scoped to the
# app under test. These exercise the REAL KfClient methods (pagination + the Applications-dict
# filter), with only `_json` stubbed -- the same pattern test_dataplane.py's _RouteAwareTransport
# uses to pin LiveDataPlane's real URL construction without a socket.

class _AppRoleRouteClient(KfClient):
    """`_json` stubbed to serve canned account-level AppRole pages, so list_app_roles's real
    pagination/filtering logic runs for real, offline."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        super().__init__(DEV)
        self.pages = pages
        self.urls: list[str] = []

    def _json(self, method: str, url: str, data: Any = None) -> Any:  # type: ignore[override]
        self.urls.append(url)
        if method == "GET" and "/app_role/2/" in url and "/list?page_number=" in url:
            n = int(url.split("page_number=")[1].split("&")[0])
            idx = n - 1
            return self.pages[idx] if 0 <= idx < len(self.pages) else []
        if method == "GET" and url == f"{DEV.base}/app_role/2/{DEV.account}/Ro_X":
            return {"_id": "Ro_X", "Name": "X", "Members": [{"_id": "U1"}]}
        return Err("http", f"unexpected {method} {url}")


def test_list_app_roles_paginates_until_a_short_page() -> None:
    page1 = [{"_id": f"Ro{i}", "Name": f"R{i}", "Applications": []} for i in range(100)]
    page2 = [{"_id": "Ro100", "Name": "R100", "Applications": []}]
    c = _AppRoleRouteClient([page1, page2])
    got = c.list_app_roles(None)
    assert isinstance(got, list) and len(got) == 101
    assert c.urls == [
        f"{DEV.base}/app_role/2/{DEV.account}/list?page_number=1&page_size=100",
        f"{DEV.base}/app_role/2/{DEV.account}/list?page_number=2&page_size=100",
    ]


def test_list_app_roles_stops_without_a_second_fetch_when_first_page_is_short() -> None:
    c = _AppRoleRouteClient([[{"_id": "Ro1", "Name": "Only", "Applications": []}]])
    got = c.list_app_roles(None)
    assert isinstance(got, list) and len(got) == 1
    assert c.urls == [f"{DEV.base}/app_role/2/{DEV.account}/list?page_number=1&page_size=100"], \
        "a short first page must never trigger a second fetch"


def test_list_app_roles_empty_first_page_returns_empty_list() -> None:
    c = _AppRoleRouteClient([[]])
    got = c.list_app_roles(None)
    assert got == []


def test_list_app_roles_filters_on_applications_dict_id_not_bare_string() -> None:
    """`Applications` is a list of {"_id":..., "Type":"Application"} DICTS, not bare id strings —
    proven live 2026-08-07 (an earlier `app_id in record["Applications"]` filter matched zero
    roles for exactly this reason)."""
    roles = [
        {"_id": "RoA", "Name": "A", "Applications": [{"_id": "App1", "Type": "Application"}]},
        {"_id": "RoB", "Name": "B", "Applications": [{"_id": "App2", "Type": "Application"}]},
        {"_id": "RoC", "Name": "C", "Applications": []},
    ]
    c = _AppRoleRouteClient([roles])
    got = c.list_app_roles("App1")
    assert [r["_id"] for r in got] == ["RoA"]


def test_list_app_roles_matches_on_top_level_application_id_scalar() -> None:
    """A role freshly created via create_app_role (POST with `_application_id`) may carry the
    top-level `_application_id` scalar but an EMPTY `Applications[]`. The scope filter must still
    match it — else apply_member_roles never sees its own just-created role, creates a DUPLICATE on
    re-run, and reads the grant back as falsely `missing` (Cowork bug report 2026-08-13)."""
    roles = [
        {"_id": "RoScalar", "Name": "Admin", "_application_id": "App1", "Applications": []},
        {"_id": "RoList", "Name": "B", "Applications": [{"_id": "App1", "Type": "Application"}]},
        {"_id": "RoOther", "Name": "C", "_application_id": "App2", "Applications": []},
    ]
    c = _AppRoleRouteClient([roles])
    got = c.list_app_roles("App1")
    assert sorted(r["_id"] for r in got) == ["RoList", "RoScalar"]


def test_list_app_roles_propagates_transport_err() -> None:
    class _Failing(KfClient):
        def __init__(self) -> None:
            super().__init__(DEV)

        def _json(self, method: str, url: str, data: Any = None) -> Any:  # type: ignore[override]
            return Err("http", "boom")

    got = _Failing().list_app_roles(None)
    assert isinstance(got, Err)


def test_get_app_role_fetches_role_detail_by_id() -> None:
    c = _AppRoleRouteClient([[]])
    got = c.get_app_role("Ro_X")
    assert isinstance(got, dict) and got["Name"] == "X" and got["Members"] == [{"_id": "U1"}]


# ---- apply_word_list (#13) --------------------------------------------------------------------

def test_apply_word_list_creates_sets_and_verifies() -> None:
    from kfforge.client import ListReport, apply_word_list

    c = FakeClient(_bare_form_draft())
    rep = apply_word_list(c, "Priorities", ["High", "Medium", "Low"])
    assert isinstance(rep, ListReport)
    assert rep.created is True
    assert rep.verified_items == ("High", "Medium", "Low") and rep.missing_items == ()
    assert rep.as_tool_result()["isError"] is False


def test_apply_word_list_reuses_existing_by_name_and_replaces_items() -> None:
    """REPLACE semantics (live-proven 2026-08-12): a second call with a changed value set
    replaces the array outright — no duplicate list, no stale leftovers."""
    from kfforge.client import ListReport, apply_word_list

    c = FakeClient(_bare_form_draft())
    first = apply_word_list(c, "Priorities", ["High", "Low"])
    assert isinstance(first, ListReport)
    rep = apply_word_list(c, "Priorities", ["Critical", "High", "Low"])
    assert isinstance(rep, ListReport)
    assert rep.created is False, "reused by name, never a second list"
    assert rep.list_id == first.list_id
    assert c.list_items[rep.list_id] == ["Critical", "High", "Low"]


def test_apply_word_list_missing_value_lands_in_missing_bucket() -> None:
    """A requested value absent on read-back is reported missing, never silently (the same
    silent-discard class the Select fill rule already has)."""
    from kfforge.client import ListReport, apply_word_list

    c = FakeClient(_bare_form_draft())
    c.drop_list_values = {"Ghost"}
    rep = apply_word_list(c, "Priorities", ["High", "Ghost"])
    assert isinstance(rep, ListReport)
    assert rep.verified_items == ("High",)
    assert rep.missing_items == ("Ghost",)
    assert rep.as_tool_result()["isError"] is True


def test_apply_section_style_root_chain_verified() -> None:
    """#11: root_style + hint_text_position land on the ROOT Model's chain and the read-back
    audits them as the '<root>' bucket."""
    c = FakeClient(_bare_form_draft())
    rep = apply_section_style(
        c, "F1", {},
        root_style={"Form.Field.Color": "Color.Primary.500",
                    "Form.Bg.Color": {"ref": "Color.Transparent"}},
        hint_text_position="Icon",
    )
    assert isinstance(rep, StyleReport)
    assert rep.verified == ("<root>",) and rep.missing == ()
    model = c.draft["M1"]
    app = c.draft[model["Model::Appearance"][0]]
    style = c.draft[app["Appearance::Style"][0]]
    assert app["HintTextPosition"] == "Icon"
    assert style["Value"]["Form.Field.Color"] == {"ref": "Color.Primary.500"}


# ---- create_process / create_flow_any — from_template (issue #59) -----------------------------

class _CreateProcessClient(FakeClient):
    """FakeClient with create_flow stubbed — create_process/create_flow_any both call it before
    touching the draft at all. A single fixed draft (like FakeClient's own get_draft) is enough
    since these tests only ever create one flow per client instance."""

    def __init__(self) -> None:
        super().__init__(_bare_process_draft())

    def create_flow(self, kind, name):  # type: ignore[override]
        return "F1"


def test_create_process_from_template_default_seeds_the_identity_shell() -> None:
    c = _CreateProcessClient()
    rep = create_process(c, "Expense Approval", ("Draft",), [])
    assert isinstance(rep, ApplyReport)
    assert rep.as_tool_result()["isError"] is False

    m = c.draft["M1"]
    assert len(m.get("Model::Field", [])) == 28, "identity shell fields must be on the draft"
    pd = c.draft[m["RootProcessDef"]]
    acts = [c.draft[a] for a in pd["ProcessDef::Activity"]]
    assert [a["NodeType"] for a in acts] == ["StartEvent", "UserTask", "EndEvent"]
    assert acts[1]["Name"] == "Manager Approve"


def test_create_process_from_template_false_yields_the_bare_scaffold() -> None:
    c = _CreateProcessClient()
    rep = create_process(c, "Expense Approval", ("Review",), [], from_template=False)
    assert isinstance(rep, ApplyReport)

    m = c.draft["M1"]
    assert m.get("Model::Field", []) == [], "the bare scaffold carries no fields"
    pd = c.draft[m["RootProcessDef"]]
    acts = [c.draft[a] for a in pd["ProcessDef::Activity"]]
    assert [a["Name"] for a in acts] == ["Start", "Review", "Completed"]


def test_create_flow_any_process_from_template_default() -> None:
    c = _CreateProcessClient()
    rep = create_flow_any(c, "process", "Expense Approval")
    assert rep.flow_id == "F1"
    m = c.draft["M1"]
    assert len(m.get("Model::Field", [])) == 28


def test_create_flow_any_process_from_template_false() -> None:
    c = _CreateProcessClient()
    rep = create_flow_any(c, "process", "Expense Approval", extra={"from_template": False, "steps": ("Review",)})
    assert rep.flow_id == "F1"
    m = c.draft["M1"]
    assert m.get("Model::Field", []) == []
    pd = c.draft[m["RootProcessDef"]]
    acts = [c.draft[a] for a in pd["ProcessDef::Activity"]]
    assert [a["Name"] for a in acts] == ["Start", "Review", "Completed"]


# ---- apply_dataset_records: name->id resolution + per-record update/delete (#58) --------------
# The record route 404s FieldNotFound on a NAME key, so create/update resolve names to ids off the
# dataform's live draft (the synthetic system "Name" key passes through). update/delete are the
# per-record ?_id= PUT/DELETE routes (residuals_r1); delete's body must carry {"Name": ...}.

def _dataset_draft() -> dict:
    """Minimal dataform draft: a root Model with two named fields — the name->id source."""
    return {
        "Root": "M1",
        "M1": {"Id": "M1", "Kind": "Model", "FlowType": "Dataset", "Model::Field": ["Field_a", "Field_b"]},
        "Field_a": {"Id": "Field_a", "Kind": "Field", "Name": "Item Name", "Model": "M1"},
        "Field_b": {"Id": "Field_b", "Kind": "Field", "Name": "Category", "Model": "M1"},
    }


class _DatasetRecordClient:
    """Duck-typed stand-in exercising apply_dataset_records' real resolution + op routing offline.
    Records every raw call so a test can assert what actually hit the (mocked) client."""

    def __init__(self, draft: dict | None = None) -> None:
        self._draft = draft if draft is not None else _dataset_draft()
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.updated: list[tuple[str, str, dict[str, Any]]] = []
        self.deleted: list[tuple[str, str, str]] = []
        self.listed = 0

    def get_draft(self, kind, flow_id):
        return self._draft

    def create_dataset_record(self, flow_id, record):
        self.created.append((flow_id, record))
        return {"_id": "Rec_new", **record}

    def update_dataset_record(self, flow_id, record_id, record):
        self.updated.append((flow_id, record_id, record))
        return {"_id": record_id, **record}

    def delete_dataset_record(self, flow_id, record_id, name):
        self.deleted.append((flow_id, record_id, name))
        return {"_id": record_id, "deleted": True}

    def list_dataset_records(self, flow_id):
        self.listed += 1
        return {"Columns": [{"Id": "Name"}], "Data": [{"_id": "Rec_1"}, {"_id": "Rec_2"}]}


def test_dataset_create_resolves_field_names_to_ids() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(
        c, "Flow_1", "create",
        record={"Name": "Widget A", "Item Name": "Widget A", "Category": "Tools"},
    )
    assert got["isError"] is False and got["created"] == 1
    # the record that actually reached the client is keyed by ids, Name passed through, no name key
    _, sent = c.created[0]
    assert sent == {"Name": "Widget A", "Field_a": "Widget A", "Field_b": "Tools"}
    assert "Item Name" not in sent and "Category" not in sent


def test_dataset_create_accepts_field_ids_too() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(
        c, "Flow_1", "create",
        record={"Name": "K1", "Field_a": "v", "Category": "Tools"},  # mixed id + name
    )
    assert got["created"] == 1
    _, sent = c.created[0]
    assert sent == {"Name": "K1", "Field_a": "v", "Field_b": "Tools"}


def test_dataset_unknown_field_name_fails_loud() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(
        c, "Flow_1", "create", record={"Name": "K", "Nope": "x"},
    )
    assert isinstance(got, Err)
    assert "Nope" in got.message and "Item Name" in got.message  # lists available names
    assert c.created == []  # nothing written


def test_dataset_update_by_id_hits_put_and_resolves() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(
        c, "Flow_1", "update", record={"Category": "New"}, record_id="Rec_9",
    )
    assert got["isError"] is False and got["updated"] == 1 and got["record_id"] == "Rec_9"
    assert c.updated == [("Flow_1", "Rec_9", {"Field_b": "New"})]


def test_dataset_update_requires_record_id() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(c, "Flow_1", "update", record={"Category": "New"})
    assert isinstance(got, Err) and "record_id" in got.message
    assert c.updated == []


def test_dataset_delete_sends_name_body() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(
        c, "Flow_1", "delete", record={"Name": "K1"}, record_id="Rec_9",
    )
    assert got["isError"] is False and got["deleted"] == 1
    assert c.deleted == [("Flow_1", "Rec_9", "K1")]


def test_dataset_delete_requires_name_body() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(c, "Flow_1", "delete", record_id="Rec_9")
    assert isinstance(got, Err) and "Name" in got.message
    assert c.deleted == []


def test_dataset_unknown_op_fails_loud() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(c, "Flow_1", "purge")
    assert isinstance(got, Err) and "purge" in got.message


def test_dataset_list_counts_rows() -> None:
    c = _DatasetRecordClient()
    got = apply_dataset_records(c, "Flow_1", "list")
    assert got["isError"] is False and got["listed"] == 2 and len(got["records"]) == 2


def test_dataset_update_delete_build_id_scoped_routes() -> None:
    """The REAL KfClient builds the per-record ?_id= PUT/DELETE URLs, delete carrying the Name body."""
    class _Rec(KfClient):
        def __init__(self) -> None:
            super().__init__(DEV)
            self.calls: list[tuple[str, str, Any]] = []

        def _json(self, method: str, url: str, data: Any = None):  # type: ignore[override]
            self.calls.append((method, url, data))
            return {"_id": "Rec_9"}

    c = _Rec()
    c.update_dataset_record("Flow_1", "Rec_9", {"Field_b": "New"})
    c.delete_dataset_record("Flow_1", "Rec_9", "K1")
    put_m, put_url, put_body = c.calls[0]
    del_m, del_url, del_body = c.calls[1]
    assert put_m == "PUT" and "/dataset/2/Acc/Flow_1?" in put_url and "_id=Rec_9" in put_url
    assert put_body == {"Field_b": "New"}
    assert del_m == "DELETE" and "_id=Rec_9" in del_url and del_body == {"Name": "K1"}


def test_dataset_create_draft_read_failure_fails_loud() -> None:
    class _NoDraft(_DatasetRecordClient):
        def get_draft(self, kind, flow_id):
            return Err("http", "draft 500", status=500)

    c = _NoDraft()
    got = apply_dataset_records(c, "Flow_1", "create", record={"Name": "K", "Item Name": "x"})
    assert isinstance(got, Err) and "draft read failed" in got.message
    assert c.created == []


# =====================================================================================
# Bundle B — the live orchestration layer. Four findings, same FakeClient idiom as above:
#   B1 the field-event trigger is DERIVED from the source field's type, never taken on faith
#   B2 an ignored field change stops being counted as a success
#   B3 a destructive tool reports its collateral
#   B4 the field lifecycle (delete / rename / required) is reachable at all
# =====================================================================================

def _form_with(*specs) -> dict:
    return _apply_changes(_bare_form_draft(), list(specs))


def _events_of(draft: dict) -> list[dict]:
    return [v for v in draft.values() if isinstance(v, dict) and v.get("Kind") == "Event"]


# ---- B1: derive the field-event trigger -------------------------------------------------------

def test_apply_field_events_derives_the_trigger_from_the_source_field_type() -> None:
    """CLAUDE.md Field events: a Select source fires onClick. The caller omits the trigger and the
    engine reads it off the live draft — the whole point, since a wrong one never fires and no
    later check can see it."""
    c = FakeClient(_form_with(FieldSpec(name="Route", type=FieldType.SELECT,
                                        referred_list="List_Sample01")))
    rep = apply_field_events(c, "F1", {"Route": [(None, "kf.x();")]})
    assert isinstance(rep, EventReport)
    assert rep.verified == ("Route",) and rep.missing == ()
    assert [e["Trigger"] for e in _events_of(c.draft)] == ["onClick"]
    assert rep.derived == ("Route",)
    assert rep.triggers == ("Route (Select) -> onClick",)
    assert rep.unverified == (), "Select -> onClick is live-confirmed, not inferred"


@pytest.mark.parametrize("ftype,trigger", [
    (FieldType.TEXT, "onChange"),
    (FieldType.TEXTAREA, "onChange"),
    (FieldType.DATE, "onSelect"),
    (FieldType.NUMBER, "onSelect"),
    (FieldType.SELECT, "onClick"),
])
def test_apply_field_events_derives_every_live_confirmed_trigger(ftype, trigger) -> None:
    # a Select must name the list its options live in (graph.apply_changes refuses a bare one);
    # every other type here takes no list at all
    listed = {"referred_list": "List_Sample01"} if ftype is FieldType.SELECT else {}
    c = FakeClient(_form_with(FieldSpec(name="Src", type=ftype, **listed)))
    rep = apply_field_events(c, "F1", {"Src": [(None, "kf.x();")]})
    assert isinstance(rep, EventReport)
    assert [e["Trigger"] for e in _events_of(c.draft)] == [trigger]
    assert rep.unverified == ()


def test_apply_field_events_refuses_a_trigger_that_disagrees_with_the_source_type() -> None:
    """The F-finding itself: `onChange` on a Select writes fine, publishes fine, never fires."""
    c = FakeClient(_form_with(FieldSpec(name="Route", type=FieldType.SELECT,
                                        referred_list="List_Sample01")))
    got = apply_field_events(c, "F1", {"Route": [("onChange", "kf.x();")]})
    assert isinstance(got, Err) and got.kind == "verify"
    assert "onClick" in got.message and "onChange" in got.message, "must name BOTH triggers"
    assert c.puts == 0, "a wrong trigger must never reach the network"


def test_apply_field_events_accepts_an_explicit_trigger_that_agrees() -> None:
    c = FakeClient(_form_with(FieldSpec(name="Note", type=FieldType.TEXT)))
    rep = apply_field_events(c, "F1", {"Note": [("onChange", "kf.x();")]})
    assert isinstance(rep, EventReport)
    assert rep.verified == ("Note",) and rep.derived == (), "the caller stated it, we agreed"
    assert rep.triggers == ("Note (Text) -> onChange",)


def test_apply_field_events_refuses_an_attachment_source_outright() -> None:
    c = FakeClient(_form_with(FieldSpec(name="Doc", type=FieldType.ATTACHMENT)))
    got = apply_field_events(c, "F1", {"Doc": [(None, "kf.x();")]})
    assert isinstance(got, Err) and got.kind == "verify"
    assert "never carry an event" in got.message
    assert c.puts == 0


@pytest.mark.parametrize("wire_type", ["Attachment", "Image", "Signature", "SequenceNumber",
                                       "Geolocation"])
def test_apply_field_events_refuses_every_event_less_field_type(wire_type: str) -> None:
    """CLAUDE.md Field events names six types with no Event tab at all. Five have a captured (or,
    for Geolocation, unambiguous) wire string; a stated trigger does not rescue any of them."""
    draft = _form_with(FieldSpec(name="X", type=FieldType.TEXT))
    fid = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "X")
    draft[fid]["Type"] = wire_type
    c = FakeClient(draft)
    got = apply_field_events(c, "F1", {"X": [("onChange", "kf.x();")]})
    assert isinstance(got, Err) and got.kind == "verify" and wire_type in got.message
    assert c.puts == 0


@pytest.mark.parametrize("ftype,trigger", [(FieldType.USER, "onSelect"),
                                           (FieldType.BOOLEAN, "onClick")])
def test_apply_field_events_carries_family_inferred_uncertainty_into_the_report(ftype, trigger) -> None:
    """User->onSelect and Boolean->onClick are family-inferred and UNVERIFIED live (CLAUDE.md).
    They are still derived — refusing would block a real capability — but the doubt travels in
    the payload instead of being silently asserted as fact."""
    c = FakeClient(_form_with(FieldSpec(name="Who", type=ftype)))
    rep = apply_field_events(c, "F1", {"Who": [(None, "kf.x();")]})
    assert isinstance(rep, EventReport)
    assert [e["Trigger"] for e in _events_of(c.draft)] == [trigger]
    assert len(rep.unverified) == 1
    assert "family-inferred" in rep.unverified[0] and trigger in rep.unverified[0]
    assert rep.as_tool_result()["isError"] is False, "uncertainty is not failure"


def test_apply_field_events_refuses_to_guess_a_trigger_for_a_type_it_has_no_mapping_for() -> None:
    """A real platform type outside `types.trigger_for` (Currency, Rating, ...). Nothing captured
    means nothing to derive — refuse rather than invent a wire value."""
    draft = _form_with(FieldSpec(name="Cost", type=FieldType.NUMBER))
    fid = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Cost")
    draft[fid]["Type"] = "Currency"
    c = FakeClient(draft)
    got = apply_field_events(c, "F1", {"Cost": [(None, "kf.x();")]})
    assert isinstance(got, Err) and got.kind == "verify" and "will not guess" in got.message
    assert c.puts == 0


def test_apply_field_events_takes_a_stated_trigger_for_an_unmapped_type_but_flags_it() -> None:
    draft = _form_with(FieldSpec(name="Cost", type=FieldType.NUMBER))
    fid = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Cost")
    draft[fid]["Type"] = "Currency"
    c = FakeClient(draft)
    rep = apply_field_events(c, "F1", {"Cost": [("onSelect", "kf.x();")]})
    assert isinstance(rep, EventReport)
    assert [e["Trigger"] for e in _events_of(c.draft)] == ["onSelect"]
    assert len(rep.unverified) == 1 and "outside" in rep.unverified[0]


def test_apply_field_events_empty_string_trigger_means_derive_it() -> None:
    """A wire caller that cannot send `null` sends `""`. Both mean the same thing."""
    c = FakeClient(_form_with(FieldSpec(name="Route", type=FieldType.SELECT,
                                        referred_list="List_Sample01")))
    rep = apply_field_events(c, "F1", {"Route": [("", "kf.x();")]})
    assert isinstance(rep, EventReport) and rep.derived == ("Route",)
    assert [e["Trigger"] for e in _events_of(c.draft)] == ["onClick"]


# ---- B2: an ignored change is not a success ---------------------------------------------------

def test_apply_fields_reports_an_ignored_type_change_instead_of_verifying_it() -> None:
    """F2, proven: apply_changes only CREATES. Asking for a different type on an existing NAME is
    a silent no-op that used to be counted under `skipped` AND `verified` at once."""
    c = FakeClient(_bare_form_draft())
    apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)])
    assert c.puts == 1

    rep = apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.NUMBER)])
    assert isinstance(rep, ApplyReport)
    assert len(rep.changed_ignored) == 1
    assert "alpha" in rep.changed_ignored[0]
    assert "'Number'" in rep.changed_ignored[0] and "'Text'" in rep.changed_ignored[0]
    assert rep.skipped == () and rep.verified == (), "the record belongs in ONE bucket, the new one"
    assert rep.added == () and rep.missing == ()
    assert rep.as_tool_result()["isError"] is True
    assert c.puts == 1, "nothing was written — that is exactly the problem being reported"
    assert c.draft[next(k for k, v in c.draft.items() if isinstance(v, dict)
                        and v.get("Name") == "alpha")]["Type"] == "Text"


def test_apply_fields_ignored_required_change_names_the_tool_that_can_do_it() -> None:
    c = FakeClient(_bare_form_draft())
    apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT, required=False)])
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT, required=True)])
    assert isinstance(rep, ApplyReport)
    assert len(rep.changed_ignored) == 1 and "Required" in rep.changed_ignored[0]
    assert rep.remediation == ("forge_set_required",)


def test_apply_fields_ignored_type_change_names_the_delete_and_recreate_route() -> None:
    c = FakeClient(_bare_form_draft())
    apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)])
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.NUMBER)])
    assert isinstance(rep, ApplyReport)
    assert rep.remediation == ("forge_delete_fields", "forge_apply_fields")


def test_apply_fields_an_identical_respec_is_still_a_plain_skip() -> None:
    """The idempotent re-run must not regress into a false alarm."""
    c = FakeClient(_bare_form_draft())
    spec = [FieldSpec(name="alpha", type=FieldType.TEXT, required=True)]
    apply_fields(c, "form", "F1", spec)
    rep = apply_fields(c, "form", "F1", spec)
    assert isinstance(rep, ApplyReport)
    assert rep.changed_ignored == () and rep.skipped == ("alpha",) and rep.verified == ("alpha",)
    assert rep.as_tool_result()["isError"] is False


def test_apply_fields_compares_only_options_the_caller_actually_named() -> None:
    """A Number field carries engine-written defaults (Decimalpoint, DefaultValue) no FieldSpec
    ever mentions — a blind key diff would flag every one of them as an ignored change."""
    c = FakeClient(_bare_form_draft())
    spec = [FieldSpec(name="score", type=FieldType.NUMBER)]
    apply_fields(c, "form", "F1", spec)
    rep = apply_fields(c, "form", "F1", spec)
    assert isinstance(rep, ApplyReport) and rep.changed_ignored == ()

    rep2 = apply_fields(c, "form", "F1",
                        [FieldSpec(name="score", type=FieldType.NUMBER,
                                   options={"DefaultValue": "7"})])
    assert isinstance(rep2, ApplyReport)
    assert len(rep2.changed_ignored) == 1 and "DefaultValue" in rep2.changed_ignored[0]


def test_apply_fields_never_publishes_when_a_change_was_ignored() -> None:
    c = FakeClient(_bare_form_draft())
    apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)])
    rep = apply_fields(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.NUMBER)],
                       publish=True)
    assert isinstance(rep, ApplyReport) and rep.published is False
    assert c.published is False, "never publish a draft that failed its own audit"


def test_apply_fields_and_layout_reports_an_ignored_change_too() -> None:
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)],
                            groups=[("G", ["alpha"])])
    rep = apply_fields_and_layout(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.NUMBER)],
                                  groups=[("G", ["alpha"])])
    assert isinstance(rep, ApplyReport)
    assert len(rep.changed_ignored) == 1 and rep.verified == () and rep.skipped == ()
    assert rep.as_tool_result()["isError"] is True


def test_apply_fields_full_reports_an_ignored_change_too() -> None:
    c = FakeClient(_bare_form_draft())
    apply_fields_full(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.TEXT)])
    rep = apply_fields_full(c, "form", "F1", [FieldSpec(name="alpha", type=FieldType.NUMBER)])
    assert not isinstance(rep, Err)
    assert len(rep.changed_ignored) == 1 and rep.verified == () and rep.skipped == ()
    assert rep.as_tool_result()["isError"] is True
    assert rep.as_tool_result()["remediation"] == ["forge_delete_fields", "forge_apply_fields"]


# ---- B3: destructive tools report their collateral --------------------------------------------

def _synthetic_with_permissions() -> tuple[dict, int]:
    from synthetic import OWNERS, synthetic_process_draft

    from kfforge.graph import progressive_matrix, set_step_permissions
    draft = synthetic_process_draft()
    draft = set_step_permissions(draft, progressive_matrix(draft, OWNERS))
    n = len([v for v in draft.values() if isinstance(v, dict) and v.get("Kind") == "Permission"])
    assert n > 0, "fixture must actually carry a live visibility matrix"
    return draft, n


def test_apply_workflow_reports_the_permission_matrix_it_destroyed() -> None:
    """A4: build_workflow DELETES every Permission (CLAUDE.md Workflow, Visibility; measured live
    234 -> 0) and the report used to say nothing at all about it."""
    draft, before = _synthetic_with_permissions()
    c = FakeClient(draft)
    rep = apply_workflow(c, "F1", [("Draft", None), ("Review", None)])
    assert isinstance(rep, WorkflowReport)
    assert rep.permissions_deleted == before
    assert any("Permission node(s) deleted" in s for s in rep.collateral)
    assert rep.remediation == ("forge_set_visibility",)
    assert rep.as_tool_result()["permissions_deleted"] == before
    assert rep.as_tool_result()["isError"] is False, "documented destruction is not a failure"


def test_apply_workflow_counts_the_damage_on_the_read_back_not_on_the_plan() -> None:
    """THE RULE: what we hoped to write proves nothing. A client whose PUT is accepted but never
    lands must NOT report a wiped matrix, because the live matrix is still there."""
    draft, _before = _synthetic_with_permissions()

    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            return new                                    # accepted, self.draft NOT updated

    c = Dropping(draft)
    rep = apply_workflow(c, "F1", [("Draft", None)])
    assert isinstance(rep, WorkflowReport)
    assert rep.permissions_deleted == 0 and rep.collateral == ()


def test_apply_workflow_reports_a_relocated_sequence_number_step_stamp() -> None:
    """#18: the Step stamp is a SCALAR activity ref the list-only sweep never touches. A rebuild
    that drops its step silently repoints it at StartEvent — correct, and previously invisible."""
    from synthetic import synthetic_process_draft

    from kfforge.graph import add_sequence_number
    draft = synthetic_process_draft()
    step = next(v["Name"] for v in draft.values()
                if isinstance(v, dict) and v.get("Kind") == "Activity"
                and v.get("NodeType") == "UserTask")
    section = next(v["Name"] for v in draft.values()
                   if isinstance(v, dict) and v.get("Kind") == "Column"
                   and v.get("Type") == "Section" and v.get("Name"))
    draft = add_sequence_number(draft, "Case ID", section, "CS-", "0001", step)

    c = FakeClient(draft)
    rep = apply_workflow(c, "F1", [("Totally Different Step", None)])
    assert isinstance(rep, WorkflowReport)
    assert any("Case ID" in s and "Step stamp relocated" in s for s in rep.collateral)
    assert "forge_add_sequence_number" in rep.remediation


def test_apply_workflow_reports_no_collateral_on_a_flow_that_had_none() -> None:
    c = FakeClient(_bare_process_draft())
    rep = apply_workflow(c, "F1", [("Draft", "Role_A")])
    assert isinstance(rep, WorkflowReport)
    assert rep.permissions_deleted == 0 and rep.collateral == () and rep.remediation == ()


def test_apply_step_permissions_reports_the_pairs_the_rebuild_dropped() -> None:
    """set_step_permissions DELETES every Permission before it writes. A pair that was live and is
    not in the new matrix used to be absent from every counted bucket (doctrine 2)."""
    from synthetic import OWNERS, synthetic_process_draft

    from kfforge.graph import progressive_matrix
    draft = synthetic_process_draft()
    full = progressive_matrix(draft, OWNERS)
    c = FakeClient(draft)

    first = apply_step_permissions(c, "F1", full)
    assert isinstance(first, ApplyReport) and first.collateral == ()

    dropped_activity = sorted(next(iter(full.values())))[0]
    thinner = {sec: {a: v for a, v in row.items() if a != dropped_activity}
               for sec, row in full.items()}
    second = apply_step_permissions(c, "F1", thinner)
    assert isinstance(second, ApplyReport)
    assert second.collateral, "every dropped pair must be named, not silently deleted"
    assert all("deleted Permission" in s for s in second.collateral)
    assert all(dropped_activity in s for s in second.collateral)
    assert second.remediation == ("forge_set_visibility",)
    assert second.as_tool_result()["isError"] is False


def test_apply_layout_reports_the_fields_it_retiled() -> None:
    """apply_exact_layout rebuilds a whole section's rows, so a field the PARTIAL spec does not
    name is MOVED into a trailing row. Nothing is lost, but the form the user sees changed."""
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(
        c, "form", "F1",
        [FieldSpec(name=n, type=FieldType.TEXT) for n in ("a", "b", "c")],
        groups=[("G", ["a", "b", "c"])])

    rep = apply_layout(c, "F1", {"G": [[("a", 0, 6)]]}, kind="form")
    assert isinstance(rep, ApplyReport)
    assert len(rep.collateral) == 2
    assert all("re-tiled into a trailing row" in s for s in rep.collateral)
    assert any("'b'" in s for s in rep.collateral) and any("'c'" in s for s in rep.collateral)
    assert rep.remediation == ("forge_apply_layout",)
    assert rep.as_tool_result()["isError"] is False


def test_apply_layout_reports_no_collateral_when_the_spec_names_every_field() -> None:
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(c, "form", "F1",
                            [FieldSpec(name=n, type=FieldType.TEXT) for n in ("a", "b")],
                            groups=[("G", ["a", "b"])])
    rep = apply_layout(c, "F1", {"G": [[("a", 0, 3), ("b", 3, 6)]]}, kind="form")
    assert isinstance(rep, ApplyReport) and rep.collateral == () and rep.remediation == ()


# ---- B4: the field lifecycle ------------------------------------------------------------------

def test_delete_fields_audits_ABSENCE_not_presence() -> None:
    """The delete audit is inverted: success is the name being GONE on read-back."""
    c = FakeClient(_form_with(FieldSpec(name="keep", type=FieldType.TEXT),
                              FieldSpec(name="drop", type=FieldType.TEXT)))
    rep = delete_fields(c, "F1", ("drop",), kind="form")
    assert isinstance(rep, DeleteFieldsReport)
    assert rep.deleted == ("drop",) and rep.surviving == ()
    assert rep.as_tool_result()["isError"] is False
    live = {v.get("Name") for v in c.draft.values()
            if isinstance(v, dict) and v.get("Kind") == "Field"}
    assert live == {"keep"}


def test_delete_fields_reports_the_cluster_it_swept() -> None:
    c = FakeClient(_form_with(FieldSpec(name="drop", type=FieldType.TEXT)))
    rep = delete_fields(c, "F1", ("drop",), kind="form")
    assert isinstance(rep, DeleteFieldsReport)
    assert "1 Field node(s)" in rep.collateral and "1 Column node(s)" in rep.collateral


def test_delete_fields_surviving_field_is_a_loud_failure_not_a_silent_pass() -> None:
    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            return new                                     # accepted, but nothing changes

    c = Dropping(_form_with(FieldSpec(name="drop", type=FieldType.TEXT)))
    rep = delete_fields(c, "F1", ("drop",), publish=True, kind="form")
    assert isinstance(rep, DeleteFieldsReport)
    assert rep.surviving == ("drop",) and rep.deleted == ()
    assert rep.as_tool_result()["isError"] is True
    assert rep.published is False and c.published is False


def test_delete_fields_unknown_name_never_reaches_put() -> None:
    c = FakeClient(_form_with(FieldSpec(name="a", type=FieldType.TEXT)))
    got = delete_fields(c, "F1", ("a", "nope"), kind="form")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0, "one bad name in a batch must delete none of the batch"


def test_delete_fields_refuses_when_a_surviving_formula_still_reads_the_field() -> None:
    from kfforge.graph import set_field_computed

    draft = _form_with(FieldSpec(name="Total", type=FieldType.NUMBER),
                       FieldSpec(name="Qty", type=FieldType.NUMBER))
    draft = set_field_computed(draft, "Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})
    c = FakeClient(draft)

    got = delete_fields(c, "F1", ("Qty",), kind="form")
    assert isinstance(got, Err) and got.kind == "verify"
    assert "left dangling" in got.message and "Qty" in got.message
    assert "forge_apply_fields" in got.message, "a refusal must name the way out"
    assert c.puts == 0


def test_delete_fields_refuses_when_the_field_triggers_another_fields_visibility() -> None:
    from kfforge.graph import set_conditional_visibility

    draft = _form_with(FieldSpec(name="Reason", type=FieldType.TEXT),
                       FieldSpec(name="Flag", type=FieldType.BOOLEAN))
    draft = set_conditional_visibility(draft, "Reason", "Flag", "EQUAL_TO", "true")
    c = FakeClient(draft)

    got = delete_fields(c, "F1", ("Flag",), kind="form")
    assert isinstance(got, Err) and "TRIGGER" in got.message
    assert c.puts == 0


def test_delete_fields_refuses_when_a_surviving_event_script_names_the_field_id() -> None:
    from kfforge.graph import set_field_events

    draft = _form_with(FieldSpec(name="Source", type=FieldType.TEXT),
                       FieldSpec(name="Target", type=FieldType.TEXT))
    tgt = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Target")
    draft = set_field_events(draft, {"Source": [("onChange", f"kf.set('{tgt}');")]})
    c = FakeClient(draft)

    got = delete_fields(c, "F1", ("Target",), kind="form")
    assert isinstance(got, Err) and "Script" in got.message
    assert c.puts == 0


def test_delete_fields_deletes_a_user_field_cluster_rather_than_refusing_it() -> None:
    """A User field's QueryDefinition is swept, not refused: the caller has no tool that could
    remove it first, so a refusal there would be a dead end, not a safeguard."""
    c = FakeClient(_form_with(FieldSpec(name="Owner", type=FieldType.USER)))
    rep = delete_fields(c, "F1", ("Owner",), kind="form")
    assert isinstance(rep, DeleteFieldsReport) and rep.deleted == ("Owner",)
    assert not [v for v in c.draft.values()
                if isinstance(v, dict) and v.get("Kind") == "QueryDefinition"]


def test_delete_fields_publishes_only_after_the_absence_is_verified() -> None:
    c = FakeClient(_form_with(FieldSpec(name="drop", type=FieldType.TEXT)))
    rep = delete_fields(c, "F1", ("drop",), publish=True, kind="form")
    assert isinstance(rep, DeleteFieldsReport) and rep.published is True and c.published is True


def test_rename_form_fields_verifies_both_halves_of_the_rename() -> None:
    c = FakeClient(_form_with(FieldSpec(name="Tikcet No", type=FieldType.TEXT)))
    rep = rename_form_fields(c, "F1", {"Tikcet No": "Ticket No"}, kind="form")
    assert isinstance(rep, RenameFieldsReport)
    assert rep.verified == ("Tikcet No -> Ticket No",)
    assert rep.missing == () and rep.stale == ()
    assert rep.as_tool_result()["isError"] is False
    live = {v.get("Name") for v in c.draft.values()
            if isinstance(v, dict) and v.get("Kind") == "Field"}
    assert live == {"Ticket No"}


def test_rename_form_fields_keeps_the_node_id_so_events_and_permissions_survive() -> None:
    """The whole reason a rename beats delete-and-recreate."""
    draft = _form_with(FieldSpec(name="old", type=FieldType.TEXT))
    fid = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "old")
    c = FakeClient(draft)
    rename_form_fields(c, "F1", {"old": "new"}, kind="form")
    assert c.draft[fid]["Name"] == "new", "same node id, new label"


def test_rename_form_fields_reports_stale_when_the_old_name_survives() -> None:
    """A half-applied rename (old AND new both present) is worse than one that did not happen —
    every later name-keyed op then resolves to an arbitrary node. It must not read as success."""
    draft = _form_with(FieldSpec(name="old", type=FieldType.TEXT))

    class Doubling(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            new["Field_ghost"] = {"Id": "Field_ghost", "Kind": "Field", "Type": "Text",
                                  "Model": "M1", "Name": "old"}
            new["_meta_version"] = "v2"
            self.draft = new
            return new

    c = Doubling(draft)
    rep = rename_form_fields(c, "F1", {"old": "new"}, publish=True, kind="form")
    assert isinstance(rep, RenameFieldsReport)
    assert rep.stale == ("old -> new",) and rep.missing == ()
    assert rep.as_tool_result()["isError"] is True
    assert rep.published is False and c.published is False


def test_rename_form_fields_refuses_a_collision_with_an_existing_name() -> None:
    c = FakeClient(_form_with(FieldSpec(name="a", type=FieldType.TEXT),
                              FieldSpec(name="b", type=FieldType.TEXT)))
    got = rename_form_fields(c, "F1", {"a": "b"}, kind="form")
    assert isinstance(got, Err) and got.kind == "verify" and "already on this form" in got.message
    assert c.puts == 0


def test_rename_form_fields_unknown_name_never_reaches_put() -> None:
    c = FakeClient(_form_with(FieldSpec(name="a", type=FieldType.TEXT)))
    got = rename_form_fields(c, "F1", {"nope": "x"}, kind="form")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_required_sets_verifies_and_reports_what_it_cleared() -> None:
    """set_required is a SET, not a patch: everything unnamed comes back optional. That is the
    documented semantics — being unable to SEE it was the problem."""
    c = FakeClient(_form_with(FieldSpec(name="a", type=FieldType.TEXT, required=True),
                              FieldSpec(name="b", type=FieldType.TEXT, required=True),
                              FieldSpec(name="c", type=FieldType.TEXT)))
    rep = apply_required(c, "F1", ("a",), kind="form")
    assert isinstance(rep, RequiredReport)
    assert rep.missing == () and rep.verified == ("a", "b", "c")
    assert rep.cleared == ("b",), "b silently lost its Required flag — say so"
    assert rep.as_tool_result()["isError"] is False
    flags = {v["Name"]: v.get("Required") for v in c.draft.values()
             if isinstance(v, dict) and v.get("Kind") == "Field"}
    assert flags == {"a": True, "b": False, "c": False}


def test_apply_required_refuses_a_computed_field() -> None:
    """graph.set_required's own war story: a computed field marked Required blocked step 1 live,
    because nobody can type the value that would satisfy it."""
    from kfforge.graph import set_field_computed

    draft = _form_with(FieldSpec(name="Total", type=FieldType.NUMBER),
                       FieldSpec(name="Qty", type=FieldType.NUMBER))
    draft = set_field_computed(draft, "Total", {"fn": "concatenate", "args": [{"field": "Qty"}]})
    c = FakeClient(draft)

    got = apply_required(c, "F1", ("Total",), kind="form")
    assert isinstance(got, Err) and got.kind == "verify"
    assert "computed" in got.message and "unsubmittable" in got.message
    assert c.puts == 0


def test_apply_required_refuses_a_sequence_number_field() -> None:
    draft = _form_with(FieldSpec(name="Case ID", type=FieldType.TEXT))
    fid = next(k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "Case ID")
    draft[fid]["Type"] = "SequenceNumber"
    c = FakeClient(draft)

    got = apply_required(c, "F1", ("Case ID",), kind="form")
    assert isinstance(got, Err) and "SequenceNumber" in got.message
    assert c.puts == 0


def test_apply_required_unknown_name_never_reaches_put() -> None:
    c = FakeClient(_form_with(FieldSpec(name="a", type=FieldType.TEXT)))
    got = apply_required(c, "F1", ("nope",), kind="form")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


def test_apply_required_missing_is_a_loud_failure_on_read_back() -> None:
    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            return new                                     # accepted, nothing lands

    c = Dropping(_form_with(FieldSpec(name="a", type=FieldType.TEXT)))
    rep = apply_required(c, "F1", ("a",), publish=True, kind="form")
    assert isinstance(rep, RequiredReport)
    assert rep.missing == ("a",) and rep.verified == ()
    assert rep.as_tool_result()["isError"] is True and c.published is False


def test_apply_field_events_unknown_field_still_gets_set_field_events_own_message() -> None:
    """The derivation must not steal a refusal it states worse: an unknown NAME with a stated
    trigger falls through to `set_field_events`, which names the field precisely."""
    c = FakeClient(_form_with(FieldSpec(name="Real", type=FieldType.TEXT)))
    got = apply_field_events(c, "F1", {"Ghost": [("onChange", "1;")]})
    assert isinstance(got, Err) and got.kind == "verify"
    assert "no field named 'Ghost'" in got.message
    assert c.puts == 0


def test_apply_field_events_unknown_field_with_nothing_to_derive_from_says_so() -> None:
    c = FakeClient(_form_with(FieldSpec(name="Real", type=FieldType.TEXT)))
    got = apply_field_events(c, "F1", {"Ghost": [(None, "1;")]})
    assert isinstance(got, Err) and got.kind == "verify"
    assert "cannot derive a trigger for 'Ghost'" in got.message
    assert c.puts == 0


# ---- regressions found reviewing the F2/M1 work (D1, D2, D3) ----------------------------------

def test_delete_fields_by_node_id_can_still_FAIL_its_read_back() -> None:
    """D2 / THE RULE: `fields` accepts a raw node id (the documented way to disambiguate a name a
    form field and a table child share). The audit used to look that token up in a set of NAMES,
    where a node id can never appear — so an id-addressed delete read as gone whether or not the
    write landed, and published on it. A read-back that cannot fail is not a read-back."""
    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            return new                                     # 200, lands nothing

    c = Dropping(_form_with(FieldSpec(name="drop", type=FieldType.TEXT)))
    fid = next(k for k, v in c.draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "drop")

    rep = delete_fields(c, "F1", (fid,), publish=True, kind="form")
    assert isinstance(rep, DeleteFieldsReport)
    assert rep.surviving == (fid,) and rep.deleted == ()
    assert rep.published is False
    assert rep.as_tool_result()["isError"] is True


def test_delete_fields_by_node_id_reports_a_real_delete_as_deleted() -> None:
    """The control for the test above: the id path must still report a delete that DID land."""
    c = FakeClient(_form_with(FieldSpec(name="keep", type=FieldType.TEXT),
                              FieldSpec(name="drop", type=FieldType.TEXT)))
    fid = next(k for k, v in c.draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "drop")

    rep = delete_fields(c, "F1", (fid,), kind="form")
    assert isinstance(rep, DeleteFieldsReport)
    assert rep.deleted == (fid,) and rep.surviving == ()
    assert rep.as_tool_result()["isError"] is False


def test_user_field_reapply_is_idempotent_not_a_changed_ignored_error() -> None:
    """D1: `graph.apply_changes` deliberately pops `LHSModel` off the Field node onto the User
    field's mandatory QueryDefinition sibling, so it reads back as None on the Field forever.
    The changed-ignored diff compared the requested value against that None and flagged a field
    written exactly as asked — turning the documented idempotent re-apply into a hard error whose
    own remediation advised DELETING a correct field (destroying its permissions and data)."""
    spec = FieldSpec(name="Requester", type=FieldType.USER, options={"LHSModel": "_employee"})
    c = FakeClient(_bare_form_draft())

    first = apply_fields(c, "form", "F1", [spec])
    assert isinstance(first, ApplyReport) and first.as_tool_result()["isError"] is False

    second = apply_fields(c, "form", "F1", [spec])
    assert isinstance(second, ApplyReport)
    result = second.as_tool_result()
    assert result["changed_ignored"] == [], result["changed_ignored"]
    assert second.skipped == ("Requester",)
    assert result["isError"] is False


def test_a_genuinely_changed_option_key_is_still_reported() -> None:
    """The control: excluding the relocated key must not blind the diff to a real change."""
    c = FakeClient(_bare_form_draft())
    apply_fields(c, "form", "F1", [FieldSpec(name="Qty", type=FieldType.NUMBER)])
    changed = apply_fields(c, "form", "F1",
                           [FieldSpec(name="Qty", type=FieldType.TEXT)])
    assert isinstance(changed, ApplyReport)
    assert changed.as_tool_result()["changed_ignored"], "a real Type change must still be loud"
    assert changed.as_tool_result()["isError"] is True


# =====================================================================================
# D4/D5/D6/D9 + the 2026-08-19 live findings. One section per defect; each test is written
# against the UNFIXED behavior first, so it fails before the change it proves.
# =====================================================================================

def test_apply_required_reports_a_requested_field_that_vanished_as_missing() -> None:
    """D4, the output invariant. `verified`/`missing` used to be computed over the READ-BACK
    population, so a requested name present BEFORE the write and absent from the read-back landed
    in no bucket at all and the flow published:
      {"required": ["A"], "verified": ["B"], "missing": [], "published": true, "isError": false}
    Every sibling (delete_fields, rename_form_fields, apply_fields) iterates the REQUESTED set."""
    draft = _form_with(FieldSpec(name="A", type=FieldType.TEXT),
                       FieldSpec(name="B", type=FieldType.TEXT))
    a_id = next(k for k, v in draft.items()
                if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A")

    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            new.pop(a_id)                      # the write "succeeds"; A is not there afterwards
            new["_meta_version"] = "v2"
            self.draft = new
            return new

    c = Dropping(draft)
    rep = apply_required(c, "F1", ("A",), publish=True, kind="form")
    assert isinstance(rep, RequiredReport)
    assert "A" in rep.missing, "a requested field absent from the read-back is a loud failure"
    assert "A" not in rep.verified
    assert rep.as_tool_result()["isError"] is True
    assert rep.published is False and c.published is False


def test_apply_required_still_audits_the_whole_read_back_population() -> None:
    """The control for the fix above: the SET-semantics audit (a field the caller never named
    that came back with the wrong flag) must survive the switch to a requested-set union."""
    class Sticky(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            for v in new.values():
                if isinstance(v, dict) and v.get("Name") == "b":
                    v["Required"] = True       # refuses to be cleared
            new["_meta_version"] = "v2"
            self.draft = new
            return new

    c = Sticky(_form_with(FieldSpec(name="a", type=FieldType.TEXT),
                          FieldSpec(name="b", type=FieldType.TEXT, required=True)))
    rep = apply_required(c, "F1", ("a",), kind="form")
    assert isinstance(rep, RequiredReport)
    assert rep.missing == ("b",) and rep.verified == ("a",)
    assert rep.as_tool_result()["isError"] is True


def _permission_missing_activity(draft: dict) -> dict:
    """Seed one Permission node with no `Activity` — the shape `_permission_pairs` used to
    KeyError on. Nothing in this engine mints one; a template or a half-applied write does."""
    new = dict(draft)
    col = next(k for k, v in new.items()
               if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Field")
    new["Permission_broken01"] = {"Id": "Permission_broken01", "Kind": "Permission",
                                  "Column": col, "Permission": "Editable"}
    return new


def test_build_workflow_does_not_key_error_on_a_permission_with_no_activity() -> None:
    """D6, errors are DATA. `_permission_pairs` subscripted n["Activity"] unguarded, and
    apply_workflow added two NEW call sites around the write — so one malformed Permission node
    escaped forge_build_workflow as a bare KeyError traceback, before any write."""
    from synthetic import synthetic_process_draft

    c = FakeClient(_permission_missing_activity(synthetic_process_draft()))
    rep = apply_workflow(c, "F1", [("Only step", None)])
    assert isinstance(rep, WorkflowReport), f"expected a report, got {rep!r}"
    assert rep.verified_steps == ("Only step",)


def test_build_workflow_counts_the_malformed_permission_it_destroyed() -> None:
    """The other half of the guard: a node the pair walk SKIPS must still land in a bucket, or
    the guard has just traded a crash for a silent loss."""
    from synthetic import synthetic_process_draft

    c = FakeClient(_permission_missing_activity(synthetic_process_draft()))
    rep = apply_workflow(c, "F1", [("Only step", None)])
    assert isinstance(rep, WorkflowReport)
    hits = [line for line in rep.collateral if "Permission_broken01" in line]
    assert len(hits) == 1, rep.collateral
    assert "malformed" in hits[0]
    assert "forge_set_visibility" in rep.remediation
    assert rep.remediation.count("forge_set_visibility") == 1


def test_set_visibility_does_not_key_error_on_a_permission_with_no_activity() -> None:
    """The same guard on the OTHER caller of the pair walk: the rebuild deletes every Permission,
    malformed ones included, so a node the walk skips must still be named in `collateral`."""
    from synthetic import OWNERS, synthetic_process_draft

    from kfforge.graph import progressive_matrix
    draft = synthetic_process_draft()
    matrix = progressive_matrix(draft, OWNERS)
    c = FakeClient(_permission_missing_activity(draft))
    rep = apply_step_permissions(c, "F1", matrix)
    assert isinstance(rep, ApplyReport), f"expected a report, got {rep!r}"
    hits = [line for line in rep.collateral if "Permission_broken01" in line]
    assert len(hits) == 1 and "malformed" in hits[0], rep.collateral


# ---- D5: forge_apply_fields silently re-tiles a custom grid ----------------------------------

def _field_placements_of(draft: dict) -> dict[str, tuple[str, int, int, int]]:
    from kfforge.client import _field_placements

    return _field_placements(draft)


def _grid_layout(draft: dict, section: str) -> list[list[tuple[str, int, int]]]:
    """The section's rows as (field name, Start, End) triples — the shape apply_layout speaks."""
    rows: dict[int, list[tuple[str, int, int]]] = {}
    for name, (title, ri, start, end) in _field_placements_of(draft).items():
        if title == section:
            rows.setdefault(ri, []).append((name, start, end))
    return [sorted(rows[i], key=lambda t: t[1]) for i in sorted(rows)]


def test_apply_fields_reports_the_custom_grid_it_re_tiled() -> None:
    """D5. Reproduced live: a custom grid written by forge_apply_layout as
    [[0-3, 3-6], [0-6], [0-6]] came back [[0-2, 2-4, 4-6], [0-2, 2-4]] after ONE
    forge_apply_fields call — every pre-existing field moved, and the report said nothing.
    forge_apply_fields is annotated destructiveHint: True for exactly this."""
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(
        c, "form", "F1",
        [FieldSpec(name=n, type=FieldType.TEXT) for n in ("A", "B", "C", "D")],
        groups=[("Details", ["A", "B", "C", "D"])])
    apply_layout(c, "F1", {"Details": [[("A", 0, 3), ("B", 3, 6)], [("C", 0, 6)], [("D", 0, 6)]]},
                 kind="form")
    assert _grid_layout(c.draft, "Details") == [[("A", 0, 3), ("B", 3, 6)],
                                                [("C", 0, 6)], [("D", 0, 6)]]

    rep = apply_fields_full(c, "form", "F1", [FieldSpec(name="E", type=FieldType.TEXT)],
                            groups=[("Details", ["E"])])
    assert isinstance(rep, FullFieldsReport)
    assert _grid_layout(c.draft, "Details") != [[("A", 0, 3), ("B", 3, 6)],
                                                [("C", 0, 6)], [("D", 0, 6)]], "sanity: it moved"
    moved = {line.split("'")[1] for line in rep.collateral}
    assert moved == {"A", "B", "C", "D"}, rep.collateral
    assert "E" not in moved, "a field this call ADDED did not move — it did not exist before"
    assert any("0-3" in line and "0-2" in line for line in rep.collateral), rep.collateral
    assert "forge_apply_layout" in rep.remediation
    assert rep.as_tool_result()["collateral"] == list(rep.collateral)
    assert rep.as_tool_result()["isError"] is False, "nothing was lost — ids and refs survive"


def test_apply_fields_and_layout_reports_the_custom_grid_it_re_tiled() -> None:
    """The sibling that hardcoded `collateral=()`."""
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name=n, type=FieldType.TEXT) for n in ("A", "B")],
        groups=[("Details", ["A", "B"])])
    apply_layout(c, "F1", {"Details": [[("A", 0, 6)], [("B", 0, 6)]]}, kind="form")

    rep = apply_fields_and_layout(c, "form", "F1", [FieldSpec(name="C", type=FieldType.TEXT)],
                                 groups=[("Details", ["C"])])
    assert isinstance(rep, ApplyReport)
    assert {line.split("'")[1] for line in rep.collateral} == {"A", "B"}, rep.collateral
    assert "forge_apply_layout" in rep.remediation


def test_apply_fields_collateral_is_silent_when_nothing_actually_moved() -> None:
    """No false positives: a regroup that lands every field exactly where it already was reports
    nothing. Without this the collateral bucket is noise on every idempotent re-run."""
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name=n, type=FieldType.TEXT) for n in ("A", "B", "C")],
        groups=[("Details", ["A", "B", "C"])])

    same = apply_fields_and_layout(c, "form", "F1",
                                   [FieldSpec(name="A", type=FieldType.TEXT)],
                                   groups=[("Details", ["A", "B", "C"])])
    assert isinstance(same, ApplyReport)
    assert same.collateral == (), same.collateral
    assert same.remediation == ()

    added = apply_fields_full(c, "form", "F1", [FieldSpec(name="D", type=FieldType.TEXT)],
                              groups=[("Details", ["D"])])
    assert isinstance(added, FullFieldsReport)
    assert added.collateral == (), "appending a 4th field opens a new row; A/B/C do not move"


def test_apply_fields_with_no_groups_writes_no_layout_collateral() -> None:
    """A call that never regroups cannot move anything — the collateral must stay empty."""
    c = FakeClient(_bare_form_draft())
    apply_fields_and_layout(
        c, "form", "F1", [FieldSpec(name=n, type=FieldType.TEXT) for n in ("A", "B")],
        groups=[("Details", ["A", "B"])])
    apply_layout(c, "F1", {"Details": [[("A", 0, 6)], [("B", 0, 6)]]}, kind="form")

    rep = apply_fields_full(c, "form", "F1", [FieldSpec(name="C", type=FieldType.TEXT)])
    assert isinstance(rep, FullFieldsReport)
    assert rep.collateral == (), rep.collateral
    placements = _field_placements_of(c.draft)
    assert placements["A"] == ("Details", 0, 0, 6) and placements["B"] == ("Details", 1, 0, 6)


# ---- D9: a no-op rename classified as the worst bucket ---------------------------------------

def test_rename_form_fields_calls_a_no_op_rename_unchanged_not_stale() -> None:
    """D9. The collision guard exempts old == new (renaming A onto A collides with nothing), and
    the read-back then classified it `stale` — new name present, old name present, because they
    are the same name — which is isError, publish suppressed, for a write that did exactly what
    was asked."""
    c = FakeClient(_form_with(FieldSpec(name="Ticket No", type=FieldType.TEXT)))
    rep = rename_form_fields(c, "F1", {"Ticket No": "Ticket No"}, publish=True, kind="form")
    assert isinstance(rep, RenameFieldsReport)
    assert rep.unchanged == ("Ticket No -> Ticket No",)
    assert rep.stale == () and rep.missing == () and rep.verified == ()
    assert rep.as_tool_result()["isError"] is False
    assert rep.published is True and c.published is True
    assert rep.as_tool_result()["unchanged"] == ["Ticket No -> Ticket No"]


def test_a_no_op_rename_whose_field_vanished_is_still_missing() -> None:
    """The no-op exemption is on the CLASSIFICATION, never on the audit."""
    draft = _form_with(FieldSpec(name="A", type=FieldType.TEXT))
    a_id = next(k for k, v in draft.items()
                if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == "A")

    class Dropping(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            new.pop(a_id)
            new["_meta_version"] = "v2"
            self.draft = new
            return new

    c = Dropping(draft)
    rep = rename_form_fields(c, "F1", {"A": "A"}, publish=True, kind="form")
    assert isinstance(rep, RenameFieldsReport)
    assert rep.missing == ("A -> A",) and rep.unchanged == ()
    assert rep.as_tool_result()["isError"] is True and rep.published is False


def test_a_real_stale_rename_is_still_stale() -> None:
    """The control: exempting old == new must not blind the two-condition test to a real
    half-applied rename."""
    draft = _form_with(FieldSpec(name="old", type=FieldType.TEXT))

    class Doubling(FakeClient):
        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            self.puts += 1
            new["Field_ghost"] = {"Id": "Field_ghost", "Kind": "Field", "Type": "Text",
                                  "Model": "M1", "Name": "old"}
            new["_meta_version"] = "v2"
            self.draft = new
            return new

    c = Doubling(draft)
    rep = rename_form_fields(c, "F1", {"old": "new"}, kind="form")
    assert isinstance(rep, RenameFieldsReport)
    assert rep.stale == ("old -> new",) and rep.unchanged == ()
    assert rep.as_tool_result()["isError"] is True


# ---- live findings 2026-08-19: the dead-end note, and the silent role gap --------------------

def test_empty_app_role_note_names_the_tool_that_fixes_it_not_a_human() -> None:
    """LIVE FINDING. The old note told the caller "a human must create at least one AppRole for
    this app in the builder UI first". That is FALSE and was disproven live: forge_create_app_role
    creates one in a single call (POST /app_role/2/{acct}, PROVEN live 2026-08-08), after which
    forge_member_batch works. A refusal a caller cannot act on is just a dead end."""
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport) and rep.note is not None
    assert "builder UI" not in rep.note
    assert "a human must" not in rep.note
    assert "forge_create_app_role" in rep.note
    assert rep.as_tool_result()["isError"] is False


def test_member_batch_states_how_many_app_roles_it_saw_versus_granted() -> None:
    """LIVE FINDING: two AppRoles were created against a brand-new app and member_batch granted
    ONE, saying nothing about the other. With only a granted count in the report there is no way
    to tell a DISCOVERY gap (the account list returned one) from a GRANT gap (it returned two and
    one was dropped) — so the report now states both numbers, always."""
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []
    c.app_roles = [
        {"_id": "RoE2MFjIipw3", "Name": "Repair Technician", "_application_id": "App"},
        {"_id": "RoE2MFsjHKHA", "Name": "Requester", "_application_id": "App"},
    ]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.roles_seen == 2
    assert rep.as_tool_result()["roles_seen"] == 2
    assert rep.as_tool_result()["roles_granted"] == 2
    assert rep.note is not None and "saw 2" in rep.note and "granted 2" in rep.note


def test_an_app_role_seen_but_not_grantable_lands_in_its_own_bucket() -> None:
    """Doctrine: seen == granted + unusable. A record the account list returns without an `_id`
    (or without a `Name`) cannot be posted to member/batch at all, and dropping it silently is
    exactly how "granted 1 of 2" reads as a clean success."""
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []
    c.app_roles = [
        {"_id": "RoGood", "Name": "Requester", "_application_id": "App"},
        {"Name": "Nameless Id", "_application_id": "App"},          # no _id
        {"_id": "RoNoName", "_application_id": "App"},              # no Name
    ]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.roles_seen == 3
    assert rep.applied == ("RoGood",)
    assert len(rep.roles_unusable) == 2, rep.roles_unusable
    assert rep.roles_seen == len(rep.applied) + len(rep.roles_unusable)
    assert rep.note is not None and "seen but NOT granted" in rep.note


def test_harvest_path_also_states_seen_versus_granted() -> None:
    """The same doctrine one source of members over: `_normalize_member` drops any harvested
    record with no `Role` key, and dropped it into nothing at all — seen == granted + unusable
    must hold on BOTH paths apply_member_batch can take, not just the account-level one."""
    c = FakeClient(_bare_process_draft())
    c.members[("process", "F_source")] = [
        {"_id": "RoA", "Name": "Admin", "Kind": "AppRole", "Role": "DataAdmin",
         "Permission": ["InitiateItems"]},
        {"_id": "RoJunk", "Name": "No Role Key", "Kind": "AppRole"},     # dropped by the normalizer
    ]
    rep = apply_member_batch(c, "F_target", source_flow_id="F_source")
    assert isinstance(rep, MemberReport)
    assert rep.roles_seen == 2
    assert rep.applied == ("DataAdmin",)
    assert len(rep.roles_unusable) == 1 and "RoJunk" in rep.roles_unusable[0]
    assert rep.roles_seen == len(rep.applied) + len(rep.roles_unusable)
    assert rep.note is not None and "seen but NOT granted" in rep.note
    assert rep.as_tool_result()["roles_granted"] == 1


def test_harvest_path_stays_quiet_when_every_record_was_granted() -> None:
    """The control: a clean harvest must not grow a note it never had."""
    c = FakeClient(_bare_process_draft())
    c.members[("process", "F_source")] = [
        {"_id": "RoA", "Name": "Admin", "Kind": "AppRole", "Role": "DataAdmin",
         "Permission": ["InitiateItems"]},
    ]
    rep = apply_member_batch(c, "F_target", source_flow_id="F_source")
    assert isinstance(rep, MemberReport)
    assert rep.note is None and rep.roles_unusable == ()
    assert rep.roles_seen == 1 and rep.as_tool_result()["roles_granted"] == 1


class _NonDictRoleClient(FakeClient):
    """A client whose account-level AppRole list returns a record that is not a dict at all.

    Real, not hypothetical: `KfClient.list_app_roles` only filters non-dicts when it is SCOPING
    to an app id — called with `app_id=None` (a config with no app scope) it returns the route's
    bare array verbatim, whatever the account replies with. `FakeClient.list_app_roles` cannot
    stand in here: its own scope filter calls `.get` on every record."""

    def list_app_roles(self, app_id=None):  # type: ignore[override]
        return list(self.app_roles)


def test_a_non_dict_app_role_record_still_lands_in_a_counted_bucket() -> None:
    """Doctrine 2, one line above where the same class was closed: `scoped = [r for r in roles if
    isinstance(r, dict)]` dropped a non-dict record into NOTHING — the route returned two records
    and the report said it saw one. `seen == granted + unusable` held only because the dropped
    record never entered the count, which is exactly the bug that invariant exists to catch. The
    harvest path already handles a non-dict correctly; the two must agree."""
    c = _NonDictRoleClient(_bare_process_draft())
    c.flows["process"] = []
    c.app_roles = ["not-a-dict", {"_id": "R1", "Name": "Tech", "_application_id": "App"}]  # type: ignore[list-item]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.applied == ("R1",)
    assert rep.roles_seen == 2, "the route returned TWO records — the report must say so"
    assert len(rep.roles_unusable) == 1 and "not-a-dict" in rep.roles_unusable[0]
    assert rep.roles_seen == len(rep.applied) + len(rep.roles_unusable)
    assert rep.note is not None and "seen but NOT granted" in rep.note


def test_a_non_dict_app_role_record_is_counted_even_when_nothing_is_grantable() -> None:
    """The other arm of the same bucket rule: with NO usable role at all the early-return report
    must still count what the route returned, or 'saw 0 app-scoped records' reads as an empty
    account when the account actually answered with something unusable."""
    c = _NonDictRoleClient(_bare_process_draft())
    c.flows["process"] = []
    c.app_roles = ["not-a-dict"]  # type: ignore[list-item]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.applied == () and rep.roles_seen == 1
    assert len(rep.roles_unusable) == 1 and "not-a-dict" in rep.roles_unusable[0]
    assert rep.roles_seen == len(rep.applied) + len(rep.roles_unusable)


def test_every_app_role_record_is_counted_when_they_are_all_usable() -> None:
    """The control: a clean account list grows no unusable bucket and still reconciles."""
    c = _NonDictRoleClient(_bare_process_draft())
    c.flows["process"] = []
    c.app_roles = [{"_id": "R1", "Name": "Tech", "_application_id": "App"}]
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.roles_seen == 1 and rep.applied == ("R1",) and rep.roles_unusable == ()


# =================================================================================================
# S3 — LIVE FINDING: ONE forge_set_visibility call returned ~15,000 TOKENS.
#
# 222 (column, activity) pairs listed TWICE (once under `added`, once under `verified`), every
# entry an opaque "Column_13Hw6YCM9B@Activity_3c29a1abe0" with no field or step NAME anywhere; two
# such calls cost ~25k tokens to convey "222 pairs written, 0 missing". The AUDIT is correct and
# doctrine-2 required and is NOT weakened here — every one of those tuples is still complete on
# the dataclass. Only the PRESENTATION is bounded.
# =================================================================================================


def _wide_matrix_draft(n_fields: int = 37) -> dict:
    """The exact live shape: 37 field columns x 6 permission-bearing activities = 222 pairs.

    Built BY the engine (dogfood), zero real-app content — 4 UserTasks plus the StartEvent and the
    EndEvent are the 6 bearing steps (a Parallel/GotoTask/SendBackToInitiator carries none).
    """
    import json
    import pathlib

    from kfforge.graph import regroup_into_sections

    base = pathlib.Path(__file__).parent / "fixtures" / "empty_form_draft.json"
    names = [f"Field {i:02d}" for i in range(n_fields)]
    d = json.loads(base.read_text())
    d = _apply_changes(d, [FieldSpec(name=n, type=FieldType.TEXT) for n in names])
    d = regroup_into_sections(d, [("Intake", names[:12]), ("Assess", names[12:25]),
                                  ("Wrap", names[25:])])
    d = _build_workflow(d, [("Ticket arrives", None), ("Assess unit", None),
                            ("Route to path", None), ("Wrap-up report", None)])
    return d


_WIDE_OWNERS = {"Intake": ["Start", "Ticket arrives"], "Assess": ["Assess unit"],
                "Wrap": ["Wrap-up report"]}


def _wide_report(draft: dict | None = None, **kw):
    from kfforge.graph import progressive_matrix

    d = draft if draft is not None else _wide_matrix_draft()
    c = FakeClient(d)
    return c, apply_step_permissions(c, "F1", progressive_matrix(d, _WIDE_OWNERS), **kw)


def test_the_222_pair_case_is_measured_and_the_default_payload_is_bounded() -> None:
    """The measurement, pinned. 37 columns x 6 activities is the live case verbatim."""
    import json

    _c, rep = _wide_report()
    assert len(rep.added) == 222 and len(rep.verified) == 222, "precondition: the live pair count"

    # what this used to emit: the BASE ApplyReport payload, both full lists, opaque ids
    before = json.dumps(ApplyReport.as_tool_result(rep))
    after = json.dumps(rep.as_tool_result())
    assert len(before) > 18_000, len(before)
    assert len(after) < 1_500, after
    assert len(after) * 10 < len(before), f"{len(before)} -> {len(after)} is not a real bound"


def test_the_default_payload_carries_no_opaque_pair_ids_at_all() -> None:
    _c, rep = _wide_report()
    body = repr(rep.as_tool_result())
    assert "Column_" not in body and "Activity_" not in body, body[:400]
    assert rep.as_tool_result()["pair_counts"] == {
        "added": 222, "skipped": 0, "verified": 222, "missing": 0, "collateral": 0,
    }


def test_the_summary_names_sections_and_steps_not_ids() -> None:
    """An id-only audit is unreadable to the agent that has to act on it."""
    _c, rep = _wide_report()
    got = rep.as_tool_result()
    assert got["by_section"] == [
        "Assess: 78 pair(s) written, 78 verified, 0 missing",
        "Intake: 72 pair(s) written, 72 verified, 0 missing",
        "Wrap: 72 pair(s) written, 72 verified, 0 missing",
    ]
    assert [line.split(":")[0] for line in got["by_step"]] == [
        "Assess unit", "End", "Route to path", "Start", "Ticket arrives", "Wrap-up report",
    ]


def test_nothing_is_ever_silently_withheld() -> None:
    """No silent caps: the payload always states how many entries the counts stand in for."""
    _c, rep = _wide_report()
    got = rep.as_tool_result()
    assert got["summarised"] == len(rep.added) + len(rep.skipped) + len(rep.verified) == 444
    assert "444" in got["note"] and "include_pairs" in got["note"]


def test_include_pairs_returns_every_pair_and_says_it_summarised_nothing() -> None:
    _c, rep = _wide_report(include_pairs=True)
    got = rep.as_tool_result()
    assert got["summarised"] == 0
    assert len(got["pairs"]["added"]) == 222 and len(got["pairs"]["verified"]) == 222
    assert got["pairs"]["verified"][0].count("/") == 1 and "@" in got["pairs"]["verified"][0]
    assert "Column_" not in repr(got["pairs"]), "even the opt-in list is resolved to names"


def test_the_audit_tuples_are_untouched_by_the_presentation_bound() -> None:
    """The half that must NOT change: doctrine 2 lives on the dataclass, not in the payload."""
    _c, rep = _wide_report()
    assert len(set(rep.added) | set(rep.verified)) == 222
    assert all("@" in p and p.startswith("Column_") for p in rep.added)
    assert set(rep.verified) == set(rep.added)


def test_every_missing_pair_is_listed_in_full_and_by_name() -> None:
    """`missing` is the FAILURE bucket and is never summarised, at any size."""
    class DroppingHalf(FakeClient):
        """A PUT that lands, and a read-back that lost every Permission on one activity."""

        def __init__(self, draft: dict) -> None:
            super().__init__(draft)
            self.dropped: str | None = None

        def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
            got = super().put_draft(kind, flow_id, new, expect_version)
            acts = [k for k, v in self.draft.items()
                    if isinstance(v, dict) and v.get("Kind") == "Activity"
                    and v.get("Name") == "Assess unit"]
            self.dropped = acts[0]
            for pid in [k for k, v in list(self.draft.items())
                        if isinstance(v, dict) and v.get("Kind") == "Permission"
                        and v.get("Activity") == self.dropped]:
                del self.draft[pid]
            return got

    from kfforge.graph import progressive_matrix

    d = _wide_matrix_draft()
    c = DroppingHalf(d)
    rep = apply_step_permissions(c, "F1", progressive_matrix(d, _WIDE_OWNERS))
    got = rep.as_tool_result()
    assert got["pair_counts"]["missing"] == 37
    assert len(got["missing"]) == 37, "the failure bucket is listed in full, never summarised"
    assert all(p.endswith("@ Assess unit") for p in got["missing"]), got["missing"][:3]
    assert got["isError"] is True
    assert "37 FAILED pairs" in got["note"]


def test_collateral_lines_name_the_field_and_step_they_deleted() -> None:
    """The destructive half is resolved to names too — and keeps the id, which is the only thing
    that can be handed back to a graph read."""
    from kfforge.graph import progressive_matrix

    d = _wide_matrix_draft()
    c = FakeClient(d)
    full = progressive_matrix(d, _WIDE_OWNERS)
    apply_step_permissions(c, "F1", full)
    dropped = sorted(next(iter(full.values())))[0]
    thinner = {s: {a: v for a, v in row.items() if a != dropped} for s, row in full.items()}
    second = apply_step_permissions(c, "F1", thinner)
    assert second.collateral and all(dropped in line for line in second.collateral)
    assert all("/" in line and "@" in line for line in second.collateral)


# ---- S4(b): forge_set_visibility must name the sections the owners map did not cover ------------


def test_set_visibility_names_a_section_that_is_editable_at_no_step() -> None:
    """The live trap: the template shell injects sections the caller cannot name in `owners`, so
    the matrix is broken from the first write and doctor only says so two steps later."""
    from kfforge.graph import progressive_matrix

    d = _wide_matrix_draft()
    owners = {k: v for k, v in _WIDE_OWNERS.items() if k != "Wrap"}
    c = FakeClient(d)
    rep = apply_step_permissions(c, "F1", progressive_matrix(d, owners))
    got = rep.as_tool_result()
    assert got["uncovered_sections"] == ["Wrap"]
    assert got["isError"] is False, "leaving a section alone can be deliberate — never an error"


def test_a_fully_covered_matrix_reports_no_uncovered_section() -> None:
    """The no-false-positive control — passes before AND after."""
    _c, rep = _wide_report()
    assert rep.as_tool_result()["uncovered_sections"] == []


def test_a_section_covered_only_by_field_level_overrides_is_not_uncovered() -> None:
    """A section that only HIDES, with editability expressed per field, is fully intentional."""
    from kfforge.graph import field_override_matrix, progressive_matrix

    d = _wide_matrix_draft()
    owners = {k: v for k, v in _WIDE_OWNERS.items() if k != "Wrap"}
    field_owners = {"Field 25": ["Wrap-up report"]}
    c = FakeClient(d)
    rep = apply_step_permissions(c, "F1", progressive_matrix(d, owners),
                                 field_matrix=field_override_matrix(d, field_owners))
    assert rep.as_tool_result()["uncovered_sections"] == []


# ---- S4(a): forge_create_process must state what the template brought in -----------------------


def test_create_process_states_the_sections_the_template_injected() -> None:
    """The report used to be all empty tuples, so the caller was blind to four sections and three
    Required fields the DEFAULT put on their flow."""
    from kfforge.client import ProcessCreateReport

    c = _CreateProcessClient()
    rep = create_process(c, "Expense Approval", ("Draft",), [])
    assert isinstance(rep, ProcessCreateReport)
    got = rep.as_tool_result()
    assert got["from_template"] is True
    assert got["template_sections"] == ["In-Kissflow Template", "Public Form Template",
                                        "Request Details", "Request Info", "System"]
    assert got["template_steps"] == ["Completed", "Manager Approve", "Start"]
    assert "owners" in got["note"] and str(len(got["template_sections"])) in got["note"]


def test_create_process_states_the_required_fields_the_template_injected() -> None:
    """A Required field that is never editable makes its step permanently unsubmittable — the
    caller cannot cover a field it was never told about."""
    c = _CreateProcessClient()
    got = create_process(c, "Expense Approval", ("Draft",), []).as_tool_result()
    live = sorted(v["Name"] for v in c.draft.values()
                  if isinstance(v, dict) and v.get("Kind") == "Field"
                  and v.get("Model") == c.draft["Root"] and v.get("Required"))
    assert got["template_required_fields"] == live
    assert live, "precondition: the shipped shell really does carry Required fields"


def test_from_template_false_reports_an_empty_template_inventory() -> None:
    """The control: the bare scaffold brings in no section and no Required field, and says so
    rather than pretending it did."""
    c = _CreateProcessClient()
    got = create_process(c, "Expense Approval", ("Review",), [], from_template=False).as_tool_result()
    assert got["from_template"] is False
    assert got["template_sections"] == [] and got["template_required_fields"] == []
    assert got["template_steps"] == ["Completed", "Review", "Start"]
    assert "note" not in got


def test_an_unreadable_scaffold_is_stated_not_reported_as_an_empty_template() -> None:
    """Doctrine 2, on the inventory itself: buckets that are empty because nothing was READ must
    never look identical to buckets that are empty because nothing was there."""
    class _NoFinalRead(_CreateProcessClient):
        def __init__(self) -> None:
            super().__init__()
            self.reads = 0

        def get_draft(self, kind, flow_id):  # type: ignore[override]
            self.reads += 1
            if self.reads > 3:                     # scaffold read + apply_fields' two reads
                return Err("http", "GET draft -> 503")
            return self.draft

    got = create_process(_NoFinalRead(), "Expense Approval", ("Draft",), []).as_tool_result()
    assert got["template_sections"] == [] and got["template_required_fields"] == []
    assert got["template_read_error"] and "503" in got["template_read_error"]
    assert "not because the shell brought nothing in" in got["note"]


def test_create_flow_any_process_also_states_the_template_inventory() -> None:
    """The OTHER tool that runs the same clone — forge_create_flow(kind='process')."""
    c = _CreateProcessClient()
    got = create_flow_any(c, "process", "Expense Approval").as_tool_result()
    assert got["from_template"] is True
    assert got["template_sections"] == ["In-Kissflow Template", "Public Form Template",
                                        "Request Details", "Request Info", "System"]
    assert got["template_steps"] == ["Completed", "Manager Approve", "Start"]
    assert got["template_required_fields"] == ["Branch", "Department", "Description",
                                               "Manager Display Name",
                                               "Requestor Employee Id Alt"]


class _AckOnlyPutClient(_CreateProcessClient):
    """A client whose draft PUT answers with an ACK, not the graph — `{"_id":..., "success":true}`.

    The live API is under no obligation to echo the whole draft back, and `create_flow_any` read
    its template inventory straight off that response. An ack inventories to three empty tuples
    with no error anywhere: indistinguishable from a template that genuinely brought nothing in."""

    def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
        super().put_draft(kind, flow_id, new, expect_version)
        return {"_id": flow_id, "success": True}


def test_create_flow_any_inventories_the_live_draft_never_the_put_response() -> None:
    """THE RULE: an inventory that can fall back to what the caller SENT is not evidence. The whole
    point of these three buckets is to state what the template silently injected — the trap that
    broke a live build (four unexpected sections, three unexpected Required fields) — so they must
    come off a real read of the flow, exactly as create_process's do."""
    got = create_flow_any(_AckOnlyPutClient(), "process", "Expense Approval").as_tool_result()
    assert got["template_sections"] == ["In-Kissflow Template", "Public Form Template",
                                        "Request Details", "Request Info", "System"]
    assert got["template_steps"] == ["Completed", "Manager Approve", "Start"]
    assert got["template_required_fields"], "the shipped shell really does carry Required fields"
    assert got["template_read_error"] is None


def test_create_flow_any_states_an_unreadable_template_read() -> None:
    """The sibling half of the distinction `ProcessCreateReport` was created to make: buckets that
    are empty because nothing was READ must never look identical to buckets that are empty because
    nothing was there. `create_flow_any` had no `template_read_error` field at all."""
    class _NoReadBack(_CreateProcessClient):
        def __init__(self) -> None:
            super().__init__()
            self.reads = 0

        def get_draft(self, kind, flow_id):  # type: ignore[override]
            self.reads += 1
            if self.reads > 1:                     # the scaffold read succeeds, the read-back dies
                return Err("http", "GET draft -> 503")
            return self.draft

    got = create_flow_any(_NoReadBack(), "process", "Expense Approval").as_tool_result()
    assert got["flow_id"] == "F1", "the flow was created — an unreadable read-back is not a failure"
    assert got["template_sections"] == [] and got["template_required_fields"] == []
    assert got["template_read_error"] and "503" in got["template_read_error"]
    assert "not because the shell brought nothing in" in got["note"]


def test_create_flow_any_born_live_kinds_carry_no_template_inventory() -> None:
    """The control: a list/dataset/case has no scaffold to inventory and must not invent one."""
    c = _CreateProcessClient()
    got = create_flow_any(c, "list", "Urgency Levels").as_tool_result()
    assert got["from_template"] is False and got["template_sections"] == []
    assert "note" not in got


# ---- S3, the siblings: no write tool's SUCCESS payload may echo opaque node ids ----------------


_OPAQUE_ID = __import__("re").compile(
    r"\b(Column|Activity|Field|Row|Permission|Resource|Expression|Node|Event|Criteria|Property)"
    r"_[A-Za-z0-9]{4,}"
)


def _wide_specs(n: int = 37) -> list[FieldSpec]:
    return [FieldSpec(name=f"New {i:02d}", type=FieldType.TEXT) for i in range(n)]


def _sibling_payloads() -> dict[str, dict]:
    """Every write orchestration whose report could grow with the field or step count, run over
    the same 37-field / 6-step draft `apply_step_permissions` blew up on."""
    import copy

    from kfforge.client import (
        apply_fields_full,
        apply_layout,
        apply_workflow,
    )
    from kfforge.graph import progressive_matrix

    d = _wide_matrix_draft()
    names = [f"Field {i:02d}" for i in range(37)]
    runs = {
        "apply_step_permissions":
            lambda c: apply_step_permissions(c, "F1", progressive_matrix(d, _WIDE_OWNERS)),
        "apply_fields":
            lambda c: apply_fields(c, "process", "F1", _wide_specs()),
        "apply_fields_full":
            lambda c: apply_fields_full(c, "process", "F1", _wide_specs(),
                                        [("Intake", [s.name for s in _wide_specs()])]),
        "apply_workflow":
            lambda c: apply_workflow(c, "F1", [(f"Step {i}", None) for i in range(6)]),
        "delete_fields":
            lambda c: delete_fields(c, "F1", tuple(names), ()),
        "rename_form_fields":
            lambda c: rename_form_fields(c, "F1", {n: f"Renamed {n}" for n in names}),
        "apply_required":
            lambda c: apply_required(c, "F1", tuple(names)),
        "run_doctor":
            lambda c: run_doctor(c, "F1"),
        "apply_layout":
            lambda c: apply_layout(c, "F1", {"Intake": [[(names[i], 0, 2), (names[i + 1], 2, 4),
                                                        (names[i + 2], 4, 6)]
                                                       for i in range(0, 12, 3)]}),
    }
    out: dict[str, dict] = {}
    for label, run in runs.items():
        rep = run(FakeClient(copy.deepcopy(d)))
        assert not isinstance(rep, Err), f"{label} fixture is broken: {rep}"
        out[label] = rep.as_tool_result() if hasattr(rep, "as_tool_result") else rep
    return out


@pytest.mark.parametrize("label", sorted(_sibling_payloads()))
def test_no_write_tools_success_payload_echoes_an_opaque_node_id(label: str) -> None:
    """The finding generalised: an id-only report is unreadable to the agent that has to act on
    it, and it is what made ONE call cost ~15k tokens. This is the standing guard across the
    whole orchestration surface, not just the tool that was caught."""
    import json

    body = json.dumps(_sibling_payloads()[label])
    hits = sorted(set(_OPAQUE_ID.findall(body)))
    assert not hits, f"{label}'s success payload names raw node ids: {hits}"


@pytest.mark.parametrize("label", sorted(_sibling_payloads()))
def test_every_sibling_payload_stays_small_at_37_fields(label: str) -> None:
    """apply_step_permissions was the SOLE outlier — 18,396 bytes where every sibling was under
    2.5k. Pinned so a new bucket cannot quietly reintroduce the same cost."""
    import json

    body = json.dumps(_sibling_payloads()[label])
    assert len(body) < 3_000, f"{label} returned {len(body)} bytes for 37 fields"


# ---- operator-reported bugs (2026-08-20) ------------------------------------------------------

def test_get_assignee_percent_encodes_a_thai_query() -> None:
    """Operator-reported: a Thai name died with UnicodeEncodeError — an EXCEPTION across the tool
    boundary, not an Err (doctrine 7). This engine is driven in Thai (the intake interview is a
    Thai script), so a non-ASCII assignee query is the NORMAL case, not an edge one."""
    seen: dict[str, str] = {}
    client = KfClient(KfConfig(key_id="k", key_secret="s", account="Ac1",
                               domain="dev-x.example.com", app_id="A1"))
    client._json = lambda m, u, d=None: seen.setdefault("url", u)      # type: ignore[assignment]

    client.get_assignee("สมชาย")

    seen["url"].encode("ascii")          # urllib does exactly this — it used to raise here
    assert "%E0%B8%AA" in seen["url"], seen["url"]
    assert "สมชาย" not in seen["url"]


def test_get_assignee_escapes_characters_that_would_truncate_the_query() -> None:
    """The quieter half of the same bug: a space or `&` in a name was not an error, it silently
    truncated or corrupted the query, so the search returned the wrong people."""
    seen: dict[str, str] = {}
    client = KfClient(KfConfig(key_id="k", key_secret="s", account="Ac1",
                               domain="dev-x.example.com", app_id="A1"))
    client._json = lambda m, u, d=None: seen.setdefault("url", u)      # type: ignore[assignment]

    client.get_assignee("a&b=c d")

    assert seen["url"].endswith("?q=a%26b%3Dc%20d"), seen["url"]


class _FakeRoleClient(KfClient):
    """An AppRole whose detail exposes Members + a nullable GroupCount, and no group LIST — the
    shape the live tenant actually returns."""

    def __init__(self, group_count: int | None = 0) -> None:
        self.detail = {"_id": "R1", "Name": "Tech", "Members": [], "UserCount": 0,
                       "GroupCount": group_count}
        self.body: dict[str, Any] | None = None
        self._count = group_count

    def get_app_role(self, role_id):                       # type: ignore[override]
        d = dict(self.detail)
        d["GroupCount"] = self._count
        return d

    def put_app_role(self, role_id, body, app_id=None):    # type: ignore[override]
        self.body = body
        if isinstance(self._count, int) and body.get("Groups"):
            self._count = len(body["Groups"])
        return {"ok": True}


def test_add_role_users_writes_groups_under_their_own_key() -> None:
    """Operator-reported: a group object placed in `Users` is refused UserDoesNotExistError. The
    body must carry BOTH keys — Users for people, Groups for groups."""
    c = _FakeRoleClient()
    rep = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)

    assert isinstance(rep, RoleUsersReport)
    assert c.body is not None
    assert c.body["Groups"] == [{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}]
    assert c.body["Users"] == [], "a group must never be smuggled into the Users array"
    assert rep.groups_added == ("everyone",)
    assert rep.as_tool_result()["isError"] is False


def test_add_role_users_reports_a_group_it_cannot_prove_landed() -> None:
    """THE RULE, applied to the weaker group read-back: GroupCount is the only signal this tenant
    exposes. If it does not move, the group is WRITTEN BUT UNPROVEN — never reported as success."""
    c = _FakeRoleClient(group_count=None)          # tenant exposes no usable count
    rep = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)

    assert isinstance(rep, RoleUsersReport)
    assert rep.groups_added == () and rep.groups_unverified == ("everyone",)
    assert rep.as_tool_result()["isError"] is True
    assert "UNPROVEN" in (rep.groups_note or "")


def test_add_role_users_refuses_a_malformed_group_before_any_write() -> None:
    c = _FakeRoleClient()
    got = apply_add_role_users(c, "R1", groups=[{"Name": "Everyone"}],     # no _id
                               confirm_group_notification=True)

    assert isinstance(got, Err) and got.kind == "verify"
    assert "'_id'" in got.message or "_id" in got.message
    assert c.body is None, "a refusal must not write first"


def test_add_role_users_still_requires_at_least_one_grant() -> None:
    got = apply_add_role_users(_FakeRoleClient(), "R1")
    assert isinstance(got, Err) and "groups" in got.message


def test_group_grant_is_refused_without_explicit_confirmation() -> None:
    """A group grant NOTIFIES every member, cannot be recalled, and cannot be undone (membership
    writes are add-only — CLAUDE.md Members first, learned the hard way 2026-08-20). It is the one
    effect on this surface that reaches PEOPLE rather than the graph, so it fails CLOSED."""
    c = _FakeRoleClient()

    got = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}])

    assert isinstance(got, Err) and got.kind == "verify"
    assert "Everyone" in got.message, "must name what it refused to grant"
    assert "CANNOT BE UNDONE" in got.message
    assert "user_query" in got.message, "must name the safe way to test this tool"
    assert c.body is None, "a refusal must not write first"


def test_group_grant_proceeds_once_confirmed() -> None:
    """The flag is a speed bump, not a wall — an intended grant still works."""
    c = _FakeRoleClient()

    rep = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)

    assert isinstance(rep, RoleUsersReport) and rep.groups_added == ("everyone",)
    assert c.body is not None and c.body["Groups"]


def test_granting_a_single_user_needs_no_confirmation() -> None:
    """The safe path stays frictionless: adding one named person notifies only that person."""
    c = _FakeRoleClient()
    c.get_assignee = lambda q: [{"_id": "U1", "Kind": "User", "Name": q}]  # type: ignore[assignment]

    rep = apply_add_role_users(c, "R1", user_query="Somchai")

    assert isinstance(rep, RoleUsersReport)
    assert c.body is not None and c.body["Users"] == [{"_id": "U1", "Kind": "User",
                                                       "Name": "Somchai"}]
    assert "Groups" not in c.body, "a user-only grant must never write a Groups key"


def test_group_regrant_is_blocked_when_group_count_already_present() -> None:
    """FIX: `_existing_group_list` is always `[]` on this tenant (no group LIST field), so the
    idempotency check based on it never actually blocked a repeat write — every identical call
    re-issued the SAME Groups write, re-fanning the notification out to every member all over
    again (the 2026-08-20 incident). The guard now gates on `GroupCount`: once it shows a group
    already present, a second identical grant must be refused, not resent."""
    c = _FakeRoleClient()
    first = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)
    assert isinstance(first, RoleUsersReport) and first.groups_added == ("everyone",)
    assert c.body is not None and c.body.get("Groups")
    c.body = None  # reset so a second write would be visible

    second = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)

    assert isinstance(second, RoleUsersReport)
    assert c.body is None, "GroupCount already shows a group present — must not re-issue the write"
    # A refused group lands in its OWN bucket, never `groups_already_present` — GroupCount cannot
    # prove the requested group is the one already there, so we never claim it is present.
    assert second.groups_refused == ("everyone",)
    assert second.groups_already_present == ()
    assert "force_regrant_groups" in (second.groups_note or ""), second.groups_note


def test_group_regrant_refusal_survives_a_mixed_call_with_new_users() -> None:
    """The refused group must land in `groups_refused` on EVERY path. A mixed call (new user
    grants alongside the blocked group) skips the groups-only early return and exits through the
    final report — which used to drop the bucket, leaving the group in no counted bucket at all."""
    c = _FakeRoleClient(group_count=1)

    rep = apply_add_role_users(
        c, "R1", user_ids=[{"_id": "U9", "Kind": "User", "Name": "Somchai"}],
        groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)

    assert isinstance(rep, RoleUsersReport)
    assert c.body is not None, "the user grant must still be written"
    assert "Groups" not in c.body, "the blocked group must not ride along on the user write"
    assert rep.groups_refused == ("everyone",)
    assert rep.groups_added == () and rep.groups_already_present == ()
    assert "force_regrant_groups" in (rep.groups_note or ""), rep.groups_note


def test_group_regrant_proceeds_with_explicit_override() -> None:
    """The guard is a speed bump, not a wall — `force_regrant_groups=True` still writes."""
    c = _FakeRoleClient()
    apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True)
    c.body = None

    rep = apply_add_role_users(
        c, "R1", groups=[{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}],
        confirm_group_notification=True, force_regrant_groups=True)

    assert isinstance(rep, RoleUsersReport)
    assert c.body is not None and c.body.get("Groups"), "override must still issue the write"
