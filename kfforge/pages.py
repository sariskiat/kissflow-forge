"""Pure, offline operations on Kissflow's app-PAGE node-graph (Page/Container/Component/...).

No network, no Kissflow calls. Every wire shape this module writes is loaded from a template in
shapes/*.json (captured empirically off a real builder page, see CLAUDE.md section Pages) and
instantiated with fresh ids; nothing here re-hardcodes a node shape that shapes/ already knows.
Knowledge stays data, this module only clones and wires it, mirroring kfforge.graph's convention:
every builder function is pure (returns a NEW draft, never mutates its input) and fails loud
(ValueError) rather than silently writing a corrupt graph.

Scope note (YAGNI, logged rather than silently omitted): the widget palette, containers, popups
and styling are covered because pages.py's own test list requires them. A few page-graph node
kinds documented in shapes/ have NO dedicated builder here because no caller in this pack's API
needs one yet and their config surface is genuinely ambiguous without a concrete use case:
`Variable` (page-local state; a KPI-tile Variable's shape differs from a JSON/Text one), the full
multi-pane `Tabs`/`Tab` mechanism beyond the single-entry `general/tab` widget (tabs.json's own
notes describe it as a separate composition), and `Criteria`/`Condition` (two different LHSType
semantics -- DatasourceParameter vs PageVariable -- with no single obvious calling convention).
Building any of those later is a straight `_instantiate()` call against its own shapes/*.json
template, same as everything below; nothing is technically blocked, they are just not built ahead
of a real need.
"""
from __future__ import annotations

import copy
import json
import pathlib
import re
import secrets
import string
from typing import Any, Literal

Draft = dict[str, Any]

SHAPES_DIR = pathlib.Path(__file__).parent.parent / "shapes"

# The full 28-script widget palette (CLAUDE.md: "COMPLETE widget palette (2026-08-06 ... 28
# scripts)"). Keys are the wire `Script.web` slug a caller thinks in; values are shapes/ filenames
# (stem only). An explicit table beats deriving the filename from the slug: 3 of the 28 (custom,
# metrics, repeater) have no "<category>/<name>" split, and "rich_text"/"progressbar" contain
# underscores that must NOT become slashes -- there is no lossless mechanical rule.
WIDGET_SLUGS: dict[str, str] = {
    "general/label": "widget_general_label",
    "general/icon": "widget_general_icon",
    "general/button": "widget_general_button",
    "general/divider": "widget_general_divider",
    "general/progressbar": "widget_general_progressbar",
    "general/breadcrumbs": "widget_general_breadcrumbs",
    "general/card": "widget_general_card",
    "general/image": "widget_general_image",
    "general/hyperlink": "widget_general_hyperlink",
    "general/rich_text": "widget_general_rich_text",
    "general/iframe": "widget_general_iframe",
    "general/tab": "widget_general_tab",
    "general/masterdetail": "widget_general_masterdetail",
    "custom": "widget_custom",
    "view/form": "widget_view_form",
    "view/table": "widget_view_table",
    "view/gallery": "widget_view_gallery",
    "view/sheet": "widget_view_sheet",
    "view/kanban": "widget_view_kanban",
    "view/matrix": "widget_view_matrix",
    "view/list": "widget_view_list",
    "view/timeline": "widget_view_timeline",
    "report/chart": "widget_report_chart",
    "report/table": "widget_report_table",
    "report/card": "widget_report_card",
    "report/pivot": "widget_report_pivot",
    "metrics": "widget_metrics",
    "repeater": "widget_repeater",
}

# Config keys add_widget REQUIRES before it writes anything, per widget slug. A widget with no
# entry here needs no config at all (every general/* widget except masterdetail, plus custom --
# none of them bind to a flow/report, they only hold their own display config, see
# shapes/widget_general_*.json). Kept as a flat literal table rather than derived from the shape
# files: "which FieldMapping names are load-bearing enough to demand a real caller value, vs which
# have a genuinely sane platform default" is a judgement call a shape file cannot make for itself
# -- e.g. widget_metrics.json's own metrics_type default ("stepmetrics") IS sane and deliberately
# left OUT of this table (its own note: "the only metrics_type observed"), while flow_id/report_id
# have no possible sane default -- they name a specific caller flow/report that cannot be guessed,
# and a page publishing with the shape's own placeholder there is exactly THE-RULE failure class
# (CLAUDE.md: publishes clean, renders broken) this table exists to close off.
WIDGET_REQUIRED_CONFIG: dict[str, tuple[str, ...]] = {
    **{slug: ("flow_type", "flow_id", "view_id") for slug in WIDGET_SLUGS if slug.startswith("view/")},
    # view/form is the ONE view/* slug whose live working example ships view_id=null (plus
    # instance_id/activity_instance_id=null -- see widget_view_form.json): a truthy view_id
    # requirement makes that exact captured binding unreachable, so view/form drops view_id to
    # optional (flow_type/flow_id stay required -- they still name a real flow that cannot be
    # guessed). This explicit entry overrides the view/* comprehension above (later key wins). Every
    # OTHER view/* slug keeps view_id required until a live example proves otherwise (ticket #21).
    "view/form": ("flow_type", "flow_id"),
    # rich text renders ONLY what the value Property holds (plain HTML string, #51/#58); an
    # add with no value used to write a Property with NO Value key at all and publish an
    # empty block — require it so the miss is loud at build time, not silent at render.
    "general/rich_text": ("value",),
    # report/* binds via the SAME flow_type/flow_id/report_id trio as view/* binds flow_type/
    # flow_id/view_id (widget_report_*.json's own note) -- report_id alone is not enough: every
    # report shape's flow_id FieldMapping is ALSO Sample-shaped ("Flow_Sample01"), so a build that
    # supplies only report_id leaves that placeholder in place for the leak scan to catch.
    **{slug: ("flow_type", "flow_id", "report_id") for slug in WIDGET_SLUGS if slug.startswith("report/")},
    "metrics": ("flow_type", "flow_id"),
    # titleField/subTitleField/sortField are binding-class config too, not display config: they
    # name the real per-row field ids that drive what a row displays and how rows sort
    # (widget_general_masterdetail.json's own titleField/subTitleField/sortField FieldMappings),
    # and their shape defaults ("Sample_Title_Field"/"Sample_Subtitle_Field") are exactly the
    # placeholder-leak shape THE RULE warns about: publishes clean, wrong field bound live.
    "general/masterdetail": (
        "flow_type", "flow_id", "view_id", "titleField", "subTitleField", "sortField",
    ),
    "repeater": ("flow_type", "flow_id", "view_id", "row_fields"),
}

_ALPHABET = string.ascii_letters + string.digits
# Real captured ids are `<Kind>_<10-char-rand>` (shapes/*.json's own notes, e.g. "Button_<10-char-
# rand>"); unlike kfforge.graph's deterministic field ids (which must be idempotent-reconcile-safe
# across re-runs keyed by NAME), a page widget-add is a one-shot clone-a-template operation with no
# name-keyed idempotency to preserve, so a random mint matching the platform's own observed id
# shape is the simpler, equally-correct choice here (ponytail: no seed-threading machinery needed).
#
# Two placeholder SHAPES seen in shapes/*.json, both must be caught: "<Kind>_SampleNN" (e.g.
# "Flow_Sample01", "Report_Sample01" -- a Sample-suffixed real id) and "Sample_<Field>" (e.g.
# "Sample_Title_Field", "Sample_Subtitle_Field" -- a Sample-PREFIXED display-field placeholder,
# widget_general_masterdetail.json's titleField/subTitleField/sortField defaults). The prefix
# group is therefore OPTIONAL, not required like the old pattern -- but still anchored with no
# space allowed anywhere, so ordinary prose that merely contains the word "Sample" (e.g. "Sample
# Master Detail", "Sample Button", "Sample label text" -- every widget's own display-text default)
# never matches: a space is never in the allowed tail charset, so those fail at the first space.
_SAMPLE_LEAK_RE = re.compile(r"^(?:[A-Za-z]+_)?Sample[_A-Za-z0-9]*$")


def load_shape(name: str) -> dict:
    """Read shapes/<name>.json. Unknown name -> ValueError listing every known shape (never a bare
    FileNotFoundError -- a typo'd shape name should read as a clear, fixable mistake)."""
    path = SHAPES_DIR / f"{name}.json"
    if not path.is_file():
        known = sorted(p.stem for p in SHAPES_DIR.glob("*.json"))
        raise ValueError(f"no shape named {name!r}; known shapes: {known}")
    return json.loads(path.read_text(encoding="utf-8"))


def _mint(kind: str) -> str:
    return f"{kind}_" + "".join(secrets.choice(_ALPHABET) for _ in range(10))


def _leaf_strings(value: Any, path: str) -> list[tuple[str, str]]:
    """Every string found anywhere under `value`, paired with a dotted/bracketed path describing
    where it sits (e.g. "Property_xyz.Value" or "Component_abc.Data.selectedFields[0]").

    Walks EVERY key, "Value"/"Data" included. The leak scan below used to skip exactly those two
    keys on the theory that they only ever hold free-form content, never a structural cross-
    reference -- refuted 2026-08-06 (review finding): shapes/event_mapping.json's OpenPopup
    Property.Value is a real Popup id, and shapes/menu_navigation.json's Page-reference Property.
    Value is a real Page id, and BOTH instantiated verbatim with no raise the whole time this skip
    existed, whenever a caller forgot to pass them via `external`. A "Value"/"Data" key is exactly
    as capable of hiding an unresolved structural id as a "::"-list back-ref is; the only thing
    that ever made it look safe was the CALLER always happening to fill it in, which is a property
    of the caller, not of the key name.
    """
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, list):
        out: list[tuple[str, str]] = []
        for i, item in enumerate(value):
            out.extend(_leaf_strings(item, f"{path}[{i}]"))
        return out
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            out.extend(_leaf_strings(v, f"{path}.{k}"))
        return out
    return []


def _keep_subset(template: dict[str, dict], keep: tuple[str, ...]) -> dict[str, dict]:
    """A filtered subset of a shape's template, keeping only the named Sample-id nodes -- the
    pattern nav.add_page_menu uses to instantiate a slice of menu_navigation.json, and
    _bind_repeater_row_label below uses for variable_ref.json. Every name in `keep` must be a real
    key of `template`: ValueError immediately (not a later, more confusing KeyError from whatever
    code tries to look the missing node up) if the shape file ever drifts out from under a stale
    `keep` list.
    """
    missing = [k for k in keep if k not in template]
    if missing:
        raise ValueError(f"shape template has no node(s) named {missing}; keep= is stale")
    return {k: v for k, v in template.items() if k in keep}


def _instantiate(
    template: dict[str, dict],
    *,
    external: dict[str, str] | None = None,
    force_ids: dict[str, str] | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Clone a shape template (or a filtered subset of one) with fresh ids.

    Every "Sample" id used as a dict KEY in `template` is minted a fresh real id (or, for a key
    named in `force_ids`, forced to that exact literal -- used for the platform's own well-known
    literals like "Container001"). Every occurrence of one of those Sample ids as a VALUE anywhere
    in any node (a scalar back-ref, or inside a `::`-list) is rewritten to match, so the cloned
    subtree is internally consistent under its NEW ids.

    `external` maps a Sample id that is NOT a key of `template` (so it will never be minted) to a
    REAL, already-existing id in the caller's draft -- this is how a clone attaches to something
    outside itself (e.g. "Page_Sample01" -> the real page id, "Container001" -> the real parent
    container id, "Navigation_Sample01" -> a real Navigation id already in an app draft).

    Returns (new nodes keyed by their NEW id, old Sample-id -> new-id map) so a caller can look up
    "which new id corresponds to Container_Sample01" etc. Raises ValueError if any Sample-shaped id
    leaks through unresolved (not minted, not covered by `external`) -- a silently wrong reference
    is exactly the class of bug this whole engine exists to avoid (see CLAUDE.md "THE RULE").
    """
    external = external or {}
    force_ids = force_ids or {}
    idmap = {old: force_ids.get(old) or _mint(old.split("_")[0]) for old in template}

    def remap(v: Any) -> Any:
        if isinstance(v, str):
            if v in idmap:
                return idmap[v]
            if v in external:
                return external[v]
            return v
        if isinstance(v, list):
            return [remap(x) for x in v]
        if isinstance(v, dict):
            return {k: remap(x) for k, x in v.items()}
        return v

    out: dict[str, dict] = {}
    for old_id, node in template.items():
        new_node = remap(copy.deepcopy(node))
        new_node["Id"] = idmap[old_id]
        out[idmap[old_id]] = new_node

    # Anything the caller explicitly supplied via `external` is a real id by declaration, even if
    # it happens to be shaped like a Sample placeholder (e.g. a hand-built test fixture reusing
    # "Navigation_Sample01" as an already-real id) -- only a string NEITHER minted nor declared is
    # an actual leak. Scans EVERY key of every node, "Value"/"Data" included -- see _leaf_strings.
    leaked = sorted(
        (path, s)
        for node in out.values()
        for path, s in _leaf_strings(node, node["Id"])
        if _SAMPLE_LEAK_RE.match(s) and s not in external.values()
    )
    if leaked:
        detail = ", ".join(f"{path}={s!r}" for path, s in leaked)
        raise ValueError(
            f"unresolved shape placeholder id(s) at {detail} -- pass them via external= "
            "(the real id they should point at, e.g. the page/container/nav/popup they attach to)"
        )
    return out, idmap


def _page_id(draft: Draft) -> str:
    root = draft.get("Root")
    if not isinstance(root, str) or root not in draft:
        raise ValueError("draft has no valid 'Root' page node")
    return root


def _require_container(draft: Draft, container_id: str) -> None:
    node = draft.get(container_id)
    if not isinstance(node, dict) or node.get("Kind") != "Container":
        raise ValueError(f"no Container node {container_id!r} in this page")


def _require_popup(draft: Draft, popup_id: str) -> None:
    node = draft.get(popup_id)
    if not isinstance(node, dict) or node.get("Kind") != "Popup":
        raise ValueError(f"no Popup node {popup_id!r} in this page")


def _apply_style_props(style_node: dict, props: dict[str, Any]) -> None:
    """Merge `props` into a Style node's Value dict. Pure mutation of the (already-cloned) node.

    A dict value (`{"value": "#hex"}` or `{"ref": "Color.Token"}`) is stored verbatim -- both forms
    render live for colour keys (page_style.json), and only the caller can know which one is meant.
    A plain string is dimensional shorthand, auto-wrapped as `{"value": <str>}` -- dimensional keys
    are ALWAYS the value-form on a page, never a token ref (page_style.json). `None` removes the
    property, returning it to the theme default (Kissflow persists only non-default style values,
    same convention as kfforge.graph.set_section_style).
    """
    value = dict(style_node.get("Value") or {})
    for key, v in props.items():
        if v is None:
            value.pop(key, None)
        elif isinstance(v, dict):
            value[key] = v
        else:
            value[key] = {"value": v}
    if value:
        style_node["Value"] = value
    else:
        style_node.pop("Value", None)


def _fm_index(nodes: dict[str, dict], host_id: str) -> dict[str, str]:
    """FieldMapping Name -> its Property node's id, for one widget's own host container."""
    out: dict[str, str] = {}
    for fmid in nodes[host_id].get("Container::FieldMapping") or []:
        fm = nodes[fmid]
        props = fm.get("FieldMapping::Property") or []
        if fm.get("Name") and props:
            out[fm["Name"]] = props[0]
    return out


def _raw_fm_values(template: dict[str, dict]) -> dict[str, str]:
    """FieldMapping Name -> its Property node's own placeholder Value, read directly off an
    UNINSTANTIATED shape template (Sample ids, before _instantiate mints anything).

    Used only to pre-resolve the small set of widget bindings (flow_id/report_id) whose shape
    default is ITSELF a Sample-shaped placeholder string (e.g. "Flow_Sample01"): add_widget passes
    those through `external` at _instantiate time so the clone comes out already correct, rather
    than leaving the placeholder in place for _instantiate's own leak scan (now Value/Data-aware,
    see _leaf_strings) to trip over before add_widget's later config patch ever gets a chance to
    fix it.
    """
    out: dict[str, str] = {}
    for node in template.values():
        if node.get("Kind") != "FieldMapping" or not node.get("Name"):
            continue
        prop_ids = node.get("FieldMapping::Property") or []
        if not prop_ids:
            continue
        value = template.get(prop_ids[0], {}).get("Value")
        if isinstance(value, str):
            out[node["Name"]] = value
    return out


def new_page_graph(page_name: str) -> Draft:
    """A virgin 4-node page (shapes/page_virgin.json), matching `POST .../application/{app}/page`.

    The root Body container and its Style are forced to the platform's own well-known literal ids
    "Container001"/"Style001" (page_virgin.json's own note: every real page uses these literally,
    not a random id) -- every widget/container shape in this pack assumes that literal as its
    default parent, so forcing it here means adding directly to the page root needs zero patching.
    """
    shape = load_shape("page_virgin")
    nodes, idmap = _instantiate(
        shape["template"],
        force_ids={"Container_Sample01": "Container001", "Style_Sample01": "Style001"},
    )
    page_id = idmap["Page_Sample01"]
    nodes[page_id]["Name"] = page_name

    draft: Draft = dict(nodes)
    draft["Root"] = page_id
    return draft


def add_container(
    page: Draft, *, parent_id: str, name: str, layout: dict[str, Any] | None = None
) -> tuple[Draft, str]:
    """Add a layout Container (shapes/container.json) as a child of `parent_id`. Pure.

    `layout` merges into the new container's own Style.Value (dimensional keys like
    "Container.Row.Gap"/"Container.Padding.Top" -- see _apply_style_props); the container's page-
    grid placement (LayoutConfig colSpan/rowSpan) is deliberately left at the shape's own default,
    out of scope here (YAGNI: no caller in this pack's API needs to place page-grid geometry).
    """
    new: Draft = copy.deepcopy(page)
    _require_container(new, parent_id)

    shape = load_shape("container")
    nodes, idmap = _instantiate(shape["template"], external={"Container001": parent_id})
    cid = idmap["Container_Sample01"]
    nodes[cid]["Name"] = name
    if layout:
        sid = nodes[cid]["Container::Style"][0]
        _apply_style_props(nodes[sid], layout)

    new.update(nodes)
    new[parent_id].setdefault("Container::Container", []).append(cid)
    return new, cid


def _bind_repeater_row_label(draft: Draft, *, page_id: str, content_id: str, field: str) -> tuple[Draft, str]:
    """One repeater row-template label, bound to live per-row data via a VariableRef.

    Composes two shapes per variable_ref.json's own cross-reference note: clone a complete
    widget_general_label host (real Container/Component/Style structure), then retarget its
    Property from a static Value to the Variable-bound form and instantiate the VariableRef node
    itself off variable_ref.json's own shape (_keep_subset + external -- the same pattern
    nav.add_page_menu uses for menu_navigation.json). Registering the VariableRef into the page's
    own Page::VariableRef list -- the step variable_ref.json calls "THE gotcha" -- is the caller's
    (add_widget's) job; this helper only returns the id so the caller can collect and register
    every one at once.
    """
    label_shape = load_shape("widget_general_label")
    nodes, idmap = _instantiate(
        label_shape["template"], external={"Page_Sample01": page_id, "Container001": content_id}
    )
    host_id = idmap["Container_Sample01"]
    prop_id = idmap["Property_Sample01"]

    # Type:"Variable" and a static "Value" are mutually exclusive on every capture seen -- drop
    # the placeholder text, don't leave it stale beside the new binding.
    nodes[prop_id].pop("Value", None)
    nodes[prop_id]["Type"] = "Variable"

    vref_shape = load_shape("variable_ref")
    vref_subset = _keep_subset(vref_shape["template"], ("VariableRef_Sample01",))
    vref_nodes, vref_idmap = _instantiate(
        vref_subset,
        external={"Container_Sample01": host_id, "Page_Sample01": page_id, "Property_Sample01": prop_id},
    )
    vref_id = vref_idmap["VariableRef_Sample01"]
    vref_nodes[vref_id]["Variable"] = f"item.{field}"

    nodes[prop_id]["Property::VariableRef"] = [vref_id]
    nodes.update(vref_nodes)
    nodes[host_id].setdefault("Container::VariableRef", []).append(vref_id)

    new: Draft = copy.deepcopy(draft)
    new.update(nodes)
    new[content_id].setdefault("Container::Container", []).append(host_id)
    return new, vref_id


def add_widget(
    page: Draft, *, container_id: str, widget: str, config: dict[str, Any], name: str | None = None
) -> tuple[Draft, str]:
    """Add a widget (any of the 28 WIDGET_SLUGS) as a child of `container_id`. Pure.

    `config` supplies binding values keyed by the shape's own FieldMapping Name (flow_type/flow_id/
    view_id | report_id | metrics_type | title/caption/... -- whatever that widget's shape defines;
    see WIDGET_SLUGS and shapes/widget_*.json). A key with no matching FieldMapping slot on that
    widget raises ValueError listing the valid keys, same as an unknown widget name. A widget whose
    binding is load-bearing (view/*, report/*, metrics, general/masterdetail, repeater -- see
    WIDGET_REQUIRED_CONFIG) additionally raises, BEFORE any node is written, if any of ITS required
    keys are missing or falsy: leaving one unset does not fall back to a sane default, it silently
    binds the published page to the shape's own placeholder flow/report id -- a page that publishes
    clean and renders broken (CLAUDE.md "THE RULE").

    `name`, if given, sets BOTH the widget's host Container Name and its Component Name (kept in
    sync, mirroring how every captured widget shape already pairs them -- see set_styles) so two
    widgets of the same kind on one page can be styled independently via set_styles instead of
    colliding on the shape's shared default name.

    The repeater widget accepts one extra, repeater-only config key: `row_fields` (a list of field
    names -- itself required for repeater, see WIDGET_REQUIRED_CONFIG: a repeater bound to zero
    columns is the same "publishes clean, shows nothing real" failure the required-config check
    exists to catch). For each field, a bound row-template label is added inside the repeater's own
    content container via _bind_repeater_row_label, and every VariableRef minted that way is
    registered in the page's Page::VariableRef list -- omitting that registration is the documented,
    silent failure mode (variable_ref.json: a repeater with unregistered refs "visibly repeats N
    times but shows no per-row data"). The same field list is ALSO written into the widget's own
    `selectedFields` binding, both the FieldMapping/Property site and the Component.Data mirror
    (widget_repeater.json: "write both rather than assuming either alone is read") -- selectedFields
    is what makes the repeater fetch those columns at all, independently of the per-row bound labels
    that merely display them.
    """
    if widget not in WIDGET_SLUGS:
        raise ValueError(f"unknown widget {widget!r}; known widgets: {sorted(WIDGET_SLUGS)}")
    if "row_fields" in config and widget != "repeater":
        raise ValueError(f"widget {widget!r} has no slot for 'row_fields' (repeater-only)")

    required = WIDGET_REQUIRED_CONFIG.get(widget, ())
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise ValueError(
            f"widget {widget!r} requires config key(s) {missing}; got config={sorted(config)} -- "
            "a page would otherwise publish clean and bind to the shape's own placeholder id"
        )

    new: Draft = copy.deepcopy(page)
    page_id = _page_id(new)
    _require_container(new, container_id)

    shape = load_shape(WIDGET_SLUGS[widget])
    row_fields = config.get("row_fields")
    body = {k: v for k, v in config.items() if k != "row_fields"}

    # Pre-resolve the shape's own Sample-shaped placeholder values (flow_id/report_id, when this
    # widget has them) to the caller's real ones BEFORE cloning, so the clone never even contains
    # the placeholder string for _instantiate's own leak scan to trip over -- see _raw_fm_values.
    raw_values = _raw_fm_values(shape["template"])
    value_external = {
        raw_values[key]: value
        for key, value in body.items()
        if key in raw_values and _SAMPLE_LEAK_RE.match(raw_values[key])
    }
    try:
        nodes, idmap = _instantiate(
            shape["template"],
            external={"Page_Sample01": page_id, "Container001": container_id, **value_external},
        )
    except ValueError:
        # _instantiate's own message says "pass them via external=" -- correct advice for a caller
        # of _instantiate, but add_widget's own caller has no such parameter, only `config`. Any
        # FieldMapping name whose raw shape default is Sample-shaped AND whose placeholder value
        # never made it into value_external (i.e. WIDGET_REQUIRED_CONFIG missed it, or a caller
        # somehow reached this despite the upfront check) is exactly the slot still leaking --
        # rederived from raw_values/value_external rather than parsed out of the caught message,
        # so the translation stays correct even if _instantiate's own wording changes later.
        unresolved = sorted(
            fm_name
            for fm_name, raw_val in raw_values.items()
            if _SAMPLE_LEAK_RE.match(raw_val) and raw_val not in value_external
        )
        if not unresolved:
            raise
        raise ValueError(
            f"widget {widget!r} requires config key(s) {unresolved}; got config={sorted(body)} -- "
            "a page would otherwise publish clean and bind to the shape's own placeholder id"
        ) from None
    host_id = idmap["Container_Sample01"]
    comp_id = idmap.get("Component_Sample01")

    if name is not None:
        nodes[host_id]["Name"] = name
        if comp_id is not None:
            nodes[comp_id]["Name"] = name

    fm_index = _fm_index(nodes, host_id)
    bad = set(body) - set(fm_index)
    if bad:
        raise ValueError(
            f"widget {widget!r} has no slot for {sorted(bad)}; valid keys: {sorted(fm_index)}"
        )
    for key, value in body.items():
        nodes[fm_index[key]]["Value"] = value

    if comp_id is not None:
        data = nodes[comp_id].get("Data")
        if isinstance(data, dict):
            for key, value in body.items():
                if key in data:            # mirror bindings widget_*.json shows double-encoded
                    data[key] = value

    if row_fields:
        # selectedFields is a SEPARATE binding from the per-row bound labels below: it drives what
        # the repeater fetches, they drive what a fetched row displays. Both read row_fields.
        sf_id = fm_index.get("selectedFields")
        if sf_id is not None:
            nodes[sf_id]["Value"] = list(row_fields)
        if comp_id is not None:
            data = nodes[comp_id].get("Data")
            if isinstance(data, dict) and "selectedFields" in data:
                data["selectedFields"] = list(row_fields)

    new.update(nodes)
    new[container_id].setdefault("Container::Container", []).append(host_id)

    if row_fields:
        content_id = idmap.get("Container_Sample02")
        if content_id is None:
            raise ValueError(f"widget {widget!r} has no row-template container to bind row_fields into")
        vref_ids: list[str] = []
        for field in row_fields:
            new, vref_id = _bind_repeater_row_label(new, page_id=page_id, content_id=content_id, field=field)
            vref_ids.append(vref_id)
        new[page_id].setdefault("Page::VariableRef", []).extend(vref_ids)

    return new, host_id


def add_popup(page: Draft, *, name: str) -> tuple[Draft, str]:
    """Add a Popup (shapes/popup.json): its own Container tree, title FieldMapping, Style. Pure.

    Content beyond the title goes inside the returned popup's own root container -- reachable via
    `page[popup_id]["Popup::Container"][0]` -- using add_container/add_widget exactly like any page
    body (popup.json's own note: "the exact same widget shapes as any page body").
    """
    new: Draft = copy.deepcopy(page)
    page_id = _page_id(new)

    shape = load_shape("popup")
    nodes, idmap = _instantiate(shape["template"], external={"Page_Sample01": page_id})
    pop_id = idmap["Popup_Sample01"]
    nodes[pop_id]["Name"] = name
    prop_id = idmap["Property_Sample01"]
    nodes[prop_id]["Value"] = name

    new.update(nodes)
    new[page_id].setdefault("Page::Popup", []).append(pop_id)
    return new, pop_id


EventMappingType = Literal["OpenPopup", "JSAction"]

# The two arms shapes/event_mapping.json actually captures (its own description: "Two real Type
# values observed"). Each maps to the (EventMapping, Property) Sample-id pair add_event_mapping
# mints for that arm -- the arm's own Container_SampleNN is deliberately NOT in this pair: it is
# never minted, only ever `external`-mapped onto the caller's real, already-existing container_id
# (the same pattern add_container/add_widget use for "Container001"), since an event hooks an
# EXISTING container, it never brings its own.
_EVENT_ARM_NODES: dict[str, tuple[str, str]] = {
    "JSAction": ("EventMapping_Sample01", "Property_Sample01"),
    "OpenPopup": ("EventMapping_Sample02", "Property_Sample02"),
}
_EVENT_ARM_CONTAINER_SAMPLE: dict[str, str] = {
    "JSAction": "Container_Sample01",
    "OpenPopup": "Container_Sample02",
}


def add_event_mapping(
    page: Draft,
    *,
    container_id: str,
    type: EventMappingType,
    popup_id: str | None = None,
    script: str | None = None,
    name: str = "on_click",
) -> tuple[Draft, str]:
    """Add an EventMapping (shapes/event_mapping.json) -- an on_click-style hook wiring an
    EXISTING Container to an action. Pure. This is the piece #22 found missing: without it, a
    built Popup (add_popup) or Component has no way to ever actually open/fire, no matter how
    correctly built (see this module's own docstring note on the gap this closes).

    Two arms, matching the shape's own two captured samples:
      - `type="OpenPopup"` needs `popup_id` (a real Popup id already on this page -- e.g. from
        add_popup; validated to actually be a Popup node, not just any id, same discipline as
        `_require_container`) -- the Property's Value is directly that Popup's id, no script
        involved.
      - `type="JSAction"` needs `script` (raw JS text, stored verbatim as the Property's Value --
        this module makes no claim about what the event editor will or won't accept inside it;
        only the wire shape is proven here, see event_mapping.json's own notes).
    Passing the OTHER arm's argument (popup_id on a JSAction, script on an OpenPopup), an unknown
    `type`, or omitting the arm's own required argument all raise ValueError before any node is
    written -- a shape's own placeholder popup id or demo script left in place is exactly THE
    RULE's "publishes clean, does nothing live" failure class.
    """
    if type not in _EVENT_ARM_NODES:
        raise ValueError(f"unknown event mapping type {type!r}; known types: {sorted(_EVENT_ARM_NODES)}")
    if type == "OpenPopup":
        if script is not None:
            raise ValueError("script is only valid for type='JSAction', not 'OpenPopup'")
        if not popup_id:
            raise ValueError("type='OpenPopup' requires popup_id")
    else:  # JSAction
        if popup_id is not None:
            raise ValueError("popup_id is only valid for type='OpenPopup', not 'JSAction'")
        if not script:
            raise ValueError("type='JSAction' requires script")

    new: Draft = copy.deepcopy(page)
    _require_container(new, container_id)
    if type == "OpenPopup":
        _require_popup(new, popup_id)  # type: ignore[arg-type]

    shape = load_shape("event_mapping")
    em_sample, prop_sample = _EVENT_ARM_NODES[type]
    subset = _keep_subset(shape["template"], (em_sample, prop_sample))
    external = {_EVENT_ARM_CONTAINER_SAMPLE[type]: container_id}
    if type == "OpenPopup":
        external["Popup_Sample01"] = popup_id  # type: ignore[assignment]
    nodes, idmap = _instantiate(subset, external=external)

    em_id = idmap[em_sample]
    prop_id = idmap[prop_sample]
    nodes[em_id]["Name"] = name
    if type == "JSAction":
        nodes[prop_id]["Value"] = script

    new.update(nodes)
    new[container_id].setdefault("Container::EventMapping", []).append(em_id)
    return new, em_id


def resolve_container_id(page: Draft, key: str) -> str:
    """Resolve a set_styles `rules` key to exactly one Container id. Two addressing modes, id wins:

      - `key` equal to an existing Container node id -> that id, directly. Ids are unique, so this
        is collision-proof: it is how a page whose Containers share a Name (real pages carry dozens
        all named 'Label'/'Icon') gets styled -- pass the id add_widget/add_container returns, no
        rename needed (#25).
      - otherwise `key` is a Name: exactly one Container with that Name -> its id; zero -> ValueError;
        more than one -> ValueError listing every match (pass the id, or a distinct name=).

    id wins on the (practically impossible) tie where a Name string equals some Container's id --
    Kissflow ids are system-minted `Container_<random>`, which no human-set Name collides with.
    Never a silent no-op. Matches Kind=="Container" only (a widget's host Container and its Component
    share a Name, so the Container covers the common "style the X widget" case)."""
    node = page.get(key)
    if isinstance(node, dict) and node.get("Kind") == "Container":
        return key
    matches = [nid for nid, n in page.items()
               if isinstance(n, dict) and n.get("Kind") == "Container" and n.get("Name") == key]
    if not matches:
        raise ValueError(f"no Container with id or name {key!r} on this page")
    if len(matches) > 1:
        raise ValueError(
            f"ambiguous Container name {key!r}: {len(matches)} matches {sorted(matches)} -- "
            "pass the container id (add_widget/add_container returns it), or a distinct name="
        )
    return matches[0]


def set_styles(page: Draft, *, rules: dict[str, dict[str, Any]]) -> Draft:
    """Style Containers by id or Name. `rules` maps a Container's id (collision-proof) or Name to
    {property: value} (see _apply_style_props for the accepted value forms). Pure. See
    resolve_container_id for the addressing rule: an id wins over a name, an ambiguous name raises
    rather than silently styling only the first match. Unknown key -> ValueError, never a silent
    no-op.
    """
    new: Draft = copy.deepcopy(page)
    for key, props in rules.items():
        cid = resolve_container_id(new, key)
        style_ids = new[cid].get("Container::Style") or []
        if not style_ids:
            raise ValueError(f"container {key!r} has no Style node to set")
        _apply_style_props(new[style_ids[0]], props)
    return new


def page_summary(page: Draft) -> dict[str, Any]:
    """Counts per Kind + a flat widget list (id/name/script), for read-back audits."""
    counts: dict[str, int] = {}
    widgets: list[dict[str, str]] = []
    for node in page.values():
        if not isinstance(node, dict):
            continue
        kind = node.get("Kind")
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "Component":
            script = (node.get("Script") or {}).get("web")
            if script:
                widgets.append({"id": node["Id"], "name": node.get("Name", ""), "script": script})
    return {"counts": counts, "widgets": widgets}
