"""Pure, offline operations on Kissflow's app-level navigation graph.

Chain (shapes/menu_navigation.json): Application --Application::Navigation--> Navigation
--Navigation::Menu--> Menu --Menu::FieldMapping--> FieldMapping --FieldMapping::Property-->
Property{Type:"Page", Value:<page id>}. No network, no Kissflow calls; every function here is pure
(returns a NEW draft, never mutates its input) and fails loud (ValueError), matching app.domain.graph
and app.domain.pages. `_instantiate`/`_keep_subset`/`load_shape` are reused from app.domain.pages rather
than duplicated -- pages.py and nav.py both clone nodes out of the SAME shapes/ catalog with the
same id-remap machinery, so this is the one cross-module reuse worth taking (see pages.py for the
full mechanism and its own docstring).
"""

from __future__ import annotations

import copy
from typing import Any

from app.domain.pages import _instantiate, _keep_subset, load_shape

Draft = dict[str, Any]


def _kind(draft: Draft, kind: str) -> dict[str, dict]:
    return {k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind}


def list_navigation(app_draft: Draft) -> dict[str, list[str]]:
    """Navigation id -> its Menu ids, for every Navigation in the draft."""
    return {
        nid: list(n.get("Navigation::Menu") or [])
        for nid, n in _kind(app_draft, "Navigation").items()
    }


def point_all_navs_at(app_draft: Draft, *, menu_ids: list[str]) -> Draft:
    """Unify: every Navigation's own Navigation::Menu list becomes exactly `menu_ids`. Pure.

    This is "same view for all roles" (menu_navigation.json's own note): role -> Navigation binding
    lives OUTSIDE the app draft entirely, so making every role see the same pages means pointing
    every Navigation at the same shared Menu ids -- never duplicating pages or Menus per role.
    A draft with zero Navigation nodes is left unchanged (nothing to unify, not a caller error);
    an empty or not-real `menu_ids` IS a caller error and raises.

    Known platform limit (pinned by test_point_all_navs_at_does_not_update_shared_menus_scalar_
    navigation_back_ref): a Menu's own scalar "Navigation" key (menu_navigation.json: "every Menu
    observed live carries an explicit scalar back-ref to its parent") can name only ONE owner. Once
    this unifies several Navigations onto the same shared Menu ids, each Menu is genuinely reachable
    from ALL of them via their Navigation::Menu lists, but its own scalar Navigation key keeps
    pointing at whichever ONE it already named (its original owner, typically whichever Navigation
    add_page_menu created it under) -- this function does not, and structurally cannot, rewrite a
    scalar into a multi-owner fact. list_navigation and sweep_orphans both key off Navigation::Menu,
    never off this scalar, so the drift is harmless to this module's own reachability logic; a
    caller reading a Menu's Navigation key directly after unification would still see only its
    original owner, not every Navigation it is now reachable from.
    """
    if not menu_ids:
        raise ValueError("menu_ids must be non-empty")
    bad = [m for m in menu_ids if app_draft.get(m, {}).get("Kind") != "Menu"]
    if bad:
        raise ValueError(f"not real Menu node id(s) in this draft: {bad}")

    new: Draft = copy.deepcopy(app_draft)
    for nav in _kind(new, "Navigation").values():
        nav["Navigation::Menu"] = list(menu_ids)
    return new


def sweep_orphans(app_draft: Draft) -> tuple[Draft, list[str]]:
    """Drop every Menu (and its FieldMapping/Property chain) unreachable from any Navigation. Pure.

    Reachability is "does some Navigation::Menu list contain this Menu's id" -- independent of
    whether the Menu itself carries the newer "Navigation" back-ref scalar (menu_navigation.json:
    an old-style Menu may lack it without being broken). Returns (new draft, ids removed) so the
    removal is never silent -- the returned list IS the audit the caller checks.
    """
    new: Draft = copy.deepcopy(app_draft)
    reachable: set[str] = set()
    for nav in _kind(new, "Navigation").values():
        reachable.update(nav.get("Navigation::Menu") or [])

    doomed: list[str] = []
    for mid, menu in _kind(new, "Menu").items():
        if mid in reachable:
            continue
        doomed.append(mid)
        for fmid in menu.get("Menu::FieldMapping") or []:
            fm = new.get(fmid) or {}
            doomed.extend(fm.get("FieldMapping::Property") or [])
            doomed.append(fmid)

    for nid in doomed:
        new.pop(nid, None)
    return new, doomed


def add_page_menu(app_draft: Draft, *, nav_id: str, page_id: str, label: str) -> Draft:
    """Wire a new page into the nav: Menu -> FieldMapping -> Property{Type:"Page", Value:page_id},
    plus the Navigation back-ref scalar on the new Menu (menu_navigation.json's "new-style Menu").
    Pure. `nav_id` must already be a real Navigation node in `app_draft`.

    Only the Menu/FieldMapping/Property portion of menu_navigation.json's template is instantiated
    -- its Application/Navigation sample nodes are the CALLER'S pre-existing `app_draft`, never
    re-minted, so they're passed as `external` substitutions instead of being cloned.
    """
    if app_draft.get(nav_id, {}).get("Kind") != "Navigation":
        raise ValueError(f"no Navigation node {nav_id!r} in this draft")

    shape = load_shape("menu_navigation")
    subset = _keep_subset(
        shape["template"], ("Menu_Sample01", "FieldMapping_Sample01", "Property_Sample01")
    )
    nodes, idmap = _instantiate(
        subset, external={"Navigation_Sample01": nav_id, "Page_Sample01": page_id}
    )
    menu_id = idmap["Menu_Sample01"]
    nodes[menu_id]["Name"] = label

    new: Draft = copy.deepcopy(app_draft)
    new.update(nodes)
    new[nav_id].setdefault("Navigation::Menu", []).append(menu_id)
    return new
