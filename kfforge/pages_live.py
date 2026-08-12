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
from .pages import add_container, add_event_mapping, add_popup, add_widget, page_summary, set_styles

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
    """One page-build op. `kind` is one of "container" | "widget" | "popup" | "event" | "style";
    `kwargs` are passed straight to the matching kfforge.pages builder
    (add_container/add_widget/add_popup/add_event_mapping/set_styles) — see their own docstrings
    for the accepted keys. A spec dict from a caller (e.g. an MCP tool argument) becomes a list of
    these."""
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
    node = read_back.get(key)
    if isinstance(node, dict) and node.get("Kind") == "Container":
        container: dict[str, Any] | None = node
    else:
        matches = [v for v in read_back.values() if isinstance(v, dict)
                   and v.get("Kind") == "Container" and v.get("Name") == key]
        container = matches[0] if len(matches) == 1 else None
    if container is None:
        return False
    style_ids = container.get("Container::Style") or []
    if not style_ids:
        return False
    style = read_back.get(style_ids[0]) or {}
    value = style.get("Value") or {}
    for prop, v in props.items():
        if v is None:
            if prop in value:
                return False
        elif isinstance(v, dict):
            if value.get(prop) != v:
                return False
        else:
            if value.get(prop) != {"value": v}:
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
            else:
                raise ValueError(
                    f"unknown page-build step kind {step.kind!r}; expected one of "
                    "container/widget/popup/event/style"
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


def apply_build_page_op(
    client: KfClient,
    app_id: str,
    op_args: dict[str, Any],
    publish: bool = False,
) -> BuildPageOpReport | Err:
    """Execute ONE compiled `build_page` op (compile._op_build_page's args: name / widgets /
    kpis / actions / popups / on_click) against an explicitly-named app — the GOVERNED page
    entry (#41, ADR-0005). `apply_page_build` stays the raw primitive underneath; this is the
    layer that turns the plan's content+behavior into builder calls, resolving the ids only the
    run itself can know (a popup's own container for its widgets, a minted button's container
    for its on-click EventMapping, a popup NAME into the popup id an OpenPopup Property needs).

    Translation, in order, every item bucketed:
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
    name = op_args.get("name")
    if not name:
        return Err("verify", "build_page op has no 'name'")

    listed = client.list_pages(app_id)
    if isinstance(listed, Err):
        return listed
    page_id = next((p.get("_id") for p in listed
                    if isinstance(p, dict) and p.get("Name") == name), None)
    page_created = page_id is None
    if page_created:
        made = client.create_page(app_id, name)
        if isinstance(made, Err):
            return made
        page_id = made

    draft = client.get_page_draft(app_id, page_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)
    body = next((k for k, v in draft.items() if isinstance(v, dict)
                 and v.get("Kind") == "Container" and v.get("Type") == "Body"), None)
    if body is None:
        return Err("verify", f"page {page_id} has no Body container — not a page draft?")

    built: list[str] = []
    skipped: list[str] = []
    refused: list[str] = []
    checks: list[tuple[str, Any]] = []
    new: Draft = draft

    def _widget_config(w: dict[str, Any]) -> dict[str, Any]:
        cfg = dict(w.get("config") or {})
        if w.get("row_fields"):
            cfg["row_fields"] = list(w["row_fields"])
        return cfg

    def _add_widget_checked(container: str, w: dict[str, Any], label: str) -> None:
        nonlocal new
        try:
            new, wid = add_widget(new, container_id=container, widget=w.get("slug", ""),
                                  config=_widget_config(w))
        except ValueError as e:
            refused.append(f"{label}: {e}")
            return
        comp_id = next((k for k, v in new.items() if isinstance(v, dict)
                        and v.get("Kind") == "Component" and v.get("Container") == wid), None)
        ids = (wid, comp_id) if comp_id else (wid,)
        built.append(label)
        checks.append((label, lambda rb, i=ids: all(x in rb for x in i)))

    for w in op_args.get("widgets") or ():
        _add_widget_checked(body, w, f"widget:{w.get('slug')}")

    popup_id_by_name: dict[str, str] = {}
    for p in op_args.get("popups") or ():
        pname = p.get("name", "")
        new, pid = add_popup(new, name=pname)
        popup_id_by_name[pname] = pid
        built.append(f"popup:{pname}")
        checks.append((f"popup:{pname}", lambda rb, i=pid: i in rb))
        popup_container = (new[pid].get("Popup::Container") or [None])[0]
        for w in p.get("widgets") or ():
            _add_widget_checked(popup_container, w, f"popup:{pname}/widget:{w.get('slug')}")

    wiring = {e.get("action"): e for e in op_args.get("on_click") or ()}
    # an on_click naming an action outside `actions` still gets its button — compile already
    # validated action membership; belt-and-braces here so no declared behavior is dropped.
    for action in list(op_args.get("actions") or ()) + [a for a in wiring
                                                        if a not in (op_args.get("actions") or ())]:
        e = wiring.get(action)
        if e and e.get("kind") == "OpenPopup" and e.get("target_popup") not in popup_id_by_name:
            refused.append(f"action:{action}: OpenPopup targets unknown popup "
                           f"{e.get('target_popup')!r} (D6: never a dead button)")
            continue
        try:
            new, host = add_widget(new, container_id=body, widget="general/button",
                                   config={"caption": action}, name=f"action {action}")
        except ValueError as err:
            refused.append(f"action:{action}: {err}")
            continue
        built.append(f"action:{action}")
        checks.append((f"action:{action}", lambda rb, i=host: i in rb))
        if e:
            try:
                if e.get("kind") == "OpenPopup":
                    new, eid = add_event_mapping(new, container_id=host, type="OpenPopup",
                                                 popup_id=popup_id_by_name[e["target_popup"]])
                else:
                    new, eid = add_event_mapping(new, container_id=host, type="JSAction",
                                                 script=e.get("script"))
            except ValueError as err:
                refused.append(f"on_click:{action}: {err}")
                continue
            prop_id = next((k for k, v in new.items() if isinstance(v, dict)
                            and v.get("Kind") == "Property" and v.get("EventMapping") == eid), None)
            ids = (eid, prop_id) if prop_id else (eid,)
            built.append(f"on_click:{action}")
            checks.append((f"on_click:{action}", lambda rb, i=ids: all(x in rb for x in i)))

    for k in op_args.get("kpis") or ():
        skipped.append(f"kpi:{k}: live value binding is a Known Exclusion (#23); the op carries "
                       "no flow binding for the metrics substitute — skipped, never faked")

    if built:
        written = client.put_page_draft(app_id, page_id, new, expect_version=version)
        if isinstance(written, Err):
            return written
    read_back = client.get_page_draft(app_id, page_id)
    if isinstance(read_back, Err):
        return read_back
    verified = tuple(label for label, check in checks if check(read_back))
    missing = tuple(label for label, check in checks if not check(read_back))

    published = False
    if publish and built and not missing and not refused:
        pub = client.publish_page(app_id, page_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return BuildPageOpReport(
        app_id=app_id, page_id=page_id, page_name=name, page_created=page_created,
        built=tuple(built), skipped=tuple(skipped), refused=tuple(refused),
        verified=verified, missing=missing,
        meta_version=read_back.get(_META_VERSION), published=published,
    )
