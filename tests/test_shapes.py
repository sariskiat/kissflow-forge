"""Contract tests for shapes/*.json: sanitized, self-consistent Kissflow wire-shape knowledge.

Each shape file is knowledge-as-data (see shapes/*.json envelope: kind/description/source_capture/
template/notes). These tests hold the manifest of required shapes and check every file's structural
contract — they do NOT re-derive Kissflow's own builder rules; those live in each file's own
"notes" and in the shape's `template`.
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
SHAPES_DIR = ROOT / "shapes"

# Platform-prefix vocabulary a minted node id must start with. Exactly the list specified for this
# task, plus a small, explicitly documented set of additional real Kissflow Kind names that are not
# covered by any prefix above (Breadcrumbs/BreadcrumbItem/MasterDetail/Repeater) — each confirmed
# live in the widget-palette / page-graph captures (research/watch/capture_page_testallbutton_A00_
# full.json, research/watch/capture_page_qa_general_masterdetail.json, research/watch/capture_page_
# qa_general_repeater.json), so a minted id using one of them is a documented literal exception, not
# real-capture entropy.
CORE_ID_PREFIXES = (
    "Field", "Column", "Row", "Model", "Activity", "Event", "Permission", "Resource",
    "Expression", "Node", "Property", "Style", "Appearance", "Page", "Container", "Component",
    "Popup", "Tabs", "Tab", "Menu", "Navigation", "Variable", "VariableRef", "EventMapping",
    "Criteria", "Condition", "StartEvent", "ProcessDef", "Button", "User", "QueryDefinition",
)
EXTRA_ID_PREFIXES = ("Breadcrumbs", "BreadcrumbItem", "MasterDetail", "Repeater")

CORE_ID_RE = re.compile(r"^(" + "|".join(CORE_ID_PREFIXES) + r")[_A-Za-z0-9]*$")
EXTRA_ID_RE = re.compile(r"^(" + "|".join(EXTRA_ID_PREFIXES) + r")[_A-Za-z0-9]*$")

ENVELOPE_KEYS = ("kind", "description", "source_capture", "template", "notes")

# The full required-shape manifest for kissflow-forge P1 node A (process side + page side +
# widgets). "repeater" (page-side mechanism) and the widget-palette's 28th entry are the SAME file,
# widget_repeater.json — it counts once.
REQUIRED_SHAPES = {
    # -- process side --
    "field_text", "field_textarea", "field_number", "field_select", "field_boolean",
    "field_attachment", "field_sequence_number", "field_star_rating",
    "table", "row_grid", "section",
    "expression_branch", "expression_goto_condition", "goto_task", "event",
    "permission_field", "permission_section", "appearance_style_section", "process_skeleton",
    # -- page side --
    "page_virgin", "container", "page_style", "variable", "variable_ref", "event_mapping",
    "criteria_condition", "popup", "tabs", "menu_navigation",
    # -- widgets (28 scripts; slash -> underscore; repeater counts once) --
    "widget_general_label", "widget_general_icon", "widget_general_button",
    "widget_general_divider", "widget_general_progressbar", "widget_general_breadcrumbs",
    "widget_general_card", "widget_general_image", "widget_general_hyperlink",
    "widget_general_rich_text", "widget_general_iframe", "widget_general_tab",
    "widget_general_masterdetail", "widget_custom",
    "widget_view_form", "widget_view_table", "widget_view_gallery", "widget_view_sheet",
    "widget_view_kanban", "widget_view_matrix", "widget_view_list", "widget_view_timeline",
    "widget_report_chart", "widget_report_table", "widget_report_card", "widget_report_pivot",
    "widget_metrics", "widget_repeater",
}


def _shape_files() -> list[pathlib.Path]:
    return sorted(SHAPES_DIR.glob("*.json"))


def _load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _id_ok(node_id: str) -> bool:
    return bool(CORE_ID_RE.match(node_id) or EXTRA_ID_RE.match(node_id))


# ---------------------------------------------------------------------------------------------
# 0) sanity: the directory exists and is not empty (every other test would vacuously pass on an
#    empty dir otherwise)
# ---------------------------------------------------------------------------------------------

def test_shapes_dir_exists_and_nonempty():
    assert SHAPES_DIR.is_dir(), "shapes/ directory is missing"
    files = _shape_files()
    assert files, "no shapes/*.json files found"


# ---------------------------------------------------------------------------------------------
# 1) every shapes/*.json parses, envelope keys present, description non-empty, source_capture is
#    a bare filename
# ---------------------------------------------------------------------------------------------

def test_every_shape_parses_and_has_envelope():
    for p in _shape_files():
        data = _load(p)  # raises json.JSONDecodeError -> pytest failure with file context if bad
        assert isinstance(data, dict), f"{p.name}: top level must be a JSON object"

        missing = [k for k in ENVELOPE_KEYS if k not in data]
        assert not missing, f"{p.name}: missing envelope key(s) {missing}"

        assert isinstance(data["kind"], str) and data["kind"].strip(), \
            f"{p.name}: kind must be a non-empty string"

        assert isinstance(data["description"], str) and data["description"].strip(), \
            f"{p.name}: description must be non-empty"

        sc = data["source_capture"]
        assert isinstance(sc, str) and sc.strip(), f"{p.name}: source_capture must be a non-empty string"
        assert sc == pathlib.Path(sc).name, \
            f"{p.name}: source_capture must be a bare filename (no path separators), got {sc!r}"

        assert isinstance(data["template"], dict) and data["template"], \
            f"{p.name}: template must be a non-empty object"

        assert isinstance(data["notes"], list) and all(isinstance(n, str) for n in data["notes"]), \
            f"{p.name}: notes must be a list of strings"


# ---------------------------------------------------------------------------------------------
# 2) manifest coverage: all required shape names exist as files (by stem, e.g. shapes/table.json
#    covers "table")
# ---------------------------------------------------------------------------------------------

def test_manifest_coverage():
    have = {p.stem for p in _shape_files()}
    missing = REQUIRED_SHAPES - have
    assert not missing, f"required shapes missing from shapes/: {sorted(missing)}"


# ---------------------------------------------------------------------------------------------
# 3) every id key inside every template matches the platform-prefix vocabulary, and (5) every id
#    contains the "Sample" mint marker (no real-capture entropy). Checked together since both
#    walk the same set of template top-level keys.
#
# Design note: `template` is always a dict keyed by minted node id -> node dict (per the shape
# file format: "Multi-node shapes ... put ALL nodes in template keyed by minted id"). So "every id
# key inside every template" is exactly the set of `template.keys()`. Draft-envelope bookkeeping
# that is legitimately NOT an id (Root/CurrentVersion/PublishedBy/_meta_version, seen on real page
# drafts) is deliberately kept OUT of every template here and described in prose in "notes"
# instead — so no "documented literal key" escape hatch is needed at this level; the escape hatch
# that IS used is the EXTRA_ID_PREFIXES allowlist above, for real Kind names outside the core list.
# ---------------------------------------------------------------------------------------------

def test_every_template_key_is_a_minted_platform_id():
    bad_prefix = []
    bad_mint = []
    bad_node_shape = []
    for p in _shape_files():
        template = _load(p)["template"]
        for node_id, node in template.items():
            if not _id_ok(node_id):
                bad_prefix.append(f"{p.name}:{node_id!r}")
            if "Sample" not in node_id:
                bad_mint.append(f"{p.name}:{node_id!r}")
            if not isinstance(node, dict):
                bad_node_shape.append(f"{p.name}:{node_id!r} (not an object)")
    assert not bad_prefix, "template keys not matching the platform-prefix vocabulary:\n" + "\n".join(bad_prefix)
    assert not bad_mint, "minted ids must contain the mint marker 'Sample':\n" + "\n".join(bad_mint)
    assert not bad_node_shape, "template values must be node objects:\n" + "\n".join(bad_node_shape)


# ---------------------------------------------------------------------------------------------
# 4) every `::` list value inside a template resolves to an id also present in that same template
#    (self-consistent back-refs) — shapes must be self-contained, never reference a node minted in
#    a different shape file.
#
# Scope: this checks ONLY `::`-list keys (e.g. Row::Column, Container::Component,
# Container::Criteria). Scalar owner back-refs (e.g. a Property's "Field": "<id>", a Component's
# "Container": "<id>") are excluded BY DESIGN and are not verified to resolve within the same
# template — a dangling scalar ref would NOT be caught here. "Self-contained" below therefore
# means self-contained with respect to `::`-list back-refs only, not every reference in the file.
# ---------------------------------------------------------------------------------------------

def test_backrefs_resolve_within_same_template():
    problems = []
    for p in _shape_files():
        template = _load(p)["template"]
        for node_id, node in template.items():
            if not isinstance(node, dict):
                continue
            for key, val in node.items():
                if "::" not in key or not isinstance(val, list):
                    continue
                for target in val:
                    if isinstance(target, str) and target not in template:
                        problems.append(f"{p.name}: {node_id}.{key} -> missing {target!r}")
    assert not problems, "dangling back-refs (target not minted in the same template):\n" + "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# extra: every node object's own "Id" field, when present, must equal the dict key it is filed
# under. This is not one of the 5 numbered checks but catches copy-paste id drift for free at
# near-zero cost, which is exactly the kind of silent corruption this manifest is meant to prevent.
# ---------------------------------------------------------------------------------------------

def test_node_id_field_matches_its_template_key():
    mismatches = []
    for p in _shape_files():
        template = _load(p)["template"]
        for node_id, node in template.items():
            if isinstance(node, dict) and "Id" in node and node["Id"] != node_id:
                mismatches.append(f"{p.name}: key {node_id!r} has Id={node['Id']!r}")
    assert not mismatches, "node Id field disagrees with its template key:\n" + "\n".join(mismatches)


# ---------------------------------------------------------------------------------------------
# extra: no shape may name another shape's file in source_capture (source_capture must point at a
# CAPTURE, e.g. a research/*.json or CLAUDE.md, never at a sibling shapes/*.json) — guards against
# shapes citing each other as if that were grounding evidence.
# ---------------------------------------------------------------------------------------------

def test_source_capture_does_not_point_at_another_shape():
    shape_names = {p.name for p in _shape_files()}
    offenders = [p.name for p in _shape_files() if _load(p)["source_capture"] in shape_names]
    assert not offenders, f"source_capture citing a sibling shape file instead of a real capture: {offenders}"
