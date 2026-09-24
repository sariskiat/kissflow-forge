"""Pure page-build helpers for `ForgeBuildPage`.

Ported from `app.infrastructure.kissflow.pages_live` (pre-refactor): the
step-application and read-back-verification logic for both `forge_build_page`
entries -- the raw `steps` primitive (`apply_page_build`) and the governed
`op` executor (`apply_build_page_op`). Every function here is pure: it reads
and returns `PageDraft`/wire-format dicts, and makes no port call. The use
case (`forge_build_page.ForgeBuildPage`) owns every port call (`get_page_draft`
/ `put_page_draft` / `list_pages` / `create_page` / `publish_page`) and drives
these functions around them.

A read-back check is a `(label, predicate)` pair: `predicate(read_back_wire)`
is `True` once that step's own node(s) actually landed live -- never trusting
the write response alone (CLAUDE.md > THE RULE). Several kinds check more
than the top-level id they mint, because the node they mint is only a SHELL:
a widget's real substance is a separate Component node
(`Container::Component`), an event's is a separate Property node
(`EventMapping::Property`) -- a write that keeps the shell but drops the
substance must not read as verified.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.domain.entities.page_draft import PageDraft, field_mapping_index

Draft = dict[str, Any]


@dataclass(frozen=True)
class PageBuildStep:
    """One page-build op. `kind` is one of "container" | "widget" | "popup" |
    "event" | "style" | "bind" | "design"; `kwargs` are passed straight to
    the matching `PageDraft` method (add_container/add_widget/add_popup/
    add_event_mapping/set_styles/bind_widget/build_design) -- see their own
    docstrings for the accepted keys. "design" takes `{parent_id, design}`
    and builds a whole nested styled Container/Component tree from one
    design dict (page.design.md).
    """

    kind: str
    kwargs: dict[str, Any]


# A (label, predicate) pair: `predicate(read_back_wire)` is True once that
# step's node(s) actually landed live.
Check = tuple[str, Callable[[Draft], bool]]


def _prop_matches(value: dict[str, Any], prop: str, expected: Any) -> bool:
    if expected is None:
        return prop not in value
    if isinstance(expected, dict):
        return value.get(prop) == expected
    return value.get(prop) == {"value": expected}


def _container_style_id(read_back: Draft, key: str) -> str | None:
    try:
        cid = PageDraft.from_wire(read_back).resolve_container_id(key)
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
    """Did every prop in `props` (the SAME dict passed to `PageDraft.
    set_styles`'s `rules[key]`) land on the read-back Style node for the
    Container addressed by `key`?

    `key` is resolved the SAME way `set_styles` resolves it
    (`PageDraft.resolve_container_id`): a Container id wins, else a unique
    Name; an unknown or ambiguous key returns False here (a read-back check,
    not the writer's hard raise). Mirrors the writer's own style-prop
    wrapping exactly (a dict value like `{"ref": token}` is stored verbatim;
    a plain scalar is auto-wrapped as `{"value": scalar}`; `None` means the
    property must be ABSENT -- removed back to the theme default).

    Args:
        read_back: The page draft's wire-format graph, as read back after
            the write.
        key: The Container id or Name `set_styles` was called with.
        props: The `{property: value}` dict that was requested for `key`.

    Returns:
        Whether every requested property landed with its requested value.
    """
    value = _container_style_value(read_back, key)
    if value is None:
        return False
    return all(_prop_matches(value, prop, v) for prop, v in props.items())


def _bind_config_landed(read_back: Draft, host: str, config: dict[str, Any]) -> bool:
    """Did every FieldMapping Value in `config` (the SAME dict passed to
    `PageDraft.bind_widget`'s own `config`) actually land on the read-back
    for the widget host addressed by `host`?

    Args:
        read_back: The page draft's wire-format graph, as read back after
            the write.
        host: The host Container id or Name `bind_widget` was called with.
        config: The `{FieldMapping Name: value}` dict that was requested.

    Returns:
        Whether every requested FieldMapping value landed, resolved off the
        read-back's own FieldMapping index (mirrors the writer's own index,
        so this checks the shape the writer actually wrote, not a guessed
        one).
    """
    try:
        host_id = PageDraft.from_wire(read_back).resolve_container_id(host)
    except ValueError:
        return False
    fm_index = field_mapping_index(read_back, host_id)
    for key, value in config.items():
        prop_id = fm_index.get(key)
        if prop_id is None or read_back.get(prop_id, {}).get("Value") != value:
            return False
    return True


def apply_build_steps(
    page: PageDraft, steps: list[PageBuildStep]
) -> tuple[PageDraft, list[str], list[Check]]:
    """Apply every raw-primitive step offline, chained so an id an earlier
    step minted is addressable by a later one (e.g. add a container then add
    a widget INTO it), and build the read-back check for each.

    Args:
        page: The page draft to build onto (a snapshot read).
        steps: The requested steps, in order.

    Returns:
        A tuple of the new `PageDraft`, the applied step labels (in order),
        and the `(label, predicate)` read-back check for each.

    Raises:
        ValueError: An unknown step `kind`, or the underlying `PageDraft`
            method rejected its `kwargs` (a placeholder/unbound widget
            config, an unknown container, ...).
    """
    applied: list[str] = []
    checks: list[Check] = []
    for step in steps:
        kwargs = step.kwargs
        if step.kind == "container":
            page, cid = page.add_container(**kwargs)
            label = f"container:{kwargs.get('name')}={cid}"
            applied.append(label)
            checks.append((label, lambda rb, nid=cid: nid in rb))
        elif step.kind == "widget":
            page, wid = page.add_widget(**kwargs)
            comp_id = _find_node_id(page.to_wire(), "Component", "Container", wid)
            widget_ids = (wid, comp_id) if comp_id else (wid,)
            label = f"widget:{kwargs.get('widget')}={wid}"
            applied.append(label)
            checks.append((label, lambda rb, ids=widget_ids: all(i in rb for i in ids)))
        elif step.kind == "popup":
            page, pid = page.add_popup(**kwargs)
            label = f"popup:{kwargs.get('name')}={pid}"
            applied.append(label)
            checks.append((label, lambda rb, nid=pid: nid in rb))
        elif step.kind == "event":
            page, eid = page.add_event_mapping(**kwargs)
            prop_id = _find_node_id(page.to_wire(), "Property", "EventMapping", eid)
            event_ids = (eid, prop_id) if prop_id else (eid,)
            label = f"event:{kwargs.get('type')}={eid}"
            applied.append(label)
            checks.append((label, lambda rb, ids=event_ids: all(i in rb for i in ids)))
        elif step.kind == "style":
            page = page.set_styles(**kwargs)
            rules = kwargs.get("rules", {})
            label = f"style:{sorted(rules)}"
            applied.append(label)
            checks.append(
                (
                    label,
                    lambda rb, r=rules: all(
                        _style_props_landed(rb, name, props)
                        for name, props in r.items()
                    ),
                )
            )
        elif step.kind == "bind":
            host = kwargs["host"]
            config = kwargs.get("config", {})
            page = page.bind_widget(**kwargs)
            label = f"bind:{host}={sorted(config)}"
            applied.append(label)
            checks.append(
                (label, lambda rb, h=host, c=config: _bind_config_landed(rb, h, c))
            )
        elif step.kind == "design":
            page, design_ids = page.build_design(**kwargs)
            label = f"design:{kwargs.get('parent_id')}=[{len(design_ids)} nodes]"
            applied.append(label)
            checks.append(
                (label, lambda rb, ids=tuple(design_ids): all(i in rb for i in ids))
            )
        else:
            raise ValueError(
                f"unknown page-build step kind {step.kind!r}; expected one of "
                "container/widget/popup/event/style/bind/design"
            )
    return page, applied, checks


def evaluate_checks(
    read_back: Draft, checks: list[Check]
) -> tuple[list[str], list[str]]:
    """Partition every check into verified and missing, against one read-back.

    Args:
        read_back: The page (or app) draft's wire-format graph, read back
            after the write.
        checks: The `(label, predicate)` pairs to evaluate.

    Returns:
        `(verified, missing)` labels, in the order `checks` listed them --
        every check lands in exactly one bucket.
    """
    verified = [label for label, check in checks if check(read_back)]
    missing = [label for label, check in checks if not check(read_back)]
    return verified, missing


def find_body_container(draft: Draft) -> str | None:
    """Find the page's own Body container.

    Args:
        draft: The page draft's wire-format graph.

    Returns:
        The Body container's id, or `None` when the draft carries none.
    """
    for k, v in draft.items():
        if (
            isinstance(v, dict)
            and v.get("Kind") == "Container"
            and v.get("Type") == "Body"
        ):
            return k
    return None


def find_page_id(pages: list[Any], name: str) -> str | None:
    """Find an existing page's id by its exact `Name`.

    Args:
        pages: `list_pages`'s own result.
        name: The page name to match.

    Returns:
        The first matching page's id, or `None` when no page (or no
        well-formed page record) carries that name.
    """
    for p in pages:
        if isinstance(p, dict) and p.get("Name") == name:
            return p.get("_id")
    return None


def _find_node_id(
    draft: Draft, kind: str, parent_key: str, parent_id: str
) -> str | None:
    for k, v in draft.items():
        if (
            isinstance(v, dict)
            and v.get("Kind") == kind
            and v.get(parent_key) == parent_id
        ):
            return k
    return None


def _widget_config(w: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(w.get("config") or {})
    row_fields = w.get("row_fields")
    if row_fields:
        cfg["row_fields"] = list(row_fields)
    return cfg


class PageOpState:
    """Mutable accumulator for one `op` build run.

    Threaded through every `_build_*_step` helper below instead of returned
    and reassigned each time, the same shape `app.infrastructure.kissflow.
    pages_live._PageOpState` used -- the op applies a handful of
    heterogeneous sub-steps (design, widgets, popups, actions, kpis) that all
    need to see each other's minted ids (a popup's id for its own on_click
    wiring), so one shared, in-place-mutated state is simpler than threading
    six return values through six call sites.
    """

    __slots__ = (
        "body",
        "built",
        "checks",
        "page",
        "popup_id_by_name",
        "refused",
        "skipped",
    )

    def __init__(self, draft: Draft, body: str) -> None:
        """Seed the state from a page draft snapshot and its Body container id.

        Args:
            draft: The page draft's wire-format graph, as read from the
                snapshot.
            body: The page's own Body container id (`find_body_container`).
        """
        self.page: PageDraft = PageDraft.from_wire(draft)
        self.body: str = body
        self.built: list[str] = []
        self.skipped: list[str] = []
        self.refused: list[str] = []
        self.checks: list[Check] = []
        self.popup_id_by_name: dict[str, str] = {}


def _build_design_step(state: PageOpState, design: Any) -> None:
    if not design:
        return
    try:
        state.page, design_ids = state.page.build_design(
            parent_id=state.body, design=design
        )
    except ValueError as e:
        state.refused.append(f"design: {e}")
        return
    label = f"design:[{len(design_ids)} nodes]"
    state.built.append(label)
    state.checks.append(
        (label, lambda rb, ids=tuple(design_ids): all(i in rb for i in ids))
    )


def _add_widget_checked(
    state: PageOpState, container_id: str, w: dict[str, Any], label: str
) -> None:
    try:
        state.page, wid = state.page.add_widget(
            container_id=container_id,
            widget=w.get("slug", ""),
            config=_widget_config(w),
        )
    except ValueError as e:
        state.refused.append(f"{label}: {e}")
        return
    comp_id = _find_node_id(state.page.to_wire(), "Component", "Container", wid)
    ids = (wid, comp_id) if comp_id else (wid,)
    state.built.append(label)
    state.checks.append((label, lambda rb, i=ids: all(x in rb for x in i)))


def _build_widgets_step(state: PageOpState, widgets: Any) -> None:
    for w in widgets or ():
        _add_widget_checked(state, state.body, w, f"widget:{w.get('slug')}")


def _build_popup_widgets(
    state: PageOpState, pname: str, container_id: str | None, widgets: Any
) -> None:
    """Place a popup's own widgets into its root container.

    `container_id` is `str | None` because the call site defaults to `None`
    when a popup came back with no `Popup::Container` at all -- harmless
    while there is nothing to place, and unbuildable the moment there is, so
    this says which, rather than handing `None` to `add_widget` and failing
    several frames away with an unrelated message.
    """
    if not widgets:
        return
    if container_id is None:
        raise ValueError(
            f"the popup {pname!r} has no Popup::Container node to hold its widgets"
        )
    for w in widgets:
        _add_widget_checked(
            state, container_id, w, f"popup:{pname}/widget:{w.get('slug')}"
        )


def _build_single_popup(state: PageOpState, p: dict[str, Any]) -> None:
    pname = p.get("name", "")
    state.page, pid = state.page.add_popup(name=pname)
    state.popup_id_by_name[pname] = pid
    label = f"popup:{pname}"
    state.built.append(label)
    state.checks.append((label, lambda rb, i=pid: i in rb))
    popup_containers = state.page.to_wire()[pid].get("Popup::Container") or [None]
    _build_popup_widgets(state, pname, popup_containers[0], p.get("widgets"))


def _build_popups_step(state: PageOpState, popups: Any) -> None:
    for p in popups or ():
        _build_single_popup(state, p)


def _wire_action_event(
    state: PageOpState, action: str, host: str, event: dict[str, Any]
) -> None:
    kind = event.get("kind")
    try:
        if kind == "OpenPopup":
            target_popup = event["target_popup"]
            popup_id = state.popup_id_by_name[target_popup]
            state.page, eid = state.page.add_event_mapping(
                container_id=host, type="OpenPopup", popup_id=popup_id
            )
        else:
            state.page, eid = state.page.add_event_mapping(
                container_id=host,
                type="JSAction",
                script=event.get("script"),
            )
    except ValueError as err:
        state.refused.append(f"on_click:{action}: {err}")
        return

    prop_id = _find_node_id(state.page.to_wire(), "Property", "EventMapping", eid)
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
    state: PageOpState, action: str, event: dict[str, Any] | None
) -> None:
    if _is_unknown_popup_target(event, state.popup_id_by_name):
        target = event.get("target_popup") if event else None
        state.refused.append(
            f"action:{action}: OpenPopup targets unknown popup {target!r} "
            "(D6: never a dead button)"
        )
        return

    try:
        state.page, host = state.page.add_widget(
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
    return {
        e["action"]: e
        for e in (on_click or ())
        if isinstance(e, dict) and "action" in e
    }


def _merge_action_names(declared: list[str], wiring: dict[str, Any]) -> list[str]:
    return declared + [a for a in wiring if a not in declared]


def _build_actions_step(state: PageOpState, actions: Any, on_click: Any) -> None:
    wiring = _action_wiring_map(on_click)
    for action in _merge_action_names(list(actions or ()), wiring):
        _build_single_action(state, action, wiring.get(action))


def _build_kpis_step(state: PageOpState, kpis: Any) -> None:
    for k in kpis or ():
        state.skipped.append(
            f"kpi:{k}: live value binding is a Known Exclusion (#23); the op "
            "carries no flow binding for the metrics substitute — skipped, "
            "never faked"
        )


def populate_page_state(state: PageOpState, op_args: dict[str, Any]) -> None:
    """Build every sub-item a compiled `build_page` op declares, in order.

    Args:
        state: The op run's shared, in-place-mutated state.
        op_args: The compiled op's own args (name/widgets/kpis/actions/
            popups/on_click/design).
    """
    _build_design_step(state, op_args.get("design"))
    _build_widgets_step(state, op_args.get("widgets"))
    _build_popups_step(state, op_args.get("popups"))
    _build_actions_step(state, op_args.get("actions"), op_args.get("on_click"))
    _build_kpis_step(state, op_args.get("kpis"))
