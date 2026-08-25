"""Live orchestration for the app-PAGE and app-NAVIGATION node-graphs (Node G, P2 server surface).

Mirrors kfforge.client's own convention exactly (GET -> apply an offline builder -> guarded PUT ->
READ-BACK verify -> optional publish), kept in its OWN file for the same reason kfforge.pages and
kfforge.nav are split out from kfforge.graph: a page/application draft is a DIFFERENT node-graph
shape (Container/Component/Style, Navigation/Menu/FieldMapping) living under a different URL
family (`/metadata/2/{a}/application/{app}/...`) than a flow draft. Every function here composes a
`kfforge.client.KfClient` (already carrying the page/app HTTP methods) with `kfforge.pages` /
`kfforge.nav`'s pure builders — it holds no HTTP logic of its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .client import Err, KfClient
from .nav import add_page_menu, point_all_navs_at, sweep_orphans
from .pages import (
    _fm_index,
    add_container,
    add_event_mapping,
    add_popup,
    add_widget,
    bind_widget,
    build_design,
    page_summary,
    resolve_container_id,
    set_styles,
)

Draft = dict[str, Any]
_META_VERSION = "_meta_version"


@dataclass(frozen=True)
class PageReport:
    """Output-invariant audit for forge_create_page: verified via list_pages, never the create
    response alone (CLAUDE.md Page CRUD)."""
    app_id: str
    page_id: str | None
    name: str
    verified: bool
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id, "page_id": self.page_id, "name": self.name,
            "verified": self.verified, "published": self.published,
            "isError": not self.verified,
        }


def create_page_flow(
    client: KfClient, app_id: str, name: str, publish: bool = False,
) -> PageReport | Err:
    """POST the page shell -> verify it exists via `list_pages` (never the create response alone,
    same discipline the manual documents for delete) -> optionally publish it.

    The virgin page graph (`pages.new_page_graph`) is NOT separately PUT here — CLAUDE.md's own
    capture shows `POST .../page` already returns a live 4-node virgin page (Page/Container001/
    Style001/User). A caller who wants to add content uses `apply_page_build` next.
    """
    page_id = client.create_page(app_id, name)
    if isinstance(page_id, Err):
        return page_id

    listed = client.list_pages(app_id)
    if isinstance(listed, Err):
        return listed
    verified = any(isinstance(p, dict) and p.get("_id") == page_id for p in listed)

    published = False
    if publish and verified:
        pub = client.publish_page(app_id, page_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return PageReport(app_id=app_id, page_id=page_id if verified else None, name=name,
                      verified=verified, published=published)


@dataclass(frozen=True)
class PageBuildStep:
    """One page-build op. `kind` is one of "container" | "widget" | "popup" | "event" | "style" |
    "bind" | "design"; `kwargs` are passed straight to the matching kfforge.pages builder
    (add_container/add_widget/add_popup/add_event_mapping/set_styles/bind_widget/build_design) — see
    their own docstrings for the accepted keys. "design" takes `{parent_id, design}` and builds a
    whole nested styled Container/Component tree from one design dict (page.design.md). A spec dict
    from a caller (e.g. an MCP tool argument) becomes a list of these."""
    kind: str
    kwargs: dict[str, Any]


@dataclass(frozen=True)
class PageBuildReport:
    """Output-invariant audit for forge_build_page: every step lands in exactly one bucket after
    the read-back — `verified` or `missing` — never a structurally-guaranteed success (Node G
    review F1: a PUT that 200s while a widget/container/popup is absent from the read-back, or a
    style value never landed, is the exact silent-discard class THE RULE exists for)."""
    app_id: str
    page_id: str
    applied: tuple[str, ...]             # one descriptive label per step, in order
    verified: tuple[str, ...]            # same labels, confirmed present/landed on read-back
    missing: tuple[str, ...]             # requested, but NOT found on read-back
    node_counts: dict[str, int]          # page_summary(read_back)["counts"] -- the read-back audit
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id, "page_id": self.page_id, "applied": list(self.applied),
            "verified": list(self.verified), "missing": list(self.missing),
            "node_counts": self.node_counts, "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing),
        }


def _prop_matches(value: dict[str, Any], prop: str, expected: Any) -> bool:
    if expected is None:
        return prop not in value
    if isinstance(expected, dict):
        return value.get(prop) == expected
    return value.get(prop) == {"value": expected}


def _container_style_id(read_back: Draft, key: str) -> str | None:
    try:
        cid = resolve_container_id(read_back, key)
    except ValueError:
        return None
    styles = read_back[cid].get("Container::Style")
    return styles[0] if styles else None


def _container_style_value(read_back: Draft, key: str) -> dict[str, Any] | None:
    sid = _container_style_id(read_back, key)
    if sid is None:
        return None
    val = read_back.get(sid, {}).get("Value")
    return val if isinstance(val, dict) else {}


def _style_props_landed(read_back: Draft, key: str, props: dict[str, Any]) -> bool:
    """Did every prop in `props` (the SAME dict passed to pages.set_styles's `rules[key]`) land
    on the read-back Style node for the Container addressed by `key`? `key` is resolved the SAME way
    set_styles resolves it (pages.resolve_container_id): a Container id wins, else a unique Name;
    an unknown or ambiguous key returns False here (this is a read-back check, not the writer's
    hard raise). Mirrors pages._apply_style_props's own wrapping exactly (a dict value like
    `{"ref": token}` is stored verbatim; a plain scalar is auto-wrapped as `{"value": scalar}`;
    `None` means the property must be ABSENT — removed back to the theme default), so this checks
    the SAME shape the writer wrote, not a guessed one.
    """
    value = _container_style_value(read_back, key)
    if value is None:
        return False
    return all(_prop_matches(value, prop, v) for prop, v in props.items())


def _bind_config_landed(read_back: Draft, host: str, config: dict[str, Any]) -> bool:
    """Did every FieldMapping Value in `config` (the SAME dict passed to pages.bind_widget's own
    `config`) actually land on the read-back for the widget host addressed by `host`? Mirrors
    pages.resolve_container_id + pages._fm_index exactly, so this checks the shape the writer
    actually wrote, not a guessed one — same shell-vs-substance discipline as the widget/event
    checks below. An unresolvable host, or any key whose landed Value doesn't match, is False.
    """
    try:
        host_id = resolve_container_id(read_back, host)
    except ValueError:
        return False
    fm_index = _fm_index(read_back, host_id)
    for key, value in config.items():
        prop_id = fm_index.get(key)
        if prop_id is None or read_back.get(prop_id, {}).get("Value") != value:
            return False
    return True


def apply_page_build(
    client: KfClient,
    app_id: str,
    page_id: str,
    steps: list[PageBuildStep],
    publish: bool = False,
) -> PageBuildReport | Err:
    """GET the page draft -> apply every step offline via kfforge.pages's own builders (each
    returns a NEW draft; chained so ids added by an earlier step are addressable by a later one,
    e.g. add a container then add a widget INTO it) -> ONE guarded PUT -> READ-BACK verify every
    step actually landed (a minted node id for container/widget/popup/event; the exact prop values
    for style) -> optional publish, skipped if anything is missing.

    Every kfforge.pages builder already fails loud (ValueError) on a placeholder/unbound widget
    config or an unknown container — that rejection surfaces here as an `Err`, offline, before any
    write; nothing here weakens those checks. That offline check proves the REQUEST was
    well-formed; it says nothing about whether the live PUT actually kept it — the read-back below
    is what proves that.
    """
    draft = client.get_page_draft(app_id, page_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    applied: list[str] = []
    # (label, check) pairs: check takes the READ-BACK draft and returns True if that step landed.
    checks: list[tuple[str, Any]] = []
    new: Draft = draft
    try:
        for step in steps:
            if step.kind == "container":
                new, cid = add_container(new, **step.kwargs)
                label = f"container:{step.kwargs.get('name')}={cid}"
                applied.append(label)
                checks.append((label, lambda rb, nid=cid: nid in rb))
            elif step.kind == "widget":
                new, wid = add_widget(new, **step.kwargs)
                # add_widget returns only its HOST CONTAINER id — the widget's actual substance
                # (Script.web type, FieldMapping config) lives on a SEPARATE Component node, back-
                # referenced via Component.Container == wid. Checking the host id alone is NOT
                # enough: a write that keeps the empty host shell but drops the Component would
                # read as "verified" even though the widget itself is gone. Resolve it here, from
                # the OFFLINE post-add_widget draft (not the read-back), so the id being checked is
                # the real one this specific call minted.
                comp_id = next((k for k, v in new.items()
                               if isinstance(v, dict) and v.get("Kind") == "Component"
                               and v.get("Container") == wid), None)
                widget_ids = (wid, comp_id) if comp_id else (wid,)
                label = f"widget:{step.kwargs.get('widget')}={wid}"
                applied.append(label)
                checks.append((label, lambda rb, ids=widget_ids: all(i in rb for i in ids)))
            elif step.kind == "popup":
                new, pid = add_popup(new, **step.kwargs)
                label = f"popup:{step.kwargs.get('name')}={pid}"
                applied.append(label)
                checks.append((label, lambda rb, nid=pid: nid in rb))
            elif step.kind == "event":
                new, eid = add_event_mapping(new, **step.kwargs)
                # Same "shell vs substance" trap as the widget branch above: the EventMapping node
                # itself is the shell, the actual payload (the script text, or the target popup
                # id) lives on a SEPARATE Property node, back-referenced via
                # EventMapping::Property. Checking eid alone would read "verified" even if a write
                # dropped that Property and left an inert, payload-less EventMapping behind.
                prop_id = next((k for k, v in new.items()
                               if isinstance(v, dict) and v.get("Kind") == "Property"
                               and v.get("EventMapping") == eid), None)
                event_ids = (eid, prop_id) if prop_id else (eid,)
                label = f"event:{step.kwargs.get('type')}={eid}"
                applied.append(label)
                checks.append((label, lambda rb, ids=event_ids: all(i in rb for i in ids)))
            elif step.kind == "style":
                new = set_styles(new, **step.kwargs)
                rules = step.kwargs.get("rules", {})
                label = f"style:{sorted(rules)}"
                applied.append(label)
                checks.append((
                    label,
                    lambda rb, r=rules: all(
                        _style_props_landed(rb, name, props) for name, props in r.items()
                    ),
                ))
            elif step.kind == "bind":
                host = step.kwargs.get("host")
                config = step.kwargs.get("config", {})
                new = bind_widget(new, **step.kwargs)
                label = f"bind:{host}={sorted(config)}"
                applied.append(label)
                checks.append((
                    label,
                    lambda rb, h=host, c=config: _bind_config_landed(rb, h, c),
                ))
            elif step.kind == "design":
                # A whole nested, styled Container/Component tree from ONE design dict
                # (page.design.md) — the beautiful-page primitive. build_design threads the minted
                # ids internally (arbitrary depth, no name-uniqueness needed) and returns every
                # Container/widget-host id it added, so the read-back check proves the tree actually
                # landed live, not just that the PUT 200'd (THE RULE).
                new, design_ids = build_design(new, **step.kwargs)
                label = f"design:{step.kwargs.get('parent_id')}=[{len(design_ids)} nodes]"
                applied.append(label)
                checks.append((label, lambda rb, ids=tuple(design_ids): all(i in rb for i in ids)))
            else:
                raise ValueError(
                    f"unknown page-build step kind {step.kind!r}; expected one of "
                    "container/widget/popup/event/style/bind/design"
                )
    except ValueError as e:
        return Err("verify", f"offline page build rejected step: {e}")

    written = client.put_page_draft(app_id, page_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_page_draft(app_id, page_id)
    if isinstance(read_back, Err):
        return read_back

    verified = tuple(label for label, check in checks if check(read_back))
    missing = tuple(label for label, check in checks if not check(read_back))

    published = False
    if publish and not missing:
        pub = client.publish_page(app_id, page_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return PageBuildReport(
        app_id=app_id, page_id=page_id, applied=tuple(applied),
        verified=verified, missing=missing,
        node_counts=page_summary(read_back)["counts"],
        meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class NavigationReport:
    app_id: str
    menu_id: str | None
    unified_nav_ids: tuple[str, ...]
    swept_orphans: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id, "menu_id": self.menu_id,
            "unified_nav_ids": list(self.unified_nav_ids),
            "swept_orphans": list(self.swept_orphans), "meta_version": self.meta_version,
            "published": self.published, "isError": self.menu_id is None,
        }


def apply_navigation(
    client: KfClient,
    app_id: str,
    page_id: str,
    label: str,
    unify: bool = True,
    sweep: bool = False,
    publish: bool = False,
) -> NavigationReport | Err:
    """GET the app draft -> `nav.add_page_menu` a Menu entry for `page_id` into the FIRST
    Navigation found -> optionally `nav.point_all_navs_at` (unify every Navigation onto the same
    Menu set — "same view for all roles", CLAUDE.md App pages) -> optionally `nav.sweep_orphans` ->
    ONE guarded PUT -> read-back verify the new Menu is reachable from a Navigation -> optional
    publish.
    """
    draft = client.get_app_draft(app_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    navs = [k for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == "Navigation"]
    if not navs:
        return Err("verify", f"application {app_id!r} draft has no Navigation node to attach a menu to")
    nav_id = navs[0]
    before_menu_ids = set(draft.get(nav_id, {}).get("Navigation::Menu") or [])

    try:
        new = add_page_menu(draft, nav_id=nav_id, page_id=page_id, label=label)
        after_menu_ids = new[nav_id]["Navigation::Menu"]
        added_ids = [m for m in after_menu_ids if m not in before_menu_ids]
        if len(added_ids) != 1:
            return Err("verify",
                       f"expected exactly 1 new Menu id, got {len(added_ids)}: {added_ids}")
        menu_id = added_ids[0]

        swept: tuple[str, ...] = ()
        if unify:
            new = point_all_navs_at(new, menu_ids=list(after_menu_ids))
        if sweep:
            new, dropped = sweep_orphans(new)
            swept = tuple(dropped)
    except ValueError as e:
        return Err("verify", f"offline navigation build rejected the spec: {e}")

    written = client.put_app_draft(app_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_app_draft(app_id)
    if isinstance(read_back, Err):
        return read_back
    verified_id = menu_id if any(
        isinstance(v, dict) and v.get("Kind") == "Navigation"
        and menu_id in (v.get("Navigation::Menu") or [])
        for v in read_back.values()
    ) else None

    published = False
    if publish and verified_id:
        pub = client.publish_app(app_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return NavigationReport(
        app_id=app_id, menu_id=verified_id, unified_nav_ids=tuple(navs) if unify else (),
        swept_orphans=swept, meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class BuildPageOpReport:
    """Output-invariant audit for the GOVERNED page executor (#41): every sub-item of the
    compiled `build_page` op lands in exactly one of `built` / `skipped` / `refused`, and every
    built item is then read-back checked into `verified` or `missing` — never a silent drop
    (D6: a behavioral element is refused, not downgraded; a KPI with no buildable binding is
    skipped with its Known-Exclusion reason, not faked)."""
    app_id: str
    page_id: str | None
    page_name: str
    page_created: bool
    built: tuple[str, ...]
    skipped: tuple[str, ...]
    refused: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id, "page_id": self.page_id, "page_name": self.page_name,
            "page_created": self.page_created, "built": list(self.built),
            "skipped": list(self.skipped), "refused": list(self.refused),
            "verified": list(self.verified), "missing": list(self.missing),
            "meta_version": self.meta_version, "published": self.published,
            "isError": bool(self.missing or self.refused),
        }


class _PageOpState:
    __slots__ = ("body", "built", "checks", "draft", "popup_id_by_name", "refused", "skipped")

    def __init__(self, draft: Draft, body: str) -> None:
        self.draft: Draft = draft
        self.body: str = body
        self.built: list[str] = []
        self.skipped: list[str] = []
        self.refused: list[str] = []
        self.checks: list[tuple[str, Any]] = []
        self.popup_id_by_name: dict[str, str] = {}


def _find_page_id(pages: list[Any], name: str) -> str | None:
    for p in pages:
        if isinstance(p, dict) and p.get("Name") == name:
            return p.get("_id")
    return None


def _resolve_page(client: KfClient, app_id: str, name: str) -> tuple[str, bool] | Err:
    listed = client.list_pages(app_id)
    if isinstance(listed, Err):
        return listed
    page_id = _find_page_id(listed, name)
    if page_id is not None:
        return page_id, False
    made = client.create_page(app_id, name)
    if isinstance(made, Err):
        return made
    return made, True


def _find_body_container(draft: Draft) -> str | None:
    for k, v in draft.items():
        if isinstance(v, dict) and v.get("Kind") == "Container" and v.get("Type") == "Body":
            return k
    return None


def _init_page_target(
    client: KfClient, app_id: str, op_args: dict[str, Any]
) -> tuple[str, str, bool, Draft, str] | Err:
    name = op_args.get("name")
    if not name:
        return Err("verify", "build_page op has no 'name'")
    page_res = _resolve_page(client, app_id, name)
    if isinstance(page_res, Err):
        return page_res
    page_id, page_created = page_res

    draft = client.get_page_draft(app_id, page_id)
    if isinstance(draft, Err):
        return draft
    body = _find_body_container(draft)
    if body is None:
        return Err("verify", f"page {page_id} has no Body container — not a page draft?")

    return name, page_id, page_created, draft, body


def _widget_config(w: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(w.get("config") or {})
    row_fields = w.get("row_fields")
    if row_fields:
        cfg["row_fields"] = list(row_fields)
    return cfg


def _find_node_id(draft: Draft, kind: str, parent_key: str, parent_id: str) -> str | None:
    for k, v in draft.items():
        if isinstance(v, dict) and v.get("Kind") == kind and v.get(parent_key) == parent_id:
            return k
    return None


def _add_widget_checked(
    state: _PageOpState, container_id: str, w: dict[str, Any], label: str
) -> None:
    try:
        state.draft, wid = add_widget(
            state.draft,
            container_id=container_id,
            widget=w.get("slug", ""),
            config=_widget_config(w),
        )
    except ValueError as e:
        state.refused.append(f"{label}: {e}")
        return
    comp_id = _find_node_id(state.draft, "Component", "Container", wid)
    ids = (wid, comp_id) if comp_id else (wid,)
    state.built.append(label)
    state.checks.append((label, lambda rb, i=ids: all(x in rb for x in i)))


def _build_design_step(state: _PageOpState, design: Any) -> None:
    if not design:
        return
    try:
        state.draft, design_ids = build_design(state.draft, parent_id=state.body, design=design)
    except ValueError as e:
        state.refused.append(f"design: {e}")
        return
    label = f"design:[{len(design_ids)} nodes]"
    state.built.append(label)
    state.checks.append((label, lambda rb, ids=tuple(design_ids): all(i in rb for i in ids)))


def _build_widgets_step(state: _PageOpState, widgets: Any) -> None:
    for w in widgets or ():
        _add_widget_checked(state, state.body, w, f"widget:{w.get('slug')}")


def _build_popup_widgets(
    state: _PageOpState, pname: str, container_id: str, widgets: Any
) -> None:
    for w in widgets or ():
        _add_widget_checked(state, container_id, w, f"popup:{pname}/widget:{w.get('slug')}")


def _build_single_popup(state: _PageOpState, p: dict[str, Any]) -> None:
    pname = p.get("name", "")
    state.draft, pid = add_popup(state.draft, name=pname)
    state.popup_id_by_name[pname] = pid
    label = f"popup:{pname}"
    state.built.append(label)
    state.checks.append((label, lambda rb, i=pid: i in rb))
    popup_containers = state.draft[pid].get("Popup::Container") or [None]
    _build_popup_widgets(state, pname, popup_containers[0], p.get("widgets"))


def _build_popups_step(state: _PageOpState, popups: Any) -> None:
    for p in popups or ():
        _build_single_popup(state, p)


def _wire_action_event(
    state: _PageOpState, action: str, host: str, event: dict[str, Any]
) -> None:
    kind = event.get("kind")
    try:
        if kind == "OpenPopup":
            target_popup = event["target_popup"]
            popup_id = state.popup_id_by_name[target_popup]
            state.draft, eid = add_event_mapping(
                state.draft, container_id=host, type="OpenPopup", popup_id=popup_id
            )
        else:
            state.draft, eid = add_event_mapping(
                state.draft, container_id=host, type="JSAction", script=event.get("script")
            )
    except ValueError as err:
        state.refused.append(f"on_click:{action}: {err}")
        return

    prop_id = _find_node_id(state.draft, "Property", "EventMapping", eid)
    ids = (eid, prop_id) if prop_id else (eid,)
    label = f"on_click:{action}"
    state.built.append(label)
    state.checks.append((label, lambda rb, i=ids: all(x in rb for x in i)))


def _is_unknown_popup_target(
    event: dict[str, Any] | None, popup_ids: dict[str, str]
) -> bool:
    if event and event.get("kind") == "OpenPopup":
        return event.get("target_popup") not in popup_ids
    return False


def _build_single_action(
    state: _PageOpState, action: str, event: dict[str, Any] | None
) -> None:
    if _is_unknown_popup_target(event, state.popup_id_by_name):
        target = event.get("target_popup") if event else None
        state.refused.append(
            f"action:{action}: OpenPopup targets unknown popup {target!r} (D6: never a dead button)"
        )
        return

    try:
        state.draft, host = add_widget(
            state.draft,
            container_id=state.body,
            widget="general/button",
            config={"caption": action},
            name=f"action {action}",
        )
    except ValueError as err:
        state.refused.append(f"action:{action}: {err}")
        return

    label = f"action:{action}"
    state.built.append(label)
    state.checks.append((label, lambda rb, i=host: i in rb))

    if event is not None:
        _wire_action_event(state, action, host, event)


def _action_wiring_map(on_click: Any) -> dict[str, Any]:
    return {e["action"]: e for e in (on_click or ()) if isinstance(e, dict) and "action" in e}


def _merge_action_names(declared: list[str], wiring: dict[str, Any]) -> list[str]:
    return declared + [a for a in wiring if a not in declared]


def _build_actions_step(state: _PageOpState, actions: Any, on_click: Any) -> None:
    wiring = _action_wiring_map(on_click)
    for action in _merge_action_names(list(actions or ()), wiring):
        _build_single_action(state, action, wiring.get(action))


def _build_kpis_step(state: _PageOpState, kpis: Any) -> None:
    for k in kpis or ():
        state.skipped.append(
            f"kpi:{k}: live value binding is a Known Exclusion (#23); the op carries "
            "no flow binding for the metrics substitute — skipped, never faked"
        )


def _populate_page_state(state: _PageOpState, op_args: dict[str, Any]) -> None:
    _build_design_step(state, op_args.get("design"))
    _build_widgets_step(state, op_args.get("widgets"))
    _build_popups_step(state, op_args.get("popups"))
    _build_actions_step(state, op_args.get("actions"), op_args.get("on_click"))
    _build_kpis_step(state, op_args.get("kpis"))


def _evaluate_read_back_checks(
    read_back: Draft, checks: list[tuple[str, Any]]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    verified: list[str] = []
    missing: list[str] = []
    for label, check in checks:
        if check(read_back):
            verified.append(label)
        else:
            missing.append(label)
    return tuple(verified), tuple(missing)


def _is_publishable(publish: bool, state: _PageOpState, missing: tuple[str, ...]) -> bool:
    return bool(publish and state.built and not missing and not state.refused)


def _maybe_publish_page(
    client: KfClient,
    app_id: str,
    page_id: str,
    state: _PageOpState,
    missing: tuple[str, ...],
    publish: bool,
) -> bool | Err:
    if not _is_publishable(publish, state, missing):
        return False
    pub = client.publish_page(app_id, page_id)
    if isinstance(pub, Err):
        return pub
    return True


def _commit_and_verify_page(
    client: KfClient,
    app_id: str,
    page_id: str,
    version: str | None,
    state: _PageOpState,
    publish: bool,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None, bool] | Err:
    if state.built:
        written = client.put_page_draft(app_id, page_id, state.draft, expect_version=version)
        if isinstance(written, Err):
            return written
    read_back = client.get_page_draft(app_id, page_id)
    if isinstance(read_back, Err):
        return read_back

    verified, missing = _evaluate_read_back_checks(read_back, state.checks)
    pub_res = _maybe_publish_page(client, app_id, page_id, state, missing, publish)
    if isinstance(pub_res, Err):
        return pub_res

    return verified, missing, read_back.get(_META_VERSION), pub_res


def apply_build_page_op(
    client: KfClient,
    app_id: str,
    op_args: dict[str, Any],
    publish: bool = False,
) -> BuildPageOpReport | Err:
    """Execute ONE compiled `build_page` op (compile._op_build_page's args: name / widgets /
    kpis / actions / popups / on_click / design) against an explicitly-named app — the GOVERNED
    page entry (#41, ADR-0005). `apply_page_build` stays the raw primitive underneath; this is the
    layer that turns the plan's content+behavior into builder calls, resolving the ids only the
    run itself can know (a popup's own container for its widgets, a minted button's container
    for its on-click EventMapping, a popup NAME into the popup id an OpenPopup Property needs).

    Translation, in order, every item bucketed:
    - the beautiful-page `design` tree (page.design.md), if any -> a nested styled Container/
      Component tree built into the Body via build_design; a malformed design is refused, never
      downgraded to the flat skeleton (D6);
    - each widget -> the page Body container (layout geometry is platform-default, eval grades
      pixels — the Build-Correctness Bar vs Eval-Parity split);
    - each popup -> add_popup, then ITS widgets into the popup's own root container;
    - each action -> a `general/button` (caption = the action name); an `on_click` wiring for
      that action attaches an EventMapping to the button's container (OpenPopup resolves the
      target popup's id from THIS run; a wiring whose target popup is unknown is REFUSED);
    - each kpi -> `skipped` with its reason: a live-bound KPI number is a Known Exclusion (#23)
      and the op carries no flow binding to build the metrics substitute — never faked.

    One guarded PUT for everything built, then a read-back proves each built item actually
    landed (widget Component substance and EventMapping Property payload included, same
    shell-vs-substance discipline as apply_page_build). Publish is skipped unless everything
    built verified AND nothing was refused.
    """
    target = _init_page_target(client, app_id, op_args)
    if isinstance(target, Err):
        return target
    name, page_id, page_created, draft, body = target

    state = _PageOpState(draft=draft, body=body)
    _populate_page_state(state, op_args)

    outcome = _commit_and_verify_page(
        client, app_id, page_id, draft.get(_META_VERSION), state, publish
    )
    if isinstance(outcome, Err):
        return outcome
    verified, missing, meta_ver, published = outcome

    return BuildPageOpReport(
        app_id=app_id,
        page_id=page_id,
        page_name=name,
        page_created=page_created,
        built=tuple(state.built),
        skipped=tuple(state.skipped),
        refused=tuple(state.refused),
        verified=verified,
        missing=missing,
        meta_version=meta_ver,
        published=published,
    )
