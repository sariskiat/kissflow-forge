"""Seam 2 of spec #10 (ticket #13): create_template_app — one call, fresh Template App carrying
the transplanted source template process, published end to end. Offline: transport stubbed (FakeClient),
the transplant itself is the real pure op over the real vendored shape.

Order under test is the proven build order (CLAUDE.md > Build order): create application ->
create process flow -> members FIRST -> write transplanted graph (assignees ride in it) ->
publish process -> publish app -> doctor read-back -> URL.
"""
from __future__ import annotations

from typing import Any

from test_client import FakeClient

from kfforge.client import Err, create_template_app

APP_NAME = "Sample Template App"


def _bare_process_draft() -> dict:
    return {
        "Root": "M1",
        "_meta_version": "v1",
        "M1": {"Id": "M1", "Kind": "Model", "Name": APP_NAME, "FlowType": "Process"},
    }


class _TemplateAppClient(FakeClient):
    """FakeClient plus the app-lifecycle verbs create_template_app composes, with a call log so
    ordering (members BEFORE the graph write) is assertable, and per-step failure injection.
    `scoped_to_app` really re-scopes the config (unlike a bare `return self`) so a tool that
    forgets to scope onto the created app is caught by the role-scope assertions below."""

    def __init__(self) -> None:
        super().__init__(_bare_process_draft())
        self.calls: list[str] = []
        self.create_application_err: Err | None = None
        self.put_draft_err: Err | None = None
        self.drop_put: bool = False          # PUT 200s but persists nothing (silent-discard trap)
        self.drop_member_batch: bool = False  # POST 200s but the roster read-back stays empty
        self.app_draft_err: Err | None = None
        self.detail_status: str = "Live"
        self.app_published: list[str] = []

    # --- account-level ---
    def create_application(self, name: str):  # type: ignore[override]
        if self.create_application_err is not None:
            return self.create_application_err
        self.calls.append("create_application")
        return super().create_application(name)

    def scoped_to_app(self, app_id: str):  # type: ignore[override]
        from dataclasses import replace
        self.calls.append(f"scoped_to_app:{app_id}")
        self._cfg = replace(self._cfg, app_id=app_id)
        return self

    # --- app-scoped ---
    def create_app_role(self, name: str, app_id: str | None = None):  # type: ignore[override]
        self.calls.append("create_app_role")
        return super().create_app_role(name, app_id)

    def create_flow(self, kind: str, name: str):  # type: ignore[override]
        self.calls.append(f"create_flow:{kind}:{name}")
        return "F1"

    def post_member_batch(self, kind, flow_id, members):  # type: ignore[override]
        self.calls.append("post_member_batch")
        if self.drop_member_batch:
            self.member_batches.append((kind, flow_id, list(members)))
            return {"ok": True}  # 200, but the roster read-back will come back empty
        return super().post_member_batch(kind, flow_id, members)

    def put_draft(self, kind, flow_id, new, expect_version):  # type: ignore[override]
        if self.put_draft_err is not None:
            return self.put_draft_err
        self.calls.append("put_draft")
        if self.drop_put:
            echoed = dict(new)
            echoed["_meta_version"] = "v2"
            return echoed  # 200-shaped echo, self.draft untouched — the silent-discard trap
        return super().put_draft(kind, flow_id, new, expect_version)

    def publish(self, kind, flow_id):  # type: ignore[override]
        self.calls.append("publish")
        return super().publish(kind, flow_id)

    def get_flow_detail(self, kind, flow_id):  # type: ignore[override]
        return {"_id": flow_id, "Status": self.detail_status}

    def publish_app(self, app_id: str):  # type: ignore[override]
        self.calls.append("publish_app")
        self.app_published.append(app_id)
        return None

    def get_app_draft(self, app_id: str):  # type: ignore[override]
        if self.app_draft_err is not None:
            return self.app_draft_err
        return {"_meta_version": "appv2"}


def _run(c: _TemplateAppClient) -> dict[str, Any] | Err:
    return create_template_app(c, APP_NAME)


# ---- happy path -------------------------------------------------------------------------------


def test_happy_path_reports_every_promised_key() -> None:
    c = _TemplateAppClient()
    got = _run(c)
    assert not isinstance(got, Err), f"unexpected Err: {got}"
    assert got["isError"] is False
    assert got["app_id"] == "App_1"
    assert got["flow_id"] == "F1"
    assert got["role_id"], "the created dev AppRole id must be reported"
    assert got["process_status"] == "Live"
    assert c.app_published == ["App_1"], "the app-level publish must actually run"
    # doctor read-back is part of the response, not a separate call the caller must remember
    assert isinstance(got["doctor"], dict)
    assert "problems" in got["doctor"] and "ok" in got["doctor"]
    # builder URLs, derived from the dev-guarded config base — labeled honestly: the /view/app
    # pattern is DERIVED from captured /view/... links, never itself captured off the builder
    assert got["app_url"] == "https://dev-x.example.com/view/app/App_1"
    assert got["process_url"] == "https://dev-x.example.com/view/process/F1"
    assert got["url_verified"] is False
    # graph-write read-back audit: every transplanted node re-read off the live draft, counted
    expected_nodes = sum(1 for k in c.draft if k not in ("Root", "_meta_version"))
    assert got["graph_nodes_verified"] == expected_nodes


def test_role_is_scoped_to_the_created_app_not_the_session_default() -> None:
    c = _TemplateAppClient()
    got = _run(c)
    assert not isinstance(got, Err)
    assert c.app_roles and c.app_roles[0]["_application_id"] == "App_1", (
        "the AppRole must be created under the app the tool just made — a role scoped to the "
        "session-default app means scoped_to_app never happened"
    )


def test_scoped_to_app_mints_a_new_client_with_the_same_identity() -> None:
    from kfforge.client import KfClient, KfConfig

    cfg = KfConfig(key_id="k", key_secret="s", account="A",
                   domain="dev-x.example.com", app_id="App")
    assert isinstance(cfg, KfConfig)
    c = KfClient(cfg)
    scoped = c.scoped_to_app("Other")
    assert scoped is not c
    assert scoped._cfg.app_id == "Other"
    assert scoped._cfg.key_id == "k" and scoped._cfg.key_secret == "s"
    assert scoped._cfg.domain == cfg.domain, "the dev-guarded domain must ride along unchanged"


def test_members_are_granted_before_the_graph_write() -> None:
    c = _TemplateAppClient()
    got = _run(c)
    assert not isinstance(got, Err)
    assert "post_member_batch" in c.calls and "put_draft" in c.calls
    assert c.calls.index("post_member_batch") < c.calls.index("put_draft"), (
        "members must land BEFORE the transplanted graph (assignees ride in that write) — "
        "CLAUDE.md > Members first"
    )


def test_transplanted_graph_lands_with_assignee_on_the_created_role() -> None:
    c = _TemplateAppClient()
    got = _run(c)
    assert not isinstance(got, Err)
    resources = [
        v for v in c.draft.values()
        if isinstance(v, dict) and v.get("Kind") == "Resource" and v.get("ValueType") == "AppRole"
    ]
    assert resources, "the transplanted graph must carry the workflow's Resource assignee node"
    assert all(r.get("Value") == got["role_id"] for r in resources), (
        "every UserTask assignee must be re-pointed at the created dev AppRole"
    )
    activities = [
        v for v in c.draft.values() if isinstance(v, dict) and v.get("Kind") == "Activity"
    ]
    assert len(activities) == 5, "the full template carries 5 Activities (quirks included)"


# ---- failure paths ----------------------------------------------------------------------------


def test_duplicate_app_name_surfaces_the_platform_error_loud() -> None:
    c = _TemplateAppClient()
    c.create_application_err = Err(
        "http", "POST .../application -> FlowNameAlreadyExists", status=400
    )
    got = _run(c)
    assert isinstance(got, Err)
    assert "FlowNameAlreadyExists" in got.message
    assert not c.applications, "no app may exist after a refused create"
    assert not any(s.startswith("create_flow") for s in c.calls), (
        "nothing downstream may run after the create is refused — no auto-rename, no retry"
    )


def test_midway_failure_deletes_the_half_built_app() -> None:
    c = _TemplateAppClient()
    c.put_draft_err = Err("http", "PUT draft -> 500", status=500)
    got = _run(c)
    assert isinstance(got, Err)
    assert not c.applications, "a failed run must archive+delete the half-built app, not leak it"
    assert "App_1" in c.archived_apps, "application delete requires archive-first"


def test_process_publish_readback_not_live_fails_and_cleans_up() -> None:
    c = _TemplateAppClient()
    c.detail_status = "Draft"
    got = _run(c)
    assert isinstance(got, Err)
    assert got.kind == "verify"
    assert not c.applications


def test_silently_dropped_graph_write_is_caught_by_read_back() -> None:
    """The silent-discard trap this codebase exists to catch: a PUT that 200s and echoes the
    graph while persisting nothing must fail the run, not report success (THE RULE)."""
    c = _TemplateAppClient()
    c.drop_put = True
    got = _run(c)
    assert isinstance(got, Err)
    assert got.kind == "verify"
    assert not c.applications, "the half-built app must be cleaned up after the failed audit"


def test_failed_run_deletes_the_created_app_role_too() -> None:
    c = _TemplateAppClient()
    c.put_draft_err = Err("http", "PUT draft -> 500", status=500)
    got = _run(c)
    assert isinstance(got, Err)
    assert not c.app_roles, (
        "the '<name> Role' AppRole must not leak into the account after a failed run — an "
        "application delete is not proven to cascade to its scoped roles"
    )


def test_member_grant_not_landing_the_role_fails_and_cleans_up() -> None:
    c = _TemplateAppClient()
    c.drop_member_batch = True
    got = _run(c)
    assert isinstance(got, Err)
    assert got.kind == "verify"
    assert not c.applications
    assert not c.app_roles


def test_app_publish_readback_failure_cleans_up() -> None:
    c = _TemplateAppClient()
    c.app_draft_err = Err("http", "GET app draft -> 500", status=500)
    got = _run(c)
    assert isinstance(got, Err)
    assert got.kind == "verify"
    assert not c.applications
    assert not c.app_roles


def test_doctor_err_fails_the_run_and_cleans_up(monkeypatch) -> None:
    import kfforge.client as kfclient

    monkeypatch.setattr(kfclient, "run_doctor",
                        lambda *a, **k: Err("http", "doctor read failed"))
    c = _TemplateAppClient()
    got = _run(c)
    assert isinstance(got, Err)
    assert not c.applications
    assert not c.app_roles
