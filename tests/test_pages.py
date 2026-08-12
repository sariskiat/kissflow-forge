"""Unit spec for kfforge.pages: the page-graph builder driven by the shapes/ catalog.

Pure + offline: no network, no Kissflow calls, no real-app content (neutral names only, checked
repo-wide by test_p0_scaffold.py's blindness test).
"""
from __future__ import annotations

import pytest

from kfforge.pages import (
    WIDGET_REQUIRED_CONFIG,
    WIDGET_SLUGS,
    _instantiate,
    _keep_subset,
    add_container,
    add_event_mapping,
    add_popup,
    add_widget,
    load_shape,
    new_page_graph,
    page_summary,
    set_styles,
)


def _kind(draft: dict, kind: str) -> dict:
    return {k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _assert_backrefs_resolve(draft: dict) -> None:
    """Every `::`-list value must resolve to a real key in the SAME draft. Mirrors the pattern in
    tests/test_shapes.py's test_backrefs_resolve_within_same_template, applied to a BUILT draft
    instead of a static shape template."""
    problems = []
    for nid, node in draft.items():
        if not isinstance(node, dict):
            continue
        for key, val in node.items():
            if "::" not in key or not isinstance(val, list):
                continue
            for target in val:
                if isinstance(target, str) and target not in draft:
                    problems.append(f"{nid}.{key} -> missing {target!r}")
    assert not problems, "dangling back-refs:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# new_page_graph
# ---------------------------------------------------------------------------------------------

def test_new_page_graph_has_exactly_the_virgin_kinds() -> None:
    page = new_page_graph("Sample Page")
    kinds = sorted(v["Kind"] for v in page.values() if isinstance(v, dict))
    assert kinds == ["Container", "Page", "Style"]

    page_id = page["Root"]
    assert page[page_id]["Name"] == "Sample Page"
    assert page[page_id]["Page::Container"] == ["Container001"]
    assert page["Container001"]["Kind"] == "Container" and page["Container001"]["Type"] == "Body"
    assert page["Style001"]["Container"] == "Container001"
    _assert_backrefs_resolve(page)


def test_new_page_graph_is_pure_and_ids_are_fresh_each_call() -> None:
    a = new_page_graph("Sample Page")
    b = new_page_graph("Sample Page")
    assert a["Root"] != b["Root"], "two builds must not collide on the same page id"


# ---------------------------------------------------------------------------------------------
# add_container
# ---------------------------------------------------------------------------------------------

def test_add_container_wires_parent_and_layout() -> None:
    page = new_page_graph("Sample Page")
    page, cid = add_container(
        page, parent_id="Container001", name="Banner", layout={"Container.Row.Gap": "24px"}
    )
    assert cid in page["Container001"]["Container::Container"]
    assert page[cid]["Name"] == "Banner"
    sid = page[cid]["Container::Style"][0]
    assert page[sid]["Value"]["Container.Row.Gap"] == {"value": "24px"}
    _assert_backrefs_resolve(page)


def test_add_container_unknown_parent_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError):
        add_container(page, parent_id="Container_nope", name="Banner")


def test_add_container_does_not_mutate_input() -> None:
    page = new_page_graph("Sample Page")
    before = set(page)
    add_container(page, parent_id="Container001", name="Banner")
    assert set(page) == before, "add_container must not mutate its input draft"


# ---------------------------------------------------------------------------------------------
# add_widget: one representative per binding family, plus the repeater trap
# ---------------------------------------------------------------------------------------------

def test_add_widget_general_label_binds_text() -> None:
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="general/label", config={"title": "Hello there"}
    )
    comp = next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
                and v.get("Container") == host)
    assert comp["Script"]["web"] == "general/label"
    fm = next(page[fid] for fid in page[host]["Container::FieldMapping"] if page[fid]["Name"] == "title")
    prop = page[fm["FieldMapping::Property"][0]]
    assert prop["Value"] == "Hello there"
    _assert_backrefs_resolve(page)


def test_add_widget_view_table_binds_flow_view_trio() -> None:
    """Every value here must DIFFER from widget_view_table.json's own raw defaults (flow_type=
    "Form", flow_id="Flow_Sample01", view_id="myitems") -- asserting the shape's own placeholder
    back at itself would pass even if the config-write mechanism were deleted entirely."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="view/table",
        config={"flow_type": "Process", "flow_id": "Flow_abc123", "view_id": "allitems"},
    )
    fm_index = {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]]["Value"]
                for fid in page[host]["Container::FieldMapping"]}
    # Subset, not ==: view/table now also carries the display-config slots showform/steps/caption
    # (ticket #21); the load-bearing binding trio is what this test guards.
    assert fm_index["flow_type"] == "Process"
    assert fm_index["flow_id"] == "Flow_abc123"
    assert fm_index["view_id"] == "allitems"
    _assert_backrefs_resolve(page)


def test_add_widget_report_chart_binds_flow_report_trio() -> None:
    """widget_report_chart.json's own raw defaults are flow_id="Flow_Sample01", flow_type=
    "Process", report_id="Report_Sample01" -- using those exact strings as the test's OWN config
    would make the assertions pass even against an untouched, never-written clone. Every value
    below must differ from the shape default it binds."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="report/chart",
        config={"flow_id": "Flow_abc123", "flow_type": "Form", "report_id": "Report_r1"},
    )
    fm_index = {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]]["Value"]
                for fid in page[host]["Container::FieldMapping"]}
    assert fm_index["flow_id"] == "Flow_abc123"
    assert fm_index["flow_type"] == "Form"
    assert fm_index["report_id"] == "Report_r1"
    _assert_backrefs_resolve(page)


# ---------------------------------------------------------------------------------------------
# ticket #21: the three data-bound widget families must reach their full live binding --
# view/form (view_id/instance_id/activity_instance_id nullable), view/table (showform/steps/
# caption slots), report/chart (showHeader + a FilterParam-typed filterParameters Property). All
# three double-encode the flow/report binding into Component.Data as well as the FieldMapping set,
# same convention widget_metrics/widget_general_masterdetail already prove. Neutral string values
# only (blindness contract, test_p0_scaffold.py) -- this test guards the binding SHAPE, not the
# eval case's literal ids.
# ---------------------------------------------------------------------------------------------

def _host_component(page: dict, host: str) -> dict:
    return next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
               and v.get("Container") == host)


def _fm_values(page: dict, host: str) -> dict:
    return {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]].get("Value")
            for fid in page[host]["Container::FieldMapping"]}


def test_add_widget_view_form_reaches_live_binding_view_id_null() -> None:
    """The live working view/form ships view_id=null (and instance_id/activity_instance_id=null) --
    a binding that was unreachable while view_id was required+truthy (ticket #21). Building with
    only flow_type/flow_id must succeed and leave those three slots null, and flow_type/flow_id must
    ALSO mirror into Component.Data (double-encoded live)."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="view/form",
        config={"flow_type": "Process", "flow_id": "Flow_abc123"},
    )
    assert _fm_values(page, host) == {
        "flow_type": "Process", "flow_id": "Flow_abc123",
        "view_id": None, "instance_id": None, "activity_instance_id": None,
    }
    assert _host_component(page, host)["Data"] == {
        "manifest_id": "Form", "category": "view", "visualization_type": "form",
        "flow_type": "Process", "flow_id": "Flow_abc123",
    }
    _assert_backrefs_resolve(page)


def test_add_widget_view_form_still_requires_flow_id() -> None:
    """Relaxing view_id to optional must NOT relax flow_id: a view/form with no flow_id still binds
    to the shape's own placeholder id and must raise before any node is written."""
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="flow_id"):
        add_widget(page, container_id="Container001", widget="view/form",
                   config={"flow_type": "Process"})


def test_add_widget_view_table_reaches_live_binding_and_mirrors_data() -> None:
    """view/table's full live binding: the flow/view trio PLUS the display-config slots
    showform/steps/caption, with flow_type/flow_id/view_id mirrored into Component.Data. caption
    here differs from the shape default ("") so a silent no-op cannot make the assertion pass."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="view/table",
        config={"flow_type": "Process", "flow_id": "Flow_abc123", "view_id": "myitems",
                "showform": True, "steps": "all", "caption": "Neutral Caption"},
    )
    assert _fm_values(page, host) == {
        "flow_type": "Process", "flow_id": "Flow_abc123", "view_id": "myitems",
        "showform": True, "steps": "all", "caption": "Neutral Caption",
    }
    assert _host_component(page, host)["Data"] == {
        "manifest_id": "Table", "category": "view", "visualization_type": "table",
        "flow_type": "Process", "flow_id": "Flow_abc123", "view_id": "myitems",
    }
    _assert_backrefs_resolve(page)


def test_add_widget_view_table_still_requires_view_id() -> None:
    """Ticket #21 safe assumption: view_id stays REQUIRED for view/table (only view/form has a live
    example shipping null). Building view/table without it must still raise."""
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="view_id"):
        add_widget(page, container_id="Container001", widget="view/table",
                   config={"flow_type": "Process", "flow_id": "Flow_abc123"})


def test_add_widget_report_chart_reaches_live_binding_with_filterparam() -> None:
    """report/chart's full live binding: the flow/report trio, showHeader, and a filterParameters
    FieldMapping whose Property is Type:"FilterParam" (NOT the usual "Value") with Value:null. The
    trio also mirrors into Component.Data."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="report/chart",
        config={"flow_type": "Process", "flow_id": "Flow_abc123", "report_id": "Report_r1",
                "showHeader": False},
    )
    host_fms = {page[fid]["Name"]: page[fid] for fid in page[host]["Container::FieldMapping"]}
    fp_prop = page[host_fms["filterParameters"]["FieldMapping::Property"][0]]
    assert fp_prop["Type"] == "FilterParam"
    assert fp_prop.get("Value") is None
    fm = _fm_values(page, host)
    assert fm["flow_type"] == "Process"
    assert fm["flow_id"] == "Flow_abc123"
    assert fm["report_id"] == "Report_r1"
    assert fm["showHeader"] is False
    assert _host_component(page, host)["Data"] == {
        "manifest_id": "ChartReport", "category": "report", "report_type": "ChartReport",
        "visualization_type": "chart", "flow_type": "Process",
        "flow_id": "Flow_abc123", "report_id": "Report_r1",
    }
    _assert_backrefs_resolve(page)


def test_add_widget_report_chart_show_header_routes_when_overridden() -> None:
    """showHeader defaults false (live capture); a caller CAN flip it -- proving the slot is a real
    routed FieldMapping, not a static default read back at itself."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="report/chart",
        config={"flow_type": "Process", "flow_id": "Flow_abc123", "report_id": "Report_r1",
                "showHeader": True},
    )
    assert _fm_values(page, host)["showHeader"] is True


def test_add_widget_metrics_binds_stepmetrics_and_mirrors_component_data() -> None:
    """widget_metrics.json's own raw defaults are flow_type="Process", flow_id="Flow_Sample01",
    metrics_type="stepmetrics" -- every value here differs from that default so the assertions
    can only pass if add_widget's config actually got written, not merely left alone."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="metrics",
        config={"flow_type": "Form", "flow_id": "Flow_abc123", "metrics_type": "stepmetrics2"},
    )
    comp = next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
                and v.get("Container") == host)
    assert comp["Script"]["web"] == "metrics"
    # "write both" (widget_metrics.json note): the FieldMapping/Property AND the mirrored Data key.
    assert comp["Data"]["flow_id"] == "Flow_abc123"
    assert comp["Data"]["flow_type"] == "Form"
    fm_index = {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]]["Value"]
                for fid in page[host]["Container::FieldMapping"]}
    assert fm_index["metrics_type"] == "stepmetrics2"
    assert fm_index["flow_type"] == "Form"
    assert fm_index["flow_id"] == "Flow_abc123"
    _assert_backrefs_resolve(page)


def test_add_widget_masterdetail_binds_flow_view_trio_and_mirrors_component_data() -> None:
    """titleField/subTitleField/sortField are now required (WIDGET_REQUIRED_CONFIG) because their
    shape defaults ("Sample_Title_Field"/"Sample_Subtitle_Field") are placeholder ids, same class
    as flow_id/report_id. Every value below -- including these three -- differs from
    widget_general_masterdetail.json's own raw default for that key, so a config-write mechanism
    that silently no-ops cannot make these assertions pass by accident."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="general/masterdetail",
        config={
            "flow_type": "Process", "flow_id": "Flow_abc123", "view_id": "assigned",
            "titleField": "fld_title_x", "subTitleField": "fld_subtitle_y", "sortField": "fld_sort_z",
        },
    )
    fm_index = {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]].get("Value")
                for fid in page[host]["Container::FieldMapping"]}
    assert fm_index["flow_type"] == "Process"
    assert fm_index["flow_id"] == "Flow_abc123"
    assert fm_index["view_id"] == "assigned"
    assert fm_index["titleField"] == "fld_title_x"
    assert fm_index["subTitleField"] == "fld_subtitle_y"
    assert fm_index["sortField"] == "fld_sort_z"
    comp = next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
                and v.get("Container") == host)
    # widget_general_masterdetail.json's Data mirrors flow_id/view_id/flow_type (NOT the
    # titleField/subTitleField/sortField family -- those live only as FieldMapping/Property).
    assert comp["Data"]["flow_id"] == "Flow_abc123"
    assert comp["Data"]["view_id"] == "assigned"
    assert comp["Data"]["flow_type"] == "Process"
    _assert_backrefs_resolve(page)


def test_add_widget_repeater_registers_variable_refs_the_known_trap() -> None:
    """variable_ref.json: a VariableRef can be fully wired to its Container/Property and STILL
    render nothing until its id is ALSO registered in the page's own Page::VariableRef list. This
    is the one behaviour the task spec calls out by name -- assert the registration explicitly.

    flow_type/flow_id/view_id below differ from widget_repeater.json's own raw defaults (Process/
    Flow_Sample01/admin) and are checked via fm_index, same discipline as every other binding
    test: an assertion against the shape's own untouched default proves nothing about whether
    add_widget actually wrote the caller's config."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="repeater",
        config={
            "flow_type": "Form", "flow_id": "Flow_xyz789", "view_id": "mytasks",
            "row_fields": ["case_id", "status"],
        },
    )
    fm_index = {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]].get("Value")
                for fid in page[host]["Container::FieldMapping"]}
    assert fm_index["flow_type"] == "Form"
    assert fm_index["flow_id"] == "Flow_xyz789"
    assert fm_index["view_id"] == "mytasks"

    page_id = page["Root"]
    vrefs = _kind(page, "VariableRef")
    assert len(vrefs) == 2
    assert {v["Variable"] for v in vrefs.values()} == {"item.case_id", "item.status"}

    registered = set(page[page_id].get("Page::VariableRef") or [])
    assert set(vrefs) == registered, "every minted VariableRef must land in Page::VariableRef"

    for vref_id, vref in vrefs.items():
        container = page[vref["Container"]]
        assert vref_id in container["Container::VariableRef"]
        prop = page[vref["Property"]]
        assert prop["Type"] == "Variable"
        assert "Value" not in prop, "Type:Variable and a stale static Value must not coexist"
    _assert_backrefs_resolve(page)


def test_add_widget_repeater_row_fields_reach_selected_fields_both_sites() -> None:
    """row_fields must ALSO become the widget's own selectedFields binding, not just drive the
    per-row bound labels -- widget_repeater.json's own note: "write both rather than assuming
    either alone is read". Check BOTH sites: the FieldMapping/Property AND the Component.Data
    mirror. flow_type/flow_id/view_id also differ from widget_repeater.json's own raw defaults
    (Process/Flow_Sample01/admin), same non-tautology discipline as the other binding tests."""
    page = new_page_graph("Sample Page")
    page, host = add_widget(
        page, container_id="Container001", widget="repeater",
        config={
            "flow_type": "Form", "flow_id": "Flow_xyz789", "view_id": "mytasks",
            "row_fields": ["case_id", "status"],
        },
    )
    fm_index = {page[fid]["Name"]: page[page[fid]["FieldMapping::Property"][0]].get("Value")
                for fid in page[host]["Container::FieldMapping"]}
    assert fm_index["selectedFields"] == ["case_id", "status"]
    assert fm_index["flow_type"] == "Form"
    assert fm_index["flow_id"] == "Flow_xyz789"
    assert fm_index["view_id"] == "mytasks"

    comp = next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
                and v.get("Container") == host)
    assert comp["Data"]["selectedFields"] == ["case_id", "status"]
    _assert_backrefs_resolve(page)


def test_add_widget_repeater_without_row_fields_raises_naming_it() -> None:
    """row_fields is now a required binding for repeater (see WIDGET_REQUIRED_CONFIG): a repeater
    fetching zero columns is the same "publishes clean, shows nothing real" failure the required-
    config check exists to catch, so omitting it is no longer treated as a valid bare-host state."""
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(
            page, container_id="Container001", widget="repeater",
            config={"flow_type": "Process", "flow_id": "Flow_Sample01", "view_id": "admin"},
        )
    assert "row_fields" in str(exc.value)


def test_add_widget_row_fields_only_valid_for_repeater() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError):
        add_widget(page, container_id="Container001", widget="general/label",
                   config={"title": "x", "row_fields": ["case_id"]})


# ---------------------------------------------------------------------------------------------
# add_widget: required config keys per binding class (config={} must raise, never silently ship a
# placeholder flow/report id -- one widget per WIDGET_REQUIRED_CONFIG class, naming what's missing)
# ---------------------------------------------------------------------------------------------

def test_add_widget_view_table_missing_config_raises_naming_keys() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="view/table", config={})
    msg = str(exc.value)
    assert "flow_type" in msg and "flow_id" in msg and "view_id" in msg


def test_add_widget_report_chart_missing_config_raises_naming_keys() -> None:
    """report/* binds via the SAME flow_type/flow_id/report_id trio view/* binds flow_type/
    flow_id/view_id -- report_id alone used to be the declared requirement, which left flow_id's
    own Sample-shaped default ("Flow_Sample01") to leak past a build using exactly that config."""
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="report/chart", config={})
    msg = str(exc.value)
    assert "flow_type" in msg and "flow_id" in msg and "report_id" in msg


def test_add_widget_leak_error_names_config_keys_not_the_internal_external_kwarg(monkeypatch) -> None:
    """Every widget's Sample-shaped FieldMapping default is fully covered by WIDGET_REQUIRED_CONFIG
    today, so this path is not reachable through a normal call -- it is a defense-in-depth guard for
    a FUTURE maintenance slip (a new widget, or a required-config entry that misses one of a shape's
    placeholder ids). Simulate that slip by monkeypatching report/chart's own required tuple down to
    just ("report_id",) -- the pre-fix declaration -- so flow_id's "Flow_Sample01" default reaches
    _instantiate unresolved and its leak scan fires. add_widget must translate that into the missing
    CONFIG key ("flow_id"), never surface _instantiate's own `external=` kwarg -- add_widget's own
    caller has no such parameter, only `config`."""
    monkeypatch.setitem(WIDGET_REQUIRED_CONFIG, "report/chart", ("report_id",))
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(
            page, container_id="Container001", widget="report/chart",
            config={"report_id": "Report_r1"},
        )
    msg = str(exc.value)
    assert "external=" not in msg, "must speak in `config` terms, never the internal kwarg name"
    assert "flow_id" in msg


def test_add_widget_metrics_missing_config_raises_naming_keys() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="metrics", config={})
    msg = str(exc.value)
    assert "flow_type" in msg and "flow_id" in msg


def test_add_widget_masterdetail_missing_config_raises_naming_keys() -> None:
    """titleField/subTitleField/sortField are now required alongside flow_type/flow_id/view_id --
    their shape defaults ("Sample_Title_Field"/"Sample_Subtitle_Field") are placeholder ids too."""
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="general/masterdetail", config={})
    msg = str(exc.value)
    assert "flow_type" in msg and "flow_id" in msg and "view_id" in msg
    assert "titleField" in msg and "subTitleField" in msg and "sortField" in msg


def test_add_widget_repeater_missing_config_raises_naming_keys() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="repeater", config={})
    msg = str(exc.value)
    assert all(k in msg for k in ("flow_type", "flow_id", "view_id", "row_fields"))


def test_add_widget_no_binding_widgets_need_no_config() -> None:
    """general/*, custom widgets have no load-bearing binding -- config={} succeeds for them,
    unlike every widget in WIDGET_REQUIRED_CONFIG."""
    page = new_page_graph("Sample Page")
    page, _ = add_widget(page, container_id="Container001", widget="custom", config={})
    page, _ = add_widget(page, container_id="Container001", widget="general/tab", config={})
    assert "custom" not in WIDGET_REQUIRED_CONFIG
    assert "general/tab" not in WIDGET_REQUIRED_CONFIG
    _assert_backrefs_resolve(page)


def test_widget_required_config_covers_exactly_the_15_binding_widgets() -> None:
    """Count check: 8 view/* + 4 report/* + metrics + masterdetail + repeater ship a flow/report
    binding, plus rich_text requires its value content (#58) == 16 config-gated widgets."""
    assert len(WIDGET_REQUIRED_CONFIG) == 16  # +1: general/rich_text requires value (#58)
    assert set(WIDGET_REQUIRED_CONFIG) <= set(WIDGET_SLUGS)


# ---------------------------------------------------------------------------------------------
# add_widget: name= disambiguates two same-kind widgets (set_styles no longer collides on them)
# ---------------------------------------------------------------------------------------------

def test_add_widget_name_sets_container_and_component_name() -> None:
    page = new_page_graph("Sample Page")
    page, host_a = add_widget(page, container_id="Container001", widget="general/label",
                              config={"title": "a"}, name="Label A")
    page, host_b = add_widget(page, container_id="Container001", widget="general/label",
                              config={"title": "b"}, name="Label B")
    assert page[host_a]["Name"] == "Label A"
    assert page[host_b]["Name"] == "Label B"

    comp_a = next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
                  and v.get("Container") == host_a)
    comp_b = next(v for v in page.values() if isinstance(v, dict) and v.get("Kind") == "Component"
                  and v.get("Container") == host_b)
    assert comp_a["Name"] == "Label A"
    assert comp_b["Name"] == "Label B"

    page = set_styles(page, rules={"Label A": {"Container.Background": {"value": "#112233"}}})
    style_a = page[page[host_a]["Container::Style"][0]]["Value"]
    assert style_a["Container.Background"] == {"value": "#112233"}
    style_b = page[page[host_b]["Container::Style"][0]].get("Value") or {}
    assert "Container.Background" not in style_b, "unnamed sibling must be untouched"
    _assert_backrefs_resolve(page)


def test_add_widget_unknown_widget_raises_listing_known_widgets() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="general/bogus", config={})
    assert "general/label" in str(exc.value)


def test_add_widget_bad_config_key_raises_listing_valid_keys() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError) as exc:
        add_widget(page, container_id="Container001", widget="general/label",
                   config={"not_a_real_slot": "x"})
    assert "title" in str(exc.value)


def test_add_widget_unknown_container_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError):
        add_widget(page, container_id="Container_nope", widget="general/label", config={"title": "x"})


def test_add_widget_registers_every_of_the_28_slugs_as_loadable() -> None:
    """Cheap catalogue-completeness guard: every WIDGET_SLUGS entry must resolve to a real,
    parseable shape file (catches a typo'd filename mapping without needing 28 separate tests)."""
    assert len(WIDGET_SLUGS) == 28
    for slug, shape_name in WIDGET_SLUGS.items():
        shape = load_shape(shape_name)
        assert "Container_Sample01" in shape["template"], f"{slug} shape has no host container"


# ---------------------------------------------------------------------------------------------
# set_styles
# ---------------------------------------------------------------------------------------------

def test_set_styles_hex_and_ref_forms_both_persist() -> None:
    page = new_page_graph("Sample Page")
    page, _ = add_container(page, parent_id="Container001", name="Banner")
    page, _ = add_container(page, parent_id="Container001", name="Accent")

    page = set_styles(page, rules={
        "Banner": {"Container.Background": {"value": "#112233"}, "Container.Row.Gap": "8px"},
        "Accent": {"Container.Background": {"ref": "Color.Primary.100"}},
    })

    by_name = {v["Name"]: k for k, v in _kind(page, "Container").items() if v.get("Name")}
    banner_style = page[page[by_name["Banner"]]["Container::Style"][0]]["Value"]
    assert banner_style["Container.Background"] == {"value": "#112233"}
    assert banner_style["Container.Row.Gap"] == {"value": "8px"}, "dimensional string auto-wraps"

    accent_style = page[page[by_name["Accent"]]["Container::Style"][0]]["Value"]
    assert accent_style["Container.Background"] == {"ref": "Color.Primary.100"}
    _assert_backrefs_resolve(page)


def test_set_styles_none_removes_a_property_back_to_default() -> None:
    page = new_page_graph("Sample Page")
    page, cid = add_container(page, parent_id="Container001", name="Banner")
    page = set_styles(page, rules={"Banner": {"Container.Background": {"value": "#112233"}}})
    page = set_styles(page, rules={"Banner": {"Container.Background": None}})
    sid = page[cid]["Container::Style"][0]
    assert "Container.Background" not in (page[sid].get("Value") or {})


def test_set_styles_unknown_container_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError):
        set_styles(page, rules={"Nonexistent": {"Container.Background": {"value": "#000000"}}})


def test_set_styles_by_id_survives_duplicate_names() -> None:
    """The #25 fix: a page whose Containers share a Name (real pages carry dozens of 'Label') is
    styleable by addressing each Container by its unique id -- the id add_widget already returns --
    with no rename and no collision. The name path still raises on that same ambiguity (test below)."""
    page = new_page_graph("Sample Page")
    page, host_a = add_widget(page, container_id="Container001", widget="general/label", config={"title": "a"})
    page, host_b = add_widget(page, container_id="Container001", widget="general/label", config={"title": "b"})
    assert page[host_a]["Name"] == page[host_b]["Name"]  # both left at the shape's shared default Name

    page = set_styles(page, rules={
        host_a: {"Container.Background": {"value": "#112233"}},
        host_b: {"Container.Background": {"ref": "Color.Primary.100"}},
    })
    assert page[page[host_a]["Container::Style"][0]]["Value"]["Container.Background"] == {"value": "#112233"}
    assert page[page[host_b]["Container::Style"][0]]["Value"]["Container.Background"] == {"ref": "Color.Primary.100"}
    _assert_backrefs_resolve(page)


def test_set_styles_unknown_id_or_name_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError):
        set_styles(page, rules={"Container_nope": {"Container.Background": {"value": "#000000"}}})


def test_set_styles_ambiguous_name_raises_listing_matches() -> None:
    """Two widgets left at the shape's shared default Name ("Label") collide: set_styles must
    raise rather than silently style only the first match (name= on add_widget is the escape
    hatch, see test_add_widget_name_sets_container_and_component_name)."""
    page = new_page_graph("Sample Page")
    page, host_a = add_widget(page, container_id="Container001", widget="general/label", config={"title": "a"})
    page, host_b = add_widget(page, container_id="Container001", widget="general/label", config={"title": "b"})
    with pytest.raises(ValueError) as exc:
        set_styles(page, rules={"Label": {"Container.Background": {"value": "#112233"}}})
    msg = str(exc.value)
    assert "Label" in msg and host_a in msg and host_b in msg


# ---------------------------------------------------------------------------------------------
# add_popup
# ---------------------------------------------------------------------------------------------

def test_add_popup_tree_complete() -> None:
    page = new_page_graph("Sample Page")
    page, popup_id = add_popup(page, name="Detail Popup")
    page_id = page["Root"]

    assert popup_id in page[page_id]["Page::Popup"]
    popup = page[popup_id]
    assert popup["Name"] == "Detail Popup"

    root_container_id = popup["Popup::Container"][0]
    root_container = page[root_container_id]
    assert root_container["Kind"] == "Container" and root_container["Type"] == "Popup"
    assert root_container["Popup"] == popup_id

    style_id = popup["Popup::Style"][0]
    assert page[style_id]["Popup"] == popup_id

    fm_id = popup["Popup::FieldMapping"][0]
    assert page[fm_id]["Name"] == "title"
    prop_id = page[fm_id]["FieldMapping::Property"][0]
    assert page[prop_id]["Value"] == "Detail Popup"
    _assert_backrefs_resolve(page)


def test_add_popup_content_can_be_added_via_add_widget() -> None:
    page = new_page_graph("Sample Page")
    page, popup_id = add_popup(page, name="Detail Popup")
    root_container_id = page[popup_id]["Popup::Container"][0]
    page, host = add_widget(page, container_id=root_container_id, widget="general/label",
                            config={"title": "Inside the popup"})
    assert host in page[root_container_id]["Container::Container"]
    _assert_backrefs_resolve(page)


# ---------------------------------------------------------------------------------------------
# add_event_mapping (#22: without this, a built popup/button has no way to ever open/fire)
# ---------------------------------------------------------------------------------------------

def test_add_event_mapping_open_popup_tree_complete() -> None:
    page = new_page_graph("Sample Page")
    page, popup_id = add_popup(page, name="Detail Popup")
    page, button_host = add_widget(page, container_id="Container001", widget="general/button",
                                   config={})

    page, em_id = add_event_mapping(
        page, container_id=button_host, type="OpenPopup", popup_id=popup_id
    )

    assert em_id in page[button_host]["Container::EventMapping"]
    em = page[em_id]
    assert em["Kind"] == "EventMapping"
    assert em["Name"] == "on_click"
    assert em["Type"] == "OpenPopup"
    assert em["Container"] == button_host

    prop_id = em["EventMapping::Property"][0]
    prop = page[prop_id]
    assert prop["Kind"] == "Property"
    assert prop["Type"] == "Popup"
    assert prop["Name"] == "popup_params"
    assert prop["Value"] == popup_id
    assert prop["EventMapping"] == em_id
    _assert_backrefs_resolve(page)


def test_add_event_mapping_js_action_tree_complete() -> None:
    page = new_page_graph("Sample Page")
    page, host = add_widget(page, container_id="Container001", widget="general/button", config={})

    script = 'await kf.app.page.setVariable("chosen", kf.eventParameters.item);'
    page, em_id = add_event_mapping(page, container_id=host, type="JSAction", script=script)

    assert em_id in page[host]["Container::EventMapping"]
    em = page[em_id]
    assert em["Kind"] == "EventMapping"
    assert em["Name"] == "on_click"
    assert em["Type"] == "JSAction"
    assert em["Container"] == host

    prop_id = em["EventMapping::Property"][0]
    prop = page[prop_id]
    assert prop["Kind"] == "Property"
    assert prop["Type"] == "Code"
    assert prop["Value"] == script
    assert prop["EventMapping"] == em_id
    _assert_backrefs_resolve(page)


def test_add_event_mapping_custom_name_overrides_default() -> None:
    page = new_page_graph("Sample Page")
    page, host = add_widget(page, container_id="Container001", widget="general/button", config={})
    page, em_id = add_event_mapping(
        page, container_id=host, type="JSAction", script="void 0;", name="on_change"
    )
    assert page[em_id]["Name"] == "on_change"


def test_add_event_mapping_unknown_type_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="unknown event mapping type"):
        add_event_mapping(page, container_id="Container001", type="OnHover")  # type: ignore[arg-type]


def test_add_event_mapping_open_popup_requires_popup_id() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="requires popup_id"):
        add_event_mapping(page, container_id="Container001", type="OpenPopup")


def test_add_event_mapping_js_action_requires_script() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="requires script"):
        add_event_mapping(page, container_id="Container001", type="JSAction")


def test_add_event_mapping_script_on_open_popup_raises() -> None:
    page = new_page_graph("Sample Page")
    page, popup_id = add_popup(page, name="Detail Popup")
    with pytest.raises(ValueError, match="only valid for type='JSAction'"):
        add_event_mapping(page, container_id="Container001", type="OpenPopup",
                          popup_id=popup_id, script="void 0;")


def test_add_event_mapping_popup_id_on_js_action_raises() -> None:
    page = new_page_graph("Sample Page")
    page, popup_id = add_popup(page, name="Detail Popup")
    with pytest.raises(ValueError, match="only valid for type='OpenPopup'"):
        add_event_mapping(page, container_id="Container001", type="JSAction",
                          script="void 0;", popup_id=popup_id)


def test_add_event_mapping_unknown_container_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="no Container node"):
        add_event_mapping(page, container_id="Container_nope", type="JSAction", script="void 0;")


def test_add_event_mapping_unknown_popup_raises() -> None:
    page = new_page_graph("Sample Page")
    with pytest.raises(ValueError, match="no Popup node"):
        add_event_mapping(page, container_id="Container001", type="OpenPopup",
                          popup_id="Popup_nope")


def test_add_event_mapping_does_not_mutate_input() -> None:
    page = new_page_graph("Sample Page")
    page, popup_id = add_popup(page, name="Detail Popup")
    before = set(page)
    add_event_mapping(page, container_id="Container001", type="OpenPopup", popup_id=popup_id)
    assert set(page) == before, "add_event_mapping must not mutate its input draft"


# ---------------------------------------------------------------------------------------------
# _instantiate: leak scan now covers Value/Data too, not just structural back-refs. Driven
# straight off shapes/event_mapping.json's own OpenPopup Property.Value -- a real cross-reference
# to another node (the popup this click should open), not free-form content, so a caller who
# forgets to pass it via `external` must get a loud raise, never a silently wrong Popup id.
# ---------------------------------------------------------------------------------------------

def test_instantiate_leak_scan_catches_a_placeholder_hiding_in_value() -> None:
    shape = load_shape("event_mapping")
    subset = _keep_subset(
        shape["template"], ("Container_Sample02", "EventMapping_Sample02", "Property_Sample02")
    )
    with pytest.raises(ValueError) as exc:
        _instantiate(subset)
    msg = str(exc.value)
    assert "Popup_Sample01" in msg
    assert ".Value" in msg, "the raise should name the offending key path, not just the bare id"


def test_instantiate_leak_scan_passes_once_the_value_ref_is_covered_by_external() -> None:
    shape = load_shape("event_mapping")
    subset = _keep_subset(
        shape["template"], ("Container_Sample02", "EventMapping_Sample02", "Property_Sample02")
    )
    nodes, idmap = _instantiate(subset, external={"Popup_Sample01": "Popup_NewSample02"})
    prop_id = idmap["Property_Sample02"]
    assert nodes[prop_id]["Value"] == "Popup_NewSample02"


# ---------------------------------------------------------------------------------------------
# load_shape / page_summary
# ---------------------------------------------------------------------------------------------

def test_load_shape_unknown_name_raises_valueerror_not_file_not_found() -> None:
    with pytest.raises(ValueError) as exc:
        load_shape("does_not_exist")
    assert "page_virgin" in str(exc.value), "error should list known shape names"


def test_page_summary_counts_and_lists_widgets() -> None:
    page = new_page_graph("Sample Page")
    page, _ = add_widget(page, container_id="Container001", widget="general/label",
                         config={"title": "x"})
    page, _ = add_widget(page, container_id="Container001", widget="general/button", config={})

    summary = page_summary(page)
    assert summary["counts"]["Component"] == 2
    scripts = sorted(w["script"] for w in summary["widgets"])
    assert scripts == ["general/button", "general/label"]


# ---------------------------------------------------------------------------------------------
# kitchen sink: compose everything, sweep for dangling back-refs at the end
# ---------------------------------------------------------------------------------------------

def test_kitchen_sink_backrefs_resolve_after_a_full_composition() -> None:
    page = new_page_graph("Sample Page")
    page, banner = add_container(page, parent_id="Container001", name="Banner",
                                 layout={"Container.Row.Gap": "16px"})
    page, _ = add_widget(page, container_id=banner, widget="general/label", config={"title": "Hi"})
    page, _ = add_widget(page, container_id="Container001", widget="view/table",
                         config={"flow_type": "Form", "flow_id": "Flow_Sample01", "view_id": "myitems"})
    page, _ = add_widget(page, container_id="Container001", widget="repeater",
                         config={"flow_type": "Process", "flow_id": "Flow_Sample01",
                                 "view_id": "admin", "row_fields": ["case_id"]})
    page, popup_id = add_popup(page, name="Detail Popup")
    root_container_id = page[popup_id]["Popup::Container"][0]
    page, _ = add_widget(page, container_id=root_container_id, widget="general/button", config={})
    page, opener = add_widget(page, container_id="Container001", widget="general/button", config={})
    page, _ = add_event_mapping(page, container_id=opener, type="OpenPopup", popup_id=popup_id)
    page = set_styles(page, rules={"Banner": {"Container.Background": {"ref": "Color.Info.300"}}})

    _assert_backrefs_resolve(page)


def test_widget_required_config_covers_every_sample_shaped_binding_default() -> None:
    """Durable guard: any Sample-shaped FieldMapping default in a widget shape MUST be a
    required config key, or a new shape silently reopens the placeholder-binding hole."""
    from kfforge.pages import _SAMPLE_LEAK_RE, _raw_fm_values

    for slug in WIDGET_SLUGS:
        shape = load_shape(WIDGET_SLUGS[slug])
        sample_keys = {k for k, v in _raw_fm_values(shape["template"]).items()
                       if _SAMPLE_LEAK_RE.match(v)}
        required = set(WIDGET_REQUIRED_CONFIG.get(slug, ()))
        assert sample_keys <= required, (
            f"{slug}: Sample-shaped defaults {sorted(sample_keys - required)} "
            f"not covered by WIDGET_REQUIRED_CONFIG")
