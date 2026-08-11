"""Unit tests for kfforge.pages_live — the page/app-draft live orchestration layer (Node G).

NO network: a FakeClient(KfClient) intercepts every page/app HTTP method, same pattern as
tests/test_client.py's own FakeClient for flow drafts.
"""
from __future__ import annotations

from typing import Any

from kfforge.client import Err, KfClient, KfConfig
from kfforge.pages import new_page_graph
from kfforge.pages_live import (
    NavigationReport,
    PageBuildReport,
    PageBuildStep,
    PageReport,
    apply_navigation,
    apply_page_build,
    create_page_flow,
)

DEV = KfConfig(key_id="k", key_secret="s", account="Acc", domain="dev-x.example.com", app_id="App")


def _seed_app_draft() -> dict:
    return {
        "Root": "Model_Sample01",
        "_meta_version": "v1",
        "Model_Sample01": {
            "Id": "Model_Sample01", "Kind": "Application", "FlowType": "Application",
            "Name": "Sample Application", "DefaultPage": "Page_Sample01",
            "Application::Navigation": ["Navigation_Sample01"],
        },
        "Navigation_Sample01": {
            "Id": "Navigation_Sample01", "Kind": "Navigation", "Name": "Requester Navigation",
            "Application": "Model_Sample01", "Navigation::Menu": ["Menu_Sample01"],
        },
        "Menu_Sample01": {
            "Id": "Menu_Sample01", "Kind": "Menu", "Name": "Overview",
            "Navigation": "Navigation_Sample01", "Menu::FieldMapping": ["FieldMapping_Sample01"],
        },
        "FieldMapping_Sample01": {
            "Id": "FieldMapping_Sample01", "Kind": "FieldMapping", "Name": "Page",
            "Menu": "Menu_Sample01", "FieldMapping::Property": ["Property_Sample01"],
        },
        "Property_Sample01": {
            "Id": "Property_Sample01", "Kind": "Property", "Type": "Page",
            "Value": "Page_Sample01", "FieldMapping": "FieldMapping_Sample01",
        },
    }


class FakePageClient(KfClient):
    """KfClient with the page/app HTTP verbs intercepted."""

    def __init__(self, *, pages: dict[str, dict[str, Any]] | None = None,
                app_draft: dict[str, Any] | None = None) -> None:
        super().__init__(DEV)
        self.pages: dict[str, dict[str, Any]] = pages if pages is not None else {}
        self.page_drafts: dict[str, dict[str, Any]] = {}
        self.app_draft = app_draft if app_draft is not None else _seed_app_draft()
        self.page_puts = 0
        self.app_puts = 0
        self.page_publishes: list[str] = []
        self.app_published = False
        self._counter = 0

    # --- pages ---
    def create_page(self, app_id, name):  # type: ignore[override]
        self._counter += 1
        graph = new_page_graph(name)
        pid = graph["Root"]  # the id new_page_graph itself minted for the Page node
        self.pages[pid] = {"_id": pid, "Name": name, "Status": "Live"}
        graph["_meta_version"] = "v1"
        self.page_drafts[pid] = graph
        return pid

    def list_pages(self, app_id):  # type: ignore[override]
        return list(self.pages.values())

    def get_page_draft(self, app_id, page_id):  # type: ignore[override]
        if page_id not in self.page_drafts:
            return Err("http", f"no such page {page_id}", 404)
        return self.page_drafts[page_id]

    def put_page_draft(self, app_id, page_id, new, expect_version):  # type: ignore[override]
        live = self.page_drafts[page_id].get("_meta_version")
        if expect_version is not None and live != expect_version:
            return Err("conflict", f"expected {expect_version!r}, live {live!r}")
        self.page_puts += 1
        new["_meta_version"] = "v2"
        self.page_drafts[page_id] = new
        return new

    def publish_page(self, app_id, page_id):  # type: ignore[override]
        self.page_publishes.append(page_id)

    # --- app / navigation ---
    def get_app_draft(self, app_id):  # type: ignore[override]
        return self.app_draft

    def put_app_draft(self, app_id, new, expect_version):  # type: ignore[override]
        live = self.app_draft.get("_meta_version")
        if expect_version is not None and live != expect_version:
            return Err("conflict", f"expected {expect_version!r}, live {live!r}")
        self.app_puts += 1
        new["_meta_version"] = "v2"
        self.app_draft = new
        return new

    def publish_app(self, app_id):  # type: ignore[override]
        self.app_published = True


# ---- create_page_flow --------------------------------------------------------------------------

def test_create_page_flow_verifies_via_list_route() -> None:
    c = FakePageClient()
    rep = create_page_flow(c, "App1", "Sample Page")
    assert isinstance(rep, PageReport)
    assert rep.verified is True and rep.page_id is not None
    assert rep.as_tool_result()["isError"] is False


def test_create_page_flow_reports_unverified_when_list_route_disagrees() -> None:
    class Lying(FakePageClient):
        def list_pages(self, app_id):  # type: ignore[override]
            return []  # the create "worked" but the list route disagrees

    c = Lying()
    rep = create_page_flow(c, "App1", "Sample Page")
    assert isinstance(rep, PageReport)
    assert rep.verified is False and rep.page_id is None
    assert rep.as_tool_result()["isError"] is True


# ---- apply_page_build ---------------------------------------------------------------------------

def test_apply_page_build_container_then_widget() -> None:
    c = FakePageClient()
    page_id = c.create_page("App1", "Sample Page")
    steps = [
        PageBuildStep("container", {"parent_id": "Container001", "name": "Banner"}),
        PageBuildStep("widget", {"container_id": "Container001", "widget": "general/label",
                                 "config": {"title": "Hello"}}),
    ]
    rep = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(rep, PageBuildReport)
    assert len(rep.applied) == 2
    assert rep.verified == rep.applied, "both steps must be confirmed present on the read-back"
    assert rep.missing == ()
    assert rep.as_tool_result()["isError"] is False
    assert rep.node_counts.get("Container", 0) >= 2  # root + the new Banner container
    assert rep.node_counts.get("Component", 0) >= 1
    assert c.page_puts == 1, "every step must land in ONE guarded PUT, not one per step"


def test_apply_page_build_popup_widget_then_event_wires_open_popup() -> None:
    """#22: a popup + a button built in one PageBuildStep list is inert on its own -- a follow-up
    "event" step is what actually lets the button open the popup, dispatched the same way
    container/widget/popup already are."""
    c = FakePageClient()
    page_id = c.create_page("App1", "Sample Page")
    steps = [
        PageBuildStep("popup", {"name": "Detail Popup"}),
        PageBuildStep("widget", {"container_id": "Container001", "widget": "general/button",
                                 "config": {}}),
    ]
    rep = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(rep, PageBuildReport)
    assert rep.missing == ()

    draft = c.get_page_draft("App1", page_id)
    popup_id = next(nid for nid, node in draft.items()
                    if isinstance(node, dict) and node.get("Kind") == "Popup")
    button_comp = next(nid for nid, node in draft.items()
                       if isinstance(node, dict) and node.get("Kind") == "Component"
                       and node.get("Script", {}).get("web") == "general/button")
    button_container = draft[button_comp]["Container"]

    steps2 = [PageBuildStep("event", {"container_id": button_container, "type": "OpenPopup",
                                      "popup_id": popup_id})]
    rep2 = apply_page_build(c, "App1", page_id, steps2)
    assert isinstance(rep2, PageBuildReport)
    assert len(rep2.applied) == 1
    assert rep2.verified == rep2.applied, "the event step must be confirmed present on read-back"
    assert rep2.missing == ()
    assert rep2.as_tool_result()["isError"] is False
    assert rep2.node_counts.get("EventMapping", 0) == 1


def test_apply_page_build_detects_an_event_mapping_silently_dropped_by_the_write() -> None:
    """Same silent-discard class as the widget/style cases: the PUT succeeds but the EventMapping
    node itself never actually lands on the read-back."""
    class DroppingEvent(FakePageClient):
        def put_page_draft(self, app_id, page_id, new, expect_version):  # type: ignore[override]
            self.page_puts += 1
            trimmed = {k: v for k, v in new.items() if not (isinstance(v, dict)
                      and v.get("Kind") == "EventMapping")}  # the EventMapping silently vanishes
            trimmed["_meta_version"] = "v2"
            self.page_drafts[page_id] = trimmed
            return trimmed

    c = DroppingEvent()
    page_id = c.create_page("App1", "Sample Page")
    steps = [PageBuildStep("popup", {"name": "Detail Popup"})]
    rep = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(rep, PageBuildReport) and rep.missing == ()
    draft = c.get_page_draft("App1", page_id)
    popup_id = next(nid for nid, node in draft.items()
                    if isinstance(node, dict) and node.get("Kind") == "Popup")

    steps2 = [PageBuildStep("event", {"container_id": "Container001", "type": "OpenPopup",
                                      "popup_id": popup_id})]
    rep2 = apply_page_build(c, "App1", page_id, steps2, publish=True)
    assert isinstance(rep2, PageBuildReport)
    assert rep2.verified == ()
    assert len(rep2.missing) == 1
    assert rep2.as_tool_result()["isError"] is True
    assert rep2.published is False, "must never publish when a step failed to verify"
    assert c.page_publishes == []


def test_apply_page_build_detects_an_event_mapping_property_silently_dropped_by_the_write() -> None:
    """code-review finding: the EventMapping node is only the SHELL — the real payload (the
    target popup id, or the JS text) lives on a separate Property node
    (EventMapping::Property). A write that keeps the empty shell but drops that Property must
    NOT read as verified — same "shell vs substance" trap the widget branch's own check
    already guards against (see pages_live.py's own comment on the "event" step check)."""
    class DroppingEventProperty(FakePageClient):
        def put_page_draft(self, app_id, page_id, new, expect_version):  # type: ignore[override]
            self.page_puts += 1
            trimmed = {k: v for k, v in new.items() if not (isinstance(v, dict)
                      and v.get("Kind") == "Property"
                      and v.get("EventMapping") is not None)}  # only the payload vanishes
            trimmed["_meta_version"] = "v2"
            self.page_drafts[page_id] = trimmed
            return trimmed

    c = DroppingEventProperty()
    page_id = c.create_page("App1", "Sample Page")
    steps = [PageBuildStep("popup", {"name": "Detail Popup"})]
    rep = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(rep, PageBuildReport) and rep.missing == ()
    draft = c.get_page_draft("App1", page_id)
    popup_id = next(nid for nid, node in draft.items()
                    if isinstance(node, dict) and node.get("Kind") == "Popup")

    steps2 = [PageBuildStep("event", {"container_id": "Container001", "type": "OpenPopup",
                                      "popup_id": popup_id})]
    rep2 = apply_page_build(c, "App1", page_id, steps2, publish=True)
    assert isinstance(rep2, PageBuildReport)
    assert rep2.verified == (), "the EventMapping shell surviving alone must not read as verified"
    assert len(rep2.missing) == 1
    assert rep2.as_tool_result()["isError"] is True
    assert rep2.published is False
    assert c.page_publishes == []


def test_apply_page_build_event_missing_popup_id_raises_offline() -> None:
    """Same offline-reject discipline as the widget binding check: a required arm argument
    missing must be rejected BEFORE any write, never shipped as a dead click."""
    c = FakePageClient()
    page_id = c.create_page("App1", "Sample Page")
    steps = [PageBuildStep("event", {"container_id": "Container001", "type": "OpenPopup"})]
    got = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.page_puts == 0


def test_apply_page_build_detects_a_widget_silently_dropped_by_the_write() -> None:
    """Node G review F1: a PUT that 200s while a widget never actually lands on the read-back
    must NOT read as success. Simulates exactly that — put_page_draft "succeeds" (200) but the
    stored draft silently drops one node, mirroring test_client.py's own Dropping() pattern."""
    class DroppingWidget(FakePageClient):
        def put_page_draft(self, app_id, page_id, new, expect_version):  # type: ignore[override]
            self.page_puts += 1
            trimmed = {k: v for k, v in new.items() if not (isinstance(v, dict)
                      and v.get("Kind") == "Component")}  # the widget's Component silently vanishes
            trimmed["_meta_version"] = "v2"
            self.page_drafts[page_id] = trimmed
            return trimmed

    c = DroppingWidget()
    page_id = c.create_page("App1", "Sample Page")
    steps = [PageBuildStep("widget", {"container_id": "Container001", "widget": "general/label",
                                      "config": {"title": "Hello"}})]
    rep = apply_page_build(c, "App1", page_id, steps, publish=True)
    assert isinstance(rep, PageBuildReport)
    assert rep.verified == ()
    assert len(rep.missing) == 1
    assert rep.as_tool_result()["isError"] is True
    assert rep.published is False, "must never publish when a step failed to verify"
    assert c.page_publishes == []


def test_apply_page_build_detects_a_style_value_that_never_landed() -> None:
    """Same silent-discard class, for a style step: the PUT succeeds but the Style.Value never
    actually reflects the requested prop."""
    class DroppingStyle(FakePageClient):
        def put_page_draft(self, app_id, page_id, new, expect_version):  # type: ignore[override]
            self.page_puts += 1
            stripped = {}
            for k, v in new.items():
                if isinstance(v, dict) and v.get("Kind") == "Style":
                    v = {**v}
                    v.pop("Value", None)  # the style write silently never lands
                stripped[k] = v
            stripped["_meta_version"] = "v2"
            self.page_drafts[page_id] = stripped
            return stripped

    c = DroppingStyle()
    page_id = c.create_page("App1", "Sample Page")
    # "Body Container" is the virgin page's own root container Name (shapes/page_virgin.json)
    steps = [PageBuildStep("style", {"rules": {"Body Container": {"Container.Background": "#fff"}}})]
    rep = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(rep, PageBuildReport)
    assert rep.verified == ()
    assert len(rep.missing) == 1
    assert rep.as_tool_result()["isError"] is True


def test_apply_page_build_view_table_needs_full_binding_or_raises_offline() -> None:
    """Placeholders CANNOT ship (THE RULE) — a widget missing its binding config must be
    rejected offline, before any write."""
    c = FakePageClient()
    page_id = c.create_page("App1", "Sample Page")
    steps = [PageBuildStep("widget", {"container_id": "Container001", "widget": "view/table",
                                      "config": {}})]
    got = apply_page_build(c, "App1", page_id, steps)
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.page_puts == 0


def test_apply_page_build_publishes_when_asked() -> None:
    c = FakePageClient()
    page_id = c.create_page("App1", "Sample Page")
    rep = apply_page_build(c, "App1", page_id, [], publish=True)
    assert isinstance(rep, PageBuildReport)
    assert rep.published is True
    assert c.page_publishes == [page_id]


# ---- apply_navigation ---------------------------------------------------------------------------

def test_apply_navigation_adds_menu_and_verifies() -> None:
    c = FakePageClient()
    rep = apply_navigation(c, "App1", "Page_New", "Sample Tab", unify=False)
    assert isinstance(rep, NavigationReport)
    assert rep.menu_id is not None
    assert rep.as_tool_result()["isError"] is False
    assert c.app_puts == 1


def test_apply_navigation_unifies_every_navigation_when_asked() -> None:
    app = _seed_app_draft()
    app["Navigation_Sample02"] = {
        "Id": "Navigation_Sample02", "Kind": "Navigation", "Name": "Admin Navigation",
        "Application": "Model_Sample01", "Navigation::Menu": ["Menu_Sample01"],
    }
    app["Model_Sample01"]["Application::Navigation"].append("Navigation_Sample02")
    c = FakePageClient(app_draft=app)

    rep = apply_navigation(c, "App1", "Page_New", "Sample Tab", unify=True)
    assert isinstance(rep, NavigationReport)
    assert rep.menu_id is not None
    nav2_menus = c.app_draft["Navigation_Sample02"]["Navigation::Menu"]
    assert rep.menu_id in nav2_menus, "unify=True must point EVERY Navigation at the new menu too"


def test_apply_navigation_no_navigation_node_rejected_before_any_write() -> None:
    c = FakePageClient(app_draft={"Root": "M1", "_meta_version": "v1",
                                  "M1": {"Id": "M1", "Kind": "Application"}})
    got = apply_navigation(c, "App1", "Page_New", "Sample Tab")
    assert isinstance(got, Err) and got.kind == "verify"
    assert c.app_puts == 0
