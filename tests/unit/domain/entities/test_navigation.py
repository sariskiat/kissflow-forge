"""Unit tests for app.domain.entities.navigation.Navigation.

The round-trip invariant over every JSON file in tests/fixtures/*.json and
shapes/*.json, from_wire's defensive copy, to_wire's defensive copy, the
`version` read, and frozen-ness, plus the behavior of every method (moved from
tests/test_nav.py, G9a): list_navigation, point_all_navs_at, sweep_orphans,
add_page_menu.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import pathlib

import pytest

from app.domain.entities.navigation import Navigation

ROOT = pathlib.Path(__file__).resolve().parents[4]


def _json_files() -> list[pathlib.Path]:
    fixtures = sorted((ROOT / "tests" / "fixtures").glob("*.json"))
    shapes = sorted((ROOT / "shapes").glob("*.json"))
    return fixtures + shapes


_FILES = _json_files()
_IDS = [str(p.relative_to(ROOT)) for p in _FILES]


def test_json_files_found() -> None:
    # Guards every parametrized case below against silently collecting zero
    # cases if the globs ever stop matching anything.
    assert len(_FILES) > 0


@pytest.mark.parametrize("path", _FILES, ids=_IDS)
def test_round_trip_is_byte_equal(path: pathlib.Path) -> None:
    with path.open(encoding="utf-8") as f:
        d = json.load(f)

    assert json.dumps(Navigation.from_wire(d).to_wire()) == json.dumps(d)


def test_from_wire_copies_its_input() -> None:
    wire = {"Navigation_Sample01": {"Name": "original"}}
    draft = Navigation.from_wire(wire)

    wire["Navigation_Sample01"]["Name"] = "mutated"
    wire["Navigation_Sample02"] = {"Name": "added after the call"}

    assert draft.nodes == {"Navigation_Sample01": {"Name": "original"}}


def test_to_wire_returns_a_copy() -> None:
    draft = Navigation.from_wire({"Navigation_Sample01": {"Name": "original"}})
    wire = draft.to_wire()

    wire["Navigation_Sample01"]["Name"] = "mutated"
    wire["Navigation_Sample02"] = {"Name": "added after the call"}

    assert draft.nodes == {"Navigation_Sample01": {"Name": "original"}}


def test_version_reads_meta_version() -> None:
    draft = Navigation.from_wire({"_meta_version": "17"})

    assert draft.version == "17"


def test_version_is_none_when_the_graph_carries_none() -> None:
    draft = Navigation.from_wire({"Navigation_Sample01": {"Name": "original"}})

    assert draft.version is None


def test_is_frozen() -> None:
    draft = Navigation.from_wire({})

    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.nodes = {"changed": True}  # ty: ignore[invalid-assignment]


# ======================================================================================
# Behavior: list_navigation / point_all_navs_at / sweep_orphans / add_page_menu (G9a).
#
# Pure + offline: no network, no Kissflow calls, no real-app content. The app draft here
# is a small HAND-BUILT fixture (like tests/fixtures/*.json) rather than something built
# by Navigation itself -- Navigation.add_page_menu adds menus into an EXISTING
# Application/Navigation graph, it does not create one from scratch, so a realistic
# pre-existing draft is the correct starting point for these tests. Moved from
# tests/test_nav.py (G9a): every assertion is unchanged, only the call shape (a module
# function on a dict -> a method on a Navigation instance) moved with it.
# ======================================================================================


def _seed_app_draft() -> dict:
    """Two roles (Requester/Admin), each with its own Navigation -> Menu -> FieldMapping
    -> Property chain, both currently pointing at the SAME target page -- a realistic
    freshly-GET'd app draft."""
    return {
        "Root": "Model_Sample01",
        "Model_Sample01": {
            "Id": "Model_Sample01",
            "Kind": "Application",
            "FlowType": "Application",
            "Name": "Sample Application",
            "DefaultPage": "Page_Sample01",
            "Application::Navigation": ["Navigation_Sample01", "Navigation_Sample02"],
        },
        "Navigation_Sample01": {
            "Id": "Navigation_Sample01",
            "Kind": "Navigation",
            "Name": "Requester Navigation",
            "Application": "Model_Sample01",
            "Navigation::Menu": ["Menu_Sample01"],
        },
        "Navigation_Sample02": {
            "Id": "Navigation_Sample02",
            "Kind": "Navigation",
            "Name": "Admin Navigation",
            "Application": "Model_Sample01",
            "Navigation::Menu": ["Menu_Sample02"],
        },
        "Menu_Sample01": {
            "Id": "Menu_Sample01",
            "Kind": "Menu",
            "Name": "Overview",
            "Navigation": "Navigation_Sample01",
            "Menu::FieldMapping": ["FieldMapping_Sample01"],
        },
        "FieldMapping_Sample01": {
            "Id": "FieldMapping_Sample01",
            "Kind": "FieldMapping",
            "Name": "Page",
            "Menu": "Menu_Sample01",
            "FieldMapping::Property": ["Property_Sample01"],
        },
        "Property_Sample01": {
            "Id": "Property_Sample01",
            "Kind": "Property",
            "Type": "Page",
            "Value": "Page_Sample01",
            "FieldMapping": "FieldMapping_Sample01",
        },
        "Menu_Sample02": {
            "Id": "Menu_Sample02",
            "Kind": "Menu",
            "Name": "Admin Overview",
            "Navigation": "Navigation_Sample02",
            "Menu::FieldMapping": ["FieldMapping_Sample02"],
        },
        "FieldMapping_Sample02": {
            "Id": "FieldMapping_Sample02",
            "Kind": "FieldMapping",
            "Name": "Page",
            "Menu": "Menu_Sample02",
            "FieldMapping::Property": ["Property_Sample02"],
        },
        "Property_Sample02": {
            "Id": "Property_Sample02",
            "Kind": "Property",
            "Type": "Page",
            "Value": "Page_Sample01",
            "FieldMapping": "FieldMapping_Sample02",
        },
    }


def _assert_backrefs_resolve(draft: dict) -> None:
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


# --------------------------------------------------------------------------------------
# list_navigation
# --------------------------------------------------------------------------------------


def test_list_navigation_maps_nav_to_menus() -> None:
    app = _seed_app_draft()
    assert Navigation.from_wire(app).list_navigation() == {
        "Navigation_Sample01": ["Menu_Sample01"],
        "Navigation_Sample02": ["Menu_Sample02"],
    }


# --------------------------------------------------------------------------------------
# point_all_navs_at
# --------------------------------------------------------------------------------------


def test_point_all_navs_at_unifies_every_navigation() -> None:
    app = _seed_app_draft()
    new = (
        Navigation.from_wire(app)
        .point_all_navs_at(menu_ids=["Menu_Sample01", "Menu_Sample02"])
        .to_wire()
    )
    navs = Navigation.from_wire(new).list_navigation()
    assert navs == {
        "Navigation_Sample01": ["Menu_Sample01", "Menu_Sample02"],
        "Navigation_Sample02": ["Menu_Sample01", "Menu_Sample02"],
    }, "every Navigation must end up pointing at the exact same shared menu set"
    _assert_backrefs_resolve(new)


def test_point_all_navs_at_does_not_update_shared_menus_scalar_navigation_back_ref() -> (  # noqa: E501
    None
):
    """Known platform limit, documented on point_all_navs_at's own docstring: a Menu's
    scalar "Navigation" key can name only ONE owner. After unifying, Menu_Sample01 and
    Menu_Sample02 are each genuinely reachable from BOTH Navigations via
    Navigation::Menu, but their own scalar Navigation key still names only their
    ORIGINAL owner -- pinned here so a future change to this is a deliberate choice,
    not an accident nobody noticed."""
    app = _seed_app_draft()
    new = (
        Navigation.from_wire(app)
        .point_all_navs_at(menu_ids=["Menu_Sample01", "Menu_Sample02"])
        .to_wire()
    )

    assert new["Menu_Sample01"]["Navigation"] == "Navigation_Sample01", (
        "unchanged: original owner"
    )
    assert new["Menu_Sample02"]["Navigation"] == "Navigation_Sample02", (
        "unchanged: original owner"
    )

    # yet BOTH menus are genuinely reachable from BOTH navigations post-unification
    for menu_ids in Navigation.from_wire(new).list_navigation().values():
        assert set(menu_ids) == {"Menu_Sample01", "Menu_Sample02"}


def test_point_all_navs_at_does_not_mutate_input() -> None:
    app = _seed_app_draft()
    before = copy.deepcopy(app)
    Navigation.from_wire(app).point_all_navs_at(menu_ids=["Menu_Sample01"])
    assert app == before


def test_point_all_navs_at_rejects_empty_menu_ids() -> None:
    app = _seed_app_draft()
    with pytest.raises(ValueError):
        Navigation.from_wire(app).point_all_navs_at(menu_ids=[])


def test_point_all_navs_at_rejects_unknown_menu_ids() -> None:
    app = _seed_app_draft()
    with pytest.raises(ValueError):
        Navigation.from_wire(app).point_all_navs_at(menu_ids=["Menu_DoesNotExist"])


def test_point_all_navs_at_rejects_a_non_menu_id() -> None:
    app = _seed_app_draft()
    with pytest.raises(ValueError):
        # real id, wrong Kind
        Navigation.from_wire(app).point_all_navs_at(menu_ids=["Navigation_Sample01"])


# --------------------------------------------------------------------------------------
# sweep_orphans
# --------------------------------------------------------------------------------------


def test_sweep_orphans_removes_exactly_the_seeded_orphan() -> None:
    app = _seed_app_draft()
    # seed an orphan Menu chain that no Navigation points at
    app["Menu_Orphan"] = {
        "Id": "Menu_Orphan",
        "Kind": "Menu",
        "Name": "Stray",
        "Navigation": "Navigation_Sample01",
        "Menu::FieldMapping": ["FieldMapping_Orphan"],
    }
    app["FieldMapping_Orphan"] = {
        "Id": "FieldMapping_Orphan",
        "Kind": "FieldMapping",
        "Name": "Page",
        "Menu": "Menu_Orphan",
        "FieldMapping::Property": ["Property_Orphan"],
    }
    app["Property_Orphan"] = {
        "Id": "Property_Orphan",
        "Kind": "Property",
        "Type": "Page",
        "Value": "Page_Sample01",
        "FieldMapping": "FieldMapping_Orphan",
    }

    new_nav, dropped = Navigation.from_wire(app).sweep_orphans()
    new = new_nav.to_wire()

    assert set(dropped) == {"Menu_Orphan", "FieldMapping_Orphan", "Property_Orphan"}
    for nid in dropped:
        assert nid not in new
    # the reachable chain is untouched
    for nid in (
        "Menu_Sample01",
        "FieldMapping_Sample01",
        "Property_Sample01",
        "Menu_Sample02",
        "FieldMapping_Sample02",
        "Property_Sample02",
    ):
        assert nid in new
    _assert_backrefs_resolve(new)


def test_sweep_orphans_is_a_no_op_when_nothing_is_orphaned() -> None:
    app = _seed_app_draft()
    new_nav, dropped = Navigation.from_wire(app).sweep_orphans()
    assert dropped == []
    assert new_nav.to_wire() == app


def test_sweep_orphans_does_not_mutate_input() -> None:
    app = _seed_app_draft()
    app["Menu_Orphan"] = {
        "Id": "Menu_Orphan",
        "Kind": "Menu",
        "Name": "Stray",
        "Menu::FieldMapping": [],
    }
    before = copy.deepcopy(app)
    Navigation.from_wire(app).sweep_orphans()
    assert app == before


# --------------------------------------------------------------------------------------
# add_page_menu
# --------------------------------------------------------------------------------------


def test_add_page_menu_wires_full_chain_and_backref() -> None:
    app = _seed_app_draft()
    new = (
        Navigation.from_wire(app)
        .add_page_menu(
            nav_id="Navigation_Sample01",
            page_id="Page_NewSample02",
            label="Sample Tab",
        )
        .to_wire()
    )

    nav = new["Navigation_Sample01"]
    added = [m for m in nav["Navigation::Menu"] if m != "Menu_Sample01"]
    assert len(added) == 1
    menu_id = added[0]
    menu = new[menu_id]
    assert menu["Name"] == "Sample Tab"
    assert menu["Navigation"] == "Navigation_Sample01", (
        "new-style Menu carries the Navigation back-ref"
    )

    fm_id = menu["Menu::FieldMapping"][0]
    fm = new[fm_id]
    assert fm["Name"] == "Page"
    prop = new[fm["FieldMapping::Property"][0]]
    assert prop["Type"] == "Page"
    assert prop["Value"] == "Page_NewSample02"
    _assert_backrefs_resolve(new)


def test_add_page_menu_leaves_other_navigations_untouched() -> None:
    app = _seed_app_draft()
    new = (
        Navigation.from_wire(app)
        .add_page_menu(
            nav_id="Navigation_Sample01",
            page_id="Page_NewSample02",
            label="Sample Tab",
        )
        .to_wire()
    )
    assert new["Navigation_Sample02"]["Navigation::Menu"] == ["Menu_Sample02"]


def test_add_page_menu_unknown_nav_raises() -> None:
    app = _seed_app_draft()
    with pytest.raises(ValueError):
        Navigation.from_wire(app).add_page_menu(
            nav_id="Navigation_DoesNotExist", page_id="Page_NewSample02", label="x"
        )


def test_add_page_menu_does_not_mutate_input() -> None:
    app = _seed_app_draft()
    before = copy.deepcopy(app)
    Navigation.from_wire(app).add_page_menu(
        nav_id="Navigation_Sample01",
        page_id="Page_NewSample02",
        label="Sample Tab",
    )
    assert app == before


# --------------------------------------------------------------------------------------
# kitchen sink: add a menu, unify, sweep -- the real "give every role the same view"
# workflow
# --------------------------------------------------------------------------------------


def test_unify_then_sweep_end_to_end() -> None:
    app = _seed_app_draft()
    app = (
        Navigation.from_wire(app)
        .add_page_menu(
            nav_id="Navigation_Sample01",
            page_id="Page_NewSample02",
            label="Sample Tab",
        )
        .to_wire()
    )
    new_menu_id = next(
        m
        for m in app["Navigation_Sample01"]["Navigation::Menu"]
        if m != "Menu_Sample01"
    )

    unified = (
        Navigation.from_wire(app)
        .point_all_navs_at(menu_ids=["Menu_Sample01", new_menu_id])
        .to_wire()
    )
    swept_nav, dropped = Navigation.from_wire(unified).sweep_orphans()
    swept = swept_nav.to_wire()

    # Menu_Sample02 (Admin's original menu) is no longer pointed at by any Navigation ->
    # swept
    assert "Menu_Sample02" in dropped
    assert "Menu_Sample02" not in swept
    for nav in Navigation.from_wire(swept).list_navigation().values():
        assert set(nav) == {"Menu_Sample01", new_menu_id}
    _assert_backrefs_resolve(swept)
