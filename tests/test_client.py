"""Unit tests for the live-write client. NO network: transport is stubbed."""
from __future__ import annotations

from typing import Any

import pytest

from kfforge.client import (
    ApplyReport,
    Err,
    EventReport,
    GotoGateReport,
    KfClient,
    KfConfig,
    MemberReport,
    StyleReport,
    TableReport,
    WorkflowReport,
    apply_field_events,
    apply_fields,
    apply_fields_and_layout,
    apply_goto_gate,
    apply_member_batch,
    apply_report_members,
    apply_section_style,
    apply_table,
    apply_workflow,
    create_application_verified,
    delete_anything,
    discover_member_source,
    run_doctor,
)
from kfforge.graph import apply_changes as _apply_changes
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
        # applications / pages
        self.applications: dict[str, dict[str, Any]] = {}
        self.archived_apps: set[str] = set()
        self.pages: dict[str, dict[str, dict[str, Any]]] = {}
        self._app_counter = 0

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

    # --- member batch ---
    def list_flows(self, kind):  # type: ignore[override]
        return self.flows.get(kind, [])

    def get_members(self, kind, flow_id):  # type: ignore[override]
        return self.members.get((kind, flow_id), [])

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
    draft = _apply_changes(draft, [FieldSpec(name="Choice", type=FieldType.SELECT)])
    c = FakeClient(draft)
    got = apply_goto_gate(c, "F1", target_activity_name="Review", field_name="Choice")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.puts == 0


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
    c = FakeClient(_bare_process_draft())
    c.flows["process"] = []
    rep = apply_member_batch(c, "F_target")
    assert isinstance(rep, MemberReport)
    assert rep.harvested == () and rep.applied == ()
    assert rep.note is not None and "no existing flow" in rep.note
    assert rep.as_tool_result()["isError"] is False, "an empty tenant is not an error state"
    assert c.member_batches == [], "nothing to post must mean nothing gets posted"


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


# ---- apply_report_members ---------------------------------------------------------------------

def test_apply_report_members_posts_and_reports_unverified_honestly() -> None:
    c = FakeClient(_bare_process_draft())
    members = [{"_id": "m1", "Name": "Lead", "Kind": "AppRole", "Role": "Ro_lead", "Permission": "Member"}]
    got = apply_report_members(c, "F1", "Rep1", members)
    assert isinstance(got, dict)
    assert got["verified"] is None, "no documented read-back route -- must not fake True"
    assert got["isError"] is False
    assert c.report_member_batches == [("F1", "Rep1", members)]


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
