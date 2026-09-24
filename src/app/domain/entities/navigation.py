"""Navigation — the app-level navigation graph, wrapped as a domain entity.

Invariant: for every JSON file `f` in `tests/fixtures/*.json` and `shapes/*.json`, with
`d = json.load(f)`:

json.dumps(Navigation.from_wire(d).to_wire()) == json.dumps(d)

Round-tripping through this entity never reorders a key, drops a node, or changes a
value.

Chain (shapes/menu_navigation.json): Application --Application::Navigation--> Navigation
--Navigation::Menu--> Menu --Menu::FieldMapping--> FieldMapping
--FieldMapping::Property--> Property{Type:"Page", Value:<page id>}. No network, no
Kissflow calls; every method here is pure (returns a NEW Navigation, never mutates
`self`) and fails loud (ValueError), matching `app.domain.entities.flow_draft` and
`app.domain.entities.page_draft`. `_instantiate`/ `_keep_subset`/`load_shape` are reused
from `app.domain.entities.page_draft` rather than duplicated -- this module and
`page_draft.py` both clone nodes out of the SAME shapes/ catalog with the same id-remap
machinery, so this is the one cross-module reuse worth taking (see page_draft.py for the
full mechanism and its own docstring).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Self

from app.domain.entities.page_draft import _instantiate, _keep_subset, load_shape

# Private node-map alias for the module-level implementation functions below. Not
# `Navigation` itself (that is the public entity) and does not end in "Draft" (G9a
# rule): used only inside the private functions this class's methods delegate to.
_NodeMap = dict[str, Any]


def _kind(draft: _NodeMap, kind: str) -> dict[str, dict]:
    return {
        k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind
    }


def _list_navigation(app_draft: _NodeMap) -> dict[str, list[str]]:
    """Navigation id -> its Menu ids, for every Navigation in the draft."""
    return {
        nid: list(n.get("Navigation::Menu") or [])
        for nid, n in _kind(app_draft, "Navigation").items()
    }


def _point_all_navs_at(app_draft: _NodeMap, *, menu_ids: list[str]) -> _NodeMap:
    """Unify: every Navigation's own Navigation::Menu list becomes exactly `menu_ids`.
    Pure.

    This is "same view for all roles" (menu_navigation.json's own note): role ->
    Navigation binding lives OUTSIDE the app draft entirely, so making every role see
    the same pages means pointing every Navigation at the same shared Menu ids -- never
    duplicating pages or Menus per role. A draft with zero Navigation nodes is left
    unchanged (nothing to unify, not a caller error); an empty or not-real `menu_ids` IS
    a caller error and raises.

    Known platform limit (pinned by
    test_point_all_navs_at_does_not_update_shared_menus_scalar_navigation_back_ref): a
    Menu's own scalar "Navigation" key (menu_navigation.json: "every Menu observed live
    carries an explicit scalar back-ref to its parent") can name only ONE owner. Once
    this unifies several Navigations onto the same shared Menu ids, each Menu is
    genuinely reachable from ALL of them via their Navigation::Menu lists, but its own
    scalar Navigation key keeps pointing at whichever ONE it already named (its original
    owner, typically whichever Navigation `_add_page_menu` created it under) -- this
    function does not, and structurally cannot, rewrite a scalar into a multi-owner
    fact. `_list_navigation` and `_sweep_orphans` both key off Navigation::Menu, never
    off this scalar, so the drift is harmless to this module's own reachability logic; a
    caller reading a Menu's Navigation key directly after unification would still see
    only its original owner, not every Navigation it is now reachable from.
    """
    if not menu_ids:
        raise ValueError("menu_ids must be non-empty")
    bad = [m for m in menu_ids if app_draft.get(m, {}).get("Kind") != "Menu"]
    if bad:
        raise ValueError(f"not real Menu node id(s) in this draft: {bad}")

    new: _NodeMap = copy.deepcopy(app_draft)
    for nav in _kind(new, "Navigation").values():
        nav["Navigation::Menu"] = list(menu_ids)
    return new


def _sweep_orphans(app_draft: _NodeMap) -> tuple[_NodeMap, list[str]]:
    """Drop every Menu (and its FieldMapping/Property chain) unreachable from any
    Navigation. Pure.

    Reachability is "does some Navigation::Menu list contain this Menu's id" --
    independent of whether the Menu itself carries the newer "Navigation" back-ref
    scalar (menu_navigation.json: an old-style Menu may lack it without being broken).
    Returns (new draft, ids removed) so the removal is never silent -- the returned list
    IS the audit the caller checks.
    """
    new: _NodeMap = copy.deepcopy(app_draft)
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


def _add_page_menu(
    app_draft: _NodeMap, *, nav_id: str, page_id: str, label: str
) -> _NodeMap:
    """Wire a new page into the nav: Menu -> FieldMapping -> Property{Type:"Page",
    Value:page_id}, plus the Navigation back-ref scalar on the new Menu
    (menu_navigation.json's "new-style Menu"). Pure. `nav_id` must already be a real
    Navigation node in `app_draft`.

    Only the Menu/FieldMapping/Property portion of menu_navigation.json's template is
    instantiated -- its Application/Navigation sample nodes are the CALLER'S
    pre-existing `app_draft`, never re-minted, so they're passed as `external`
    substitutions instead of being cloned.
    """
    if app_draft.get(nav_id, {}).get("Kind") != "Navigation":
        raise ValueError(f"no Navigation node {nav_id!r} in this draft")

    shape = load_shape("menu_navigation")
    subset = _keep_subset(
        shape["template"],
        ("Menu_Sample01", "FieldMapping_Sample01", "Property_Sample01"),
    )
    nodes, idmap = _instantiate(
        subset, external={"Navigation_Sample01": nav_id, "Page_Sample01": page_id}
    )
    menu_id = idmap["Menu_Sample01"]
    nodes[menu_id]["Name"] = label

    new: _NodeMap = copy.deepcopy(app_draft)
    new.update(nodes)
    new[nav_id].setdefault("Navigation::Menu", []).append(menu_id)
    return new


@dataclass(frozen=True)
class Navigation:
    """The normalized Kissflow app-level navigation graph.

    Attributes:
        nodes: The wire-format node graph, keyed by node id.
    """

    nodes: dict[str, Any]

    @classmethod
    def from_wire(cls, wire: dict[str, Any]) -> Self:
        """Build a Navigation from a wire-format node graph.

        Args:
            wire: The raw node graph, as read from the Kissflow builder API
                or a JSON fixture. Deep-copied on the way in, so a mutation
                of `wire` after this call never reaches the entity.

        Returns:
            A new Navigation wrapping a deep copy of `wire`. No validation,
            no reordering.
        """
        return cls(nodes=copy.deepcopy(wire))

    def to_wire(self) -> dict[str, Any]:
        """Return the node graph in wire format.

        Returns:
            A deep copy of the stored node graph, safe for the caller to
            mutate without affecting this entity.
        """
        return copy.deepcopy(self.nodes)

    @property
    def version(self) -> str | None:
        """The draft's `_meta_version`, or None when the graph carries none."""
        return self.nodes.get("_meta_version")

    def list_navigation(self) -> dict[str, list[str]]:
        """Every Navigation node's own Menu ids.

        Returns:
            Navigation id -> its Menu ids, for every Navigation in the draft.
        """
        return _list_navigation(copy.deepcopy(self.nodes))

    def point_all_navs_at(self, *, menu_ids: list[str]) -> Self:
        """Unify: every Navigation's own Menu list becomes exactly `menu_ids`.

        Args:
            menu_ids: The real Menu ids every Navigation should point at.

        Returns:
            The new Navigation, unchanged when the draft holds zero
            Navigation nodes.

        Raises:
            ValueError: `menu_ids` is empty, or names an id that is not a
                real Menu node in this draft.
        """
        nodes = _point_all_navs_at(copy.deepcopy(self.nodes), menu_ids=menu_ids)
        return self.__class__(nodes=nodes)

    def sweep_orphans(self) -> tuple[Self, list[str]]:
        """Drop every Menu unreachable from any Navigation.

        Returns:
            A tuple of the new Navigation and the ids removed (a Menu and
            its FieldMapping/Property chain, per dropped Menu).
        """
        nodes, doomed = _sweep_orphans(copy.deepcopy(self.nodes))
        return self.__class__(nodes=nodes), doomed

    def add_page_menu(self, *, nav_id: str, page_id: str, label: str) -> Self:
        """Wire a new page into the nav under an existing Navigation.

        Args:
            nav_id: A real Navigation node id already in this draft.
            page_id: The page id the new Menu entry should open.
            label: The new Menu's `Name`.

        Returns:
            The new Navigation with the Menu/FieldMapping/Property chain added.

        Raises:
            ValueError: `nav_id` names no Navigation node in this draft.
        """
        nodes = _add_page_menu(
            copy.deepcopy(self.nodes), nav_id=nav_id, page_id=page_id, label=label
        )
        return self.__class__(nodes=nodes)
