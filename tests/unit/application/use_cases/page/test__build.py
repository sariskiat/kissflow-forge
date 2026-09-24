"""`app.application.use_cases.page._build`: ported from
`tests/test_pages_live.py`'s offline/pure-function cases (pre-refactor) --
`_style_props_landed`, the raw-primitive step application, and the governed
`op` builders (`PageOpState`, `_build_single_action`, `_find_node_id`,
`_build_popup_widgets`).
"""

from __future__ import annotations

import pytest

from app.application.use_cases.page._build import (
    PageBuildStep,
    PageOpState,
    _build_popup_widgets,
    _build_single_action,
    _find_node_id,
    apply_build_steps,
    evaluate_checks,
    find_body_container,
    find_page_id,
    populate_page_state,
)
from app.domain.entities.page_draft import PageDraft

_DESIGN = {
    "kind": "container",
    "name": "page shell",
    "style": [
        ["Container.Background", "#FCFAF2"],
        ["Container.Flex.Direction", "column"],
    ],
    "children": [
        {
            "kind": "container",
            "name": "hero",
            "style": [["Container.Background", "#2E6B3B"]],
            "children": [
                {
                    "kind": "widget",
                    "name": "hero title",
                    "style": [["Label.Color", "token:Color.White"]],
                    "widget": {
                        "slug": "general/label",
                        "config": [["title", "Submit your case"]],
                    },
                },
            ],
        },
        {
            "kind": "container",
            "name": "card",
            "style": [["Container.Background", "#FFFFFF"]],
            "children": [
                {
                    "kind": "widget",
                    "name": "form",
                    "widget": {
                        "slug": "view/form",
                        "config": [["flow_type", "process"], ["flow_id", "Flow_abc"]],
                    },
                },
            ],
        },
    ],
}


def _virgin() -> PageDraft:
    return PageDraft.new("Sample Page")


# ----------------------------------------------------------------- apply_build_steps


def test_apply_build_steps_container_then_widget() -> None:
    page = _virgin()
    steps = [
        PageBuildStep("container", {"parent_id": "Container001", "name": "Banner"}),
        PageBuildStep(
            "widget",
            {
                "container_id": "Container001",
                "widget": "general/label",
                "config": {"title": "Hello"},
            },
        ),
    ]
    new_page, applied, checks = apply_build_steps(page, steps)

    assert len(applied) == 2
    read_back = new_page.to_wire()
    verified, missing = evaluate_checks(read_back, checks)
    assert verified == applied
    assert missing == []


def test_apply_build_steps_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown page-build step kind"):
        apply_build_steps(_virgin(), [PageBuildStep("bogus", {})])


def test_apply_build_steps_rejects_a_placeholder_binding_offline() -> None:
    """THE RULE: a load-bearing widget binding missing its config is rejected
    offline, before any write -- mirrors
    `test_apply_page_build_view_table_needs_full_binding_or_raises_offline`."""
    steps = [
        PageBuildStep(
            "widget",
            {"container_id": "Container001", "widget": "view/table", "config": {}},
        )
    ]
    with pytest.raises(ValueError):
        apply_build_steps(_virgin(), steps)


def test_apply_build_steps_style_check_reads_back_the_requested_props() -> None:
    """Mirrors `test_style_props_landed_resolutions_and_matching`: a style step's
    check is satisfied only when every requested prop actually landed."""
    steps = [
        PageBuildStep(
            "style", {"rules": {"Body Container": {"Container.Background": "#fff"}}}
        )
    ]
    new_page, _applied, checks = apply_build_steps(_virgin(), steps)
    verified, missing = evaluate_checks(new_page.to_wire(), checks)
    assert missing == []
    assert verified

    # a read-back that never actually landed the style value must NOT verify
    stripped = dict(new_page.to_wire())
    for k, v in list(stripped.items()):
        if isinstance(v, dict) and v.get("Kind") == "Style":
            stripped[k] = {**v, "Value": {}}
    verified2, missing2 = evaluate_checks(stripped, checks)
    assert verified2 == []
    assert missing2


def test_apply_build_steps_design_step_builds_nested_styled_tree() -> None:
    """Mirrors `test_apply_page_build_design_step_builds_nested_styled_tree`
    (pages_live.py:234, pre-refactor): the "design" step kind builds a whole
    nested, styled Container/Component tree in one call, and every minted
    node is read-back verified."""
    steps = [PageBuildStep("design", {"parent_id": "Container001", "design": _DESIGN})]
    new_page, applied, checks = apply_build_steps(_virgin(), steps)

    verified, missing = evaluate_checks(new_page.to_wire(), checks)
    assert missing == []
    assert verified == applied
    counts = new_page.page_summary()["counts"]
    assert counts.get("Container", 0) >= 5  # root+shell+hero+card+2 widget hosts


def test_apply_build_steps_popup_widget_then_event_wires_open_popup() -> None:
    """Mirrors `test_apply_page_build_popup_widget_then_event_wires_open_popup`
    (pages_live.py:315, pre-refactor): a popup + a button built in one
    `PageBuildStep` list is inert on its own -- a follow-up "event" step is
    what lets the button open the popup."""
    page, applied, checks = apply_build_steps(
        _virgin(),
        [
            PageBuildStep("popup", {"name": "Detail Popup"}),
            PageBuildStep(
                "widget",
                {
                    "container_id": "Container001",
                    "widget": "general/button",
                    "config": {},
                },
            ),
        ],
    )
    verified, missing = evaluate_checks(page.to_wire(), checks)
    assert missing == []

    draft = page.to_wire()
    popup_id = next(
        nid
        for nid, node in draft.items()
        if isinstance(node, dict) and node.get("Kind") == "Popup"
    )
    button_comp = next(
        nid
        for nid, node in draft.items()
        if isinstance(node, dict)
        and node.get("Kind") == "Component"
        and node.get("Script", {}).get("web") == "general/button"
    )
    button_container = draft[button_comp]["Container"]

    page2, applied2, checks2 = apply_build_steps(
        page,
        [
            PageBuildStep(
                "event",
                {
                    "container_id": button_container,
                    "type": "OpenPopup",
                    "popup_id": popup_id,
                },
            )
        ],
    )
    verified2, missing2 = evaluate_checks(page2.to_wire(), checks2)
    assert missing2 == []
    assert verified2 == applied2
    counts = page2.page_summary()["counts"]
    assert counts.get("EventMapping", 0) == 1


def test_apply_build_steps_event_missing_popup_id_raises_before_any_write() -> None:
    """Mirrors `test_apply_page_build_event_missing_popup_id_raises_offline`
    (pages_live.py:467, pre-refactor): a required arm argument missing must
    be rejected before any write, never shipped as a dead click."""
    steps = [
        PageBuildStep("event", {"container_id": "Container001", "type": "OpenPopup"})
    ]
    with pytest.raises(ValueError):
        apply_build_steps(_virgin(), steps)


def test_apply_build_steps_bind_repairs_an_already_built_widget() -> None:
    page, _applied, _checks = apply_build_steps(
        _virgin(),
        [
            PageBuildStep(
                "widget",
                {
                    "container_id": "Container001",
                    "widget": "view/form",
                    "config": {"flow_type": "Process", "flow_id": "Flow_placeholder"},
                },
            )
        ],
    )
    host = next(
        v["Id"]
        for v in page.to_wire().values()
        if isinstance(v, dict)
        and v.get("Kind") == "Container"
        and v.get("Container::Component")
    )
    new_page, applied, checks = apply_build_steps(
        page,
        [PageBuildStep("bind", {"host": host, "config": {"flow_id": "Flow_rebind99"}})],
    )
    verified, missing = evaluate_checks(new_page.to_wire(), checks)
    assert verified == applied
    assert missing == []


# --------------------------------------------------------------------- find_* helpers


def test_find_body_container_finds_the_virgin_root() -> None:
    body = find_body_container(_virgin().to_wire())
    assert body == "Container001"


def test_find_body_container_returns_none_when_absent() -> None:
    assert find_body_container({"Root": "Page1"}) is None


def test_find_page_id_matches_by_exact_name() -> None:
    pages = [None, "invalid", {"Name": "Other"}, {"_id": "p1", "Name": "Existing"}]
    assert find_page_id(pages, "Existing") == "p1"
    assert find_page_id(pages, "Nope") is None


# ------------------------------------------------------------------------- PageOpState


def test_populate_page_state_builds_widgets_popups_actions_kpis() -> None:
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(
        state,
        {
            "widgets": ({"slug": "general/label", "config": {"title": "Welcome"}},),
            "kpis": ("Open cases",),
            "actions": ("New Case",),
            "popups": (
                {
                    "name": "New Case Form",
                    "widgets": (
                        {"slug": "general/label", "config": {"title": "Fill me"}},
                    ),
                },
            ),
            "on_click": (
                {
                    "action": "New Case",
                    "kind": "OpenPopup",
                    "target_popup": "New Case Form",
                },
            ),
        },
    )
    assert set(state.built) == {
        "widget:general/label",
        "popup:New Case Form",
        "popup:New Case Form/widget:general/label",
        "action:New Case",
        "on_click:New Case",
    }
    assert state.skipped and "Known Exclusion" in state.skipped[0]
    assert state.refused == []
    verified, missing = evaluate_checks(state.page.to_wire(), state.checks)
    assert missing == []
    assert set(verified) == set(state.built)


def test_populate_page_state_design_step_builds_into_the_body() -> None:
    """Mirrors `test_apply_build_page_op_builds_design_into_body`
    (pages_live.py:252, pre-refactor): the governed executor consumes a
    compiled `build_page` op whose args carry a `design`, building the
    beautiful-page tree into the Body and read-back verifying it."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(state, {"design": _DESIGN})

    assert any(b.startswith("design:") for b in state.built)
    verified, missing = evaluate_checks(state.page.to_wire(), state.checks)
    assert missing == []


def test_populate_page_state_malformed_design_is_refused() -> None:
    """Mirrors `test_apply_build_page_op_malformed_design_refused`
    (pages_live.py:970, pre-refactor)."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(state, {"design": {"bad": "tree"}})

    assert any(r.startswith("design:") for r in state.refused)
    assert state.built == []


def test_populate_page_state_an_invalid_widget_is_refused() -> None:
    """Mirrors `test_apply_build_page_op_widget_error_refused`
    (pages_live.py:982, pre-refactor)."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(
        state,
        {"widgets": ({"slug": "invalid/widget", "config": {}, "row_fields": ("f1",)},)},
    )

    assert any(r.startswith("widget:") for r in state.refused)
    assert state.built == []


def test_populate_page_state_jsaction_builds_and_verifies() -> None:
    """Mirrors `test_apply_build_page_op_jsaction_and_action_error`
    (pages_live.py:998, pre-refactor)."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(
        state,
        {
            "actions": ("Run JS",),
            "on_click": (
                {"action": "Run JS", "kind": "JSAction", "script": "console.log(1)"},
            ),
        },
    )

    assert "action:Run JS" in state.built
    assert "on_click:Run JS" in state.built
    verified, _missing = evaluate_checks(state.page.to_wire(), state.checks)
    assert "on_click:Run JS" in verified


def test_populate_page_state_jsaction_with_no_script_is_refused() -> None:
    """Mirrors `test_apply_build_page_op_action_event_mapping_fails`
    (pages_live.py:1025, pre-refactor): a JSAction with no real script is
    refused, never a dead click shipped."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(
        state,
        {
            "actions": ("Bad JS",),
            "on_click": ({"action": "Bad JS", "kind": "JSAction", "script": ""},),
        },
    )

    assert any("on_click:Bad JS" in r for r in state.refused)


def test_populate_page_state_builds_an_action_only_declared_in_wiring() -> None:
    """Mirrors `test_apply_build_page_op_undeclared_action_in_wiring`
    (pages_live.py:1144, pre-refactor): an action that is not in `actions`
    but IS the target of an `on_click` entry still gets built -- the wiring
    map, not the declared list, is authoritative."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(
        state,
        {
            "popups": ({"name": "New Case Form", "widgets": ()},),
            "actions": (),
            "on_click": (
                {
                    "action": "OnlyInWiring",
                    "kind": "OpenPopup",
                    "target_popup": "New Case Form",
                },
            ),
        },
    )

    assert "action:OnlyInWiring" in state.built
    assert "on_click:OnlyInWiring" in state.built


def test_populate_page_state_plain_action_without_onclick_builds_no_wiring() -> None:
    """Mirrors `test_apply_build_page_op_plain_action_without_onclick`
    (pages_live.py:1170, pre-refactor): a declared action with no matching
    `on_click` entry builds the button alone, never a dead EventMapping."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(state, {"actions": ("PlainButton",), "on_click": ()})

    assert "action:PlainButton" in state.built
    assert "on_click:PlainButton" not in state.built


def test_populate_page_state_refuses_a_dangling_popup_target() -> None:
    """D6: never a dead button -- mirrors
    `test_apply_build_page_op_refuses_dangling_popup_target`."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    populate_page_state(
        state,
        {
            "actions": ("New Case",),
            "on_click": (
                {
                    "action": "New Case",
                    "kind": "OpenPopup",
                    "target_popup": "Ghost Popup",
                },
            ),
        },
    )
    assert any("unknown popup" in r for r in state.refused)
    assert "action:New Case" not in state.built


def test_find_node_id_returns_none_for_an_unknown_parent() -> None:
    assert _find_node_id({}, "Component", "Container", "unknown") is None


def test_build_single_action_refuses_when_the_body_container_is_missing() -> None:
    """Mirrors `test_apply_build_page_op_action_widget_error_refused`: calling
    the private builder directly, against a draft with no real body
    container."""
    state = PageOpState({"Root": "Page1"}, "MissingBody")
    _build_single_action(state, "MyAction", None)
    assert any("action:MyAction" in r for r in state.refused)


def test_build_popup_widgets_no_widgets_no_container_is_a_no_op() -> None:
    """Mirrors `test_a_popup_with_widgets_but_no_container_is_named_not_passed_down`:
    two different situations must not be conflated."""
    state = PageOpState(_virgin().to_wire(), "Container001")
    _build_popup_widgets(state, "Detail", None, None)
    _build_popup_widgets(state, "Detail", None, ())
    assert state.built == []
    assert state.refused == []


def test_build_popup_widgets_widgets_but_no_container_is_refused_named() -> None:
    state = PageOpState(_virgin().to_wire(), "Container001")
    with pytest.raises(ValueError, match="Detail.*no Popup::Container"):
        _build_popup_widgets(
            state, "Detail", None, ({"slug": "general/label", "config": {}},)
        )
