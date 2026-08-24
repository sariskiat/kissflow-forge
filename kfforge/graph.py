"""Pure, offline operations on Kissflow's normalized node-graph.

No network, no Kissflow calls. Graph shape documented in FINDINGS.md:
  Model -> Model::Field[] / Model::Row[]
  Row   -> Row::Column[]
  Column{Type:Section|Field} -> Column::Row[] (sections) | Column::Field[] (fields)
  Field{Kind:"Field", Type, Name, Column, Required}
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .pages import _instantiate, _mint
from .types import FieldSpec, FieldType, ParsedField, Visibility

Draft = dict[str, Any]


def _model_id(draft: Draft) -> str:
    root = draft.get("Root")
    if not isinstance(root, str) or root not in draft:
        raise ValueError("draft has no valid 'Root' model node")
    return root


def _new_id(kind: str, model_id: str, i: int, name: str) -> str:
    # Deterministic (no randomness) so runs are reproducible and testable.
    # Not a security hash — just derives a short stable node id, hence usedforsecurity=False.
    h = hashlib.sha1(f"{model_id}:{kind}:{i}:{name}".encode(), usedforsecurity=False).hexdigest()[:10]
    return f"{kind}_{h}"


def _ensure_appearance(draft: Draft, model_id: str) -> None:
    """Give the model the Appearance -> Style pair the BUILDER UI needs to render the flow.

    The API does not require this: a flow without it PUTs and publishes happily. But opening it in
    the builder shows only "There was an error / Reload", because the page dereferences
    Model::Appearance. EVERY human-built flow in the tenant has exactly one Appearance + one Style
    (checked on live dataform and process drafts). Mutates in place; no-op if present.
    """
    model = draft[model_id]
    if model.get("Model::Appearance"):
        return
    app_id = _new_id("Appearance", model_id, 0, "root")
    style_id = _new_id("Style", model_id, 0, "root")
    draft[app_id] = {"Id": app_id, "Kind": "Appearance", "Model": model_id,
                     "Appearance::Style": [style_id]}
    draft[style_id] = {"Id": style_id, "Kind": "Style", "Appearance": app_id}
    model["Model::Appearance"] = [app_id]


def _ensure_section(draft: Draft, model_id: str) -> str:
    """Return an existing Section column id, or SCAFFOLD Model->Row->Section if none.

    A freshly-created form's draft is bare (no Row/Section), so we must build the layout
    skeleton, not assume it. Learned from a real dev-form spike (see tests/fixtures/empty_form_draft.json).
    """
    for nid, node in draft.items():
        if isinstance(node, dict) and node.get("Kind") == "Column" and node.get("Type") == "Section":
            return nid
    model = draft[model_id]
    top_row = _new_id("Row", model_id, 0, "top")
    sec = _new_id("Column", model_id, 0, "section")
    draft[top_row] = {"Id": top_row, "Kind": "Row", "Model": model_id, "Row::Column": [sec]}
    draft[sec] = {
        "Id": sec, "Kind": "Column", "Type": "Section", "Name": model.get("Name", "Section"),
        "Start": 0, "End": 6, "Row": top_row, "Column::Row": [],
    }
    model.setdefault("Model::Row", []).append(top_row)
    return sec


ROW_UNITS = 6      # a Row is a 6-unit grid
FIELD_SPAN = 2     # a field column occupies 2 units -> 3 per row, tiled (0,2) (2,4) (4,6)


def _alloc_slot(draft: Draft, model_id: str, seq: int) -> tuple[str, int, int]:
    """Reserve a grid slot for one new field-column: (row_id, Start, End).

    A Row holds at most ROW_UNITS/FIELD_SPAN columns; past that a NEW Row is opened. Getting this
    wrong is not cosmetic: stacking every column at Start=0 in a single Row overflows the grid and
    the builder then fails to render the whole flow ("There was an error"). Observed live on
    a live process when 17 columns landed in one Row — reverted, then fixed here.
    """
    section = draft[_ensure_section(draft, model_id)]
    rows = section.setdefault("Column::Row", [])

    per_row = ROW_UNITS // FIELD_SPAN
    if rows and len(draft[rows[-1]].get("Row::Column") or []) < per_row:
        row_id = rows[-1]
    else:
        row_id = _new_id("Row", model_id, 1000 + seq, "auto")
        draft[row_id] = {"Id": row_id, "Kind": "Row", "Column": section["Id"], "Row::Column": []}
        rows.append(row_id)

    start = len(draft[row_id].get("Row::Column") or []) * FIELD_SPAN
    return row_id, start, start + FIELD_SPAN


def _tile_into_rows(columns: list[str]) -> list[list[tuple[str, int, int]]]:
    """Tile column ids across the 6-unit grid: one inner list per Row, `(column id, Start, End)`.

    THE auto-tiler. At most ROW_UNITS/FIELD_SPAN columns per Row, at (0,2) (2,4) (4,6) — past
    that a new Row opens, exactly as `_alloc_slot` allocates one slot at a time. Every path that
    places columns the caller did not position itself goes through here (`regroup_into_sections`,
    `apply_exact_layout`'s leftover row), so "a Row never overflows the grid" is ONE rule in one
    place rather than one copy per call site — a second, hand-rolled tiler is how
    `apply_exact_layout` came to emit (6,8) and (8,6) columns off the end of the grid. Pure.
    """
    per_row = ROW_UNITS // FIELD_SPAN
    rows: list[list[tuple[str, int, int]]] = []
    for i, cid in enumerate(columns):
        slot = i % per_row
        if slot == 0:
            rows.append([])
        rows[-1].append((cid, slot * FIELD_SPAN, (slot + 1) * FIELD_SPAN))
    return rows


def validate_layout_spans(layout: dict[str, list[list[tuple[str, int, int]]]]) -> None:
    """Reject any caller-stated layout that cannot exist on the 6-unit row grid. Raises ValueError.

    PURE — it reads the spec and nothing else, no draft required. That is what lets the live
    orchestration (`client.apply_layout`) run it BEFORE the GET, so a caller with an impossible
    span is refused without paying for a round trip; `apply_exact_layout` runs it again before it
    copies or touches anything, so a bad spec also leaves the draft entirely unmutated.

    Two refusals, both render-breaking rather than cosmetic (CLAUDE.md > Node-graph invariants —
    overflow one Row and the BUILDER fails to render the whole flow, not just that row):

    * a span off the grid (`0 <= Start < End <= ROW_UNITS`);
    * two spans sharing a unit of the same row.

    ⚠️ A COUNT bound ("at most 3 columns per row") deliberately does NOT live here, and briefly
    did (D8b, reverted 2026-08-19). The repo owns a capture AGAINST it:
    shapes/process_template_identity_shell.json, de-identified off a REAL PUBLISHED production
    template, carries a Row with FOUR field columns at (0,2) (2,4) (4,5) (5,6) — in-grid,
    disjoint, rendering. `verify.doctor` cited that same capture to refuse a count bound on drafts
    it did not build, so asserting one HERE was the same repo contradicting itself, and refusing a
    geometry the platform demonstrably renders is inventing a bound with no capture behind it
    (#10). "At most 3" remains the consequence of FIELD_SPAN=2 in the auto-tiler
    (`_tile_into_rows`), which is a default layout, never a limit on what a caller may state.

    A field named TWICE anywhere in the spec is refused too (D8a): a field owns exactly ONE
    Column, so placing it twice puts that Column in two Rows' `Row::Column` while its own `Row`
    back-ref names only the last — a corruption the doctor's geometry rule cannot see from the
    column side, since it groups by that very back-ref.
    """
    seen: dict[str, str] = {}                     # field name -> "<section> row <n>" it was placed
    for title, rows_spec in layout.items():
        for ri, row in enumerate(rows_spec):
            placed: list[tuple[str, int, int]] = []
            for fname, start, end in row:
                where = f"{title!r} row {ri}"
                if fname in seen:
                    raise ValueError(
                        f"layout places {fname!r} twice — at {seen[fname]} and again at {where}: a "
                        f"field owns exactly ONE Column, so the second placement leaves that "
                        f"Column in two Rows while its own Row back-ref names only one")
                seen[fname] = where
                if not (0 <= start < end <= ROW_UNITS):
                    raise ValueError(
                        f"layout places {fname!r} @ {title!r} row {ri} at (Start={start}, "
                        f"End={end}): a Row is a {ROW_UNITS}-unit grid, so every span must satisfy "
                        f"0 <= Start < End <= {ROW_UNITS}")
                for ofname, ostart, oend in placed:
                    if start < oend and ostart < end:
                        raise ValueError(
                            f"layout overlaps {fname!r} at ({start}, {end}) with {ofname!r} at "
                            f"({ostart}, {oend}) @ {title!r} row {ri}: spans sharing one Row must "
                            f"be disjoint on the {ROW_UNITS}-unit grid")
                placed.append((fname, start, end))


def ensure_process_def(
    draft: Draft,
    steps: tuple[str, ...] = ("Submit",),
    assignee: tuple[str, str] | None = None,
) -> Draft:
    """Give a bare PROCESS draft the workflow skeleton it needs to be writable at all.

    A freshly created process draft is only {Root, Model}. PUTting it back — even UNMODIFIED —
    returns HTTP 500 MetadataError, because the process metadata compiler requires a ProcessDef.
    (Two-arm control experiment, 2026-08-03; see FINDINGS.md.) So creating a process from zero
    means synthesizing: ProcessDef -> [StartEvent, UserTask per step, EndEvent].

    Shape copied from a live captured ProcessDef. Note there are NO transition nodes:
    `WorkflowType: "Sequence"` means the order IS the `ProcessDef::Activity` array order.
    No-op when the draft already has a RootProcessDef. Pure: returns a new draft.

    `assignee` is (app_role_id, display_name) and attaches a Resource to every UserTask — WITHOUT it
    the steps have nobody to act on them, which is what the builder flags on a freshly created
    process. Role ids are not listable (`/app_role/.../external/list` returns []); harvest them from
    an existing flow via `GET /flow/2/{acct}/{type}/{id}/member`.
    """
    if not steps:
        raise ValueError("a process needs at least one step")

    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    model = new[model_id]
    if model.get("RootProcessDef"):
        return new

    pd = _new_id("ProcessDef", model_id, 0, "root")
    activity_ids: list[str] = []

    def _activity(i: int, node_type: str, name: str) -> str:
        aid = _new_id("Activity", model_id, i, name)
        new[aid] = {"Id": aid, "Kind": "Activity", "NodeType": node_type,
                    "Name": name, "ProcessDef": pd}
        activity_ids.append(aid)
        return aid

    _activity(0, "StartEvent", "Start")
    for i, step in enumerate(steps, start=1):
        aid = _activity(i, "UserTask", step)
        if assignee is not None:
            role_id, display = assignee
            rid = _new_id("Resource", model_id, i, step)
            new[rid] = {"Id": rid, "Kind": "Resource", "ValueType": "AppRole",
                        "Value": role_id, "DisplayValue": display, "Activity": aid}
            new[aid]["Activity::Resource"] = [rid]
    _activity(len(steps) + 1, "EndEvent", "Completed")

    new[pd] = {"Id": pd, "Kind": "ProcessDef", "WorkflowType": "Sequence",
               "Model": model_id, "ProcessDef::Activity": activity_ids}
    model["Model::ProcessDef"] = [pd]
    model["RootProcessDef"] = pd

    _ensure_appearance(new, model_id)
    if not model.get("Button::Row"):  # every human-built process carries one; the UI expects it
        btn = _new_id("Row", model_id, 99, "button")
        new[btn] = {"Id": btn, "Kind": "Row", "Button": model_id}
        model["Button::Row"] = [btn]
    return new


_SHAPES_DIR = pathlib.Path(__file__).parent.parent / "shapes"
_DEFAULT_TEMPLATE_PATH = _SHAPES_DIR / "process_template_identity_shell.json"
_TEMPLATE_ROOT_KEY = "Model_Sample01"
_TEMPLATE_ROOT_LIST_KEYS = (
    "Model::Row", "Model::Field", "Model::ProcessDef", "Model::Component", "Model::Appearance",
    "Button::Row",
)


def _resolve_template_path(template_path: str | None) -> pathlib.Path:
    """template_path arg > KF_PROCESS_TEMPLATE env var > the shipped default shape.

    Kept as a plain file path (not a shapes/<name> lookup) so a tenant-specific override can live
    anywhere outside this repo — issue #59's own point is that a real tenant's template stays out
    of the engine, only the de-identified default ships here.
    """
    if template_path:
        return pathlib.Path(template_path)
    env = os.environ.get("KF_PROCESS_TEMPLATE")
    if env:
        return pathlib.Path(env)
    return _DEFAULT_TEMPLATE_PATH


def clone_template_shell(draft: Draft, template_path: str | None = None) -> Draft:
    """Graft the process-template identity shell onto a freshly created process draft, in place
    of the bare ensure_process_def scaffold — issue #59's "every process starts from a
    structure-clone" decision.

    Loads shapes/process_template_identity_shell.json (or KF_PROCESS_TEMPLATE / `template_path`),
    a de-identified capture of a real production template: the identity/initiate field block,
    section/row/column layout, the mandatory Model::Appearance/Style chain, a "Manager Approve"
    UserTask, and Button::Row. Every node is freshly re-minted (kfforge.pages._instantiate — the
    SAME clone-with-fresh-ids machinery nav.py already reuses from pages.py) so two processes
    built from_template=True never collide. Callers add their own fields/workflow on top.

    Pure: returns a NEW draft, never mutates `draft`. No-op (returns a deep copy, unchanged) if the
    draft already has a RootProcessDef — same idempotency contract as ensure_process_def.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    model = new[model_id]
    if model.get("RootProcessDef"):
        return new

    path = _resolve_template_path(template_path)
    if not path.is_file():
        raise ValueError(f"process template not found: {path} "
                         f"(from template_path arg, KF_PROCESS_TEMPLATE, or the shipped default)")
    shape = json.loads(path.read_text(encoding="utf-8"))
    template = shape.get("template")
    if not isinstance(template, dict) or not template:
        raise ValueError(f"{path}: not a valid shapes/*.json shape (no non-empty 'template')")
    root_node = template.get(_TEMPLATE_ROOT_KEY)
    if not isinstance(root_node, dict) or root_node.get("Kind") != "Model":
        raise ValueError(f"{path}: template has no root Model node keyed {_TEMPLATE_ROOT_KEY!r}")

    subset = {k: v for k, v in template.items() if k != _TEMPLATE_ROOT_KEY}
    external = {_TEMPLATE_ROOT_KEY: model_id}
    cloned, idmap = _instantiate(subset, external=external)
    new.update(cloned)

    def _remap(v: str) -> str:
        return idmap.get(v, external.get(v, v))

    for key in _TEMPLATE_ROOT_LIST_KEYS:
        if key in root_node:
            model[key] = [_remap(v) for v in root_node[key]]
    if "RootProcessDef" in root_node:
        model["RootProcessDef"] = _remap(root_node["RootProcessDef"])
    return new


_TEMPLATE_FULL_PATH = _SHAPES_DIR / "process_template_full.json"
_TEMPLATE_FULL_ROOT_KEY = "Model_Sample01"
# Same family as _TEMPLATE_ROOT_LIST_KEYS, minus "Model::Appearance" -- this fuller capture has
# no root Appearance/Style chain at all (synthesized below), see shape notes[4].
_TEMPLATE_FULL_ROOT_LIST_KEYS = ("Model::Row", "Model::Field", "Model::ProcessDef", "Model::Component",
                                "Button::Row")
_SAMPLE_TOKEN_RE = re.compile(r"[A-Za-z]+_Sample\d+")


def _rewrite_sample_tokens(value: Any, lookup: dict[str, str]) -> Any:
    """Every `<Kind>_SampleNN` SUBSTRING anywhere under `value` (not just a leaf that IS one, whole
    string) rewritten via `lookup`, recursively over dicts/lists; dict KEYS untouched, only values.

    `_instantiate`'s own remap only ever replaces a leaf string that EXACTLY equals a mapped id --
    this template's own ExpressionStr formulas ('if(_Field_Sample12, ...)') and one System-field
    Node's underscore-prefixed `Field` value ('_Field_Sample12') embed an id as a SUBSTRING of a
    larger string, which that exact-match remap silently leaves alone (CLAUDE.md > Expressions).
    A token not present in `lookup` (ordinary prose that merely LOOKS like one) is left unchanged.
    """
    if isinstance(value, str):
        return _SAMPLE_TOKEN_RE.sub(lambda m: lookup.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [_rewrite_sample_tokens(v, lookup) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite_sample_tokens(v, lookup) for k, v in value.items()}
    return value


def transplant_template(
    draft: Draft,
    *,
    app_role: tuple[str, str],
    template_path: str | pathlib.Path | None = None,
    force_ids: dict[str, str] | None = None,
) -> Draft:
    """Graft the FULL deidentified production-template capture (shapes/process_template_full.json,
    ADR-0006, spec #10 / ticket #12) onto a bare dev draft. Unlike `clone_template_shell` (the
    small identity-shell scaffold), this carries the WHOLE captured graph -- every field, the
    branch/goto Condition/Criteria/Expression/Node subtrees, and the source capture's own quirks
    (a duplicate suspended "Manager Approve" step, an orphaned SendBackToInitiator dangling out of
    ProcessDef::Activity) -- verbatim modulo a fresh id mapping. Then repairs the thing the capture
    deliberately ships broken (shape note[4]): the mandatory root Model::Appearance -> Appearance ->
    Style chain (missing entirely, or the whole form fails to render -- CLAUDE.md > Node-graph
    invariants), and the workflow's assignee, re-pointed from the source tenant's Resource at
    `app_role` (the dev AppRole) on every UserTask step. Notes[7]/[8] (external tenant refs) pass
    through untouched -- a later seam, not this op's job. Pure: deep-copies `draft`, returns a new
    Draft; raises ValueError if `draft` already has a RootProcessDef (this op needs a bare draft to
    graft onto).

    `force_ids` is a `{old_id: new_id}` map covering the template's node ids (an id absent from it
    is minted fresh, kfforge.pages._mint). Passing the SAME map twice reproduces an IDENTICAL output
    graph (byte for byte, including the synthesized Appearance/Style ids) ONLY when the map is
    COMPLETE (covers every template id) -- a partial map still mints the uncovered ids fresh each
    call. Omitting `force_ids` entirely mints every id at random, so two calls never collide.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    model = new[model_id]
    if model.get("RootProcessDef"):
        raise ValueError("transplant_template needs a bare draft (no RootProcessDef yet)")

    path = pathlib.Path(template_path) if template_path else _TEMPLATE_FULL_PATH
    if not path.is_file():
        raise ValueError(f"process template not found: {path}")
    shape = json.loads(path.read_text(encoding="utf-8"))
    template = shape.get("template")
    if not isinstance(template, dict) or not template:
        raise ValueError(f"{path}: not a valid shapes/*.json shape (no non-empty 'template')")
    root_node = template.get(_TEMPLATE_FULL_ROOT_KEY)
    if not isinstance(root_node, dict) or root_node.get("Kind") != "Model":
        raise ValueError(f"{path}: template has no root Model node keyed {_TEMPLATE_FULL_ROOT_KEY!r}")

    subset = {k: v for k, v in template.items() if k != _TEMPLATE_FULL_ROOT_KEY}
    external = {_TEMPLATE_FULL_ROOT_KEY: model_id}
    force_ids = force_ids or {}
    # Mirror _instantiate's OWN idmap formula up front (force_ids override, else mint), so the
    # substring pre-rewrite below and _instantiate's later exact-match remap land on the identical
    # ids -- passing this same dict back in as `force_ids=` makes _instantiate reuse it verbatim
    # rather than minting a second, divergent, set.
    idmap = {old: force_ids.get(old) or _mint(old.split("_")[0]) for old in subset}
    # An exact-leaf reference to the template's root Model (e.g. an AST Node's "FieldModel"
    # self-reference) is NOT rewritten here -- it falls through to _instantiate's `external` map and
    # lands on the real target model, like every other node's Model backref.
    rewritten = {k: _rewrite_sample_tokens(v, idmap) for k, v in subset.items()}
    cloned, _ = _instantiate(rewritten, external=external, force_ids=idmap)
    new.update(cloned)

    def _remap(v: str) -> str:
        return idmap.get(v, external.get(v, v))

    for key in _TEMPLATE_FULL_ROOT_LIST_KEYS:
        if key in root_node:
            model[key] = [_remap(v) for v in root_node[key]]
    if "RootProcessDef" in root_node:
        model["RootProcessDef"] = _remap(root_node["RootProcessDef"])

    # The capture's own audit node (Kind:"User") carries only {Kind, Name, _id} -- _instantiate
    # force-sets "Id" on every node it clones; strip it back off wherever the template original
    # never had one (its "_id" VALUE is already remapped, exact-match, by _instantiate itself).
    for old_id, old_node in subset.items():
        if "Id" not in old_node:
            new[idmap[old_id]].pop("Id", None)

    # Mandatory root style chain (CLAUDE.md > Node-graph invariants): the capture ships without it
    # on purpose (shape notes[4]) -- synthesize or the form will not render. Deterministic under
    # force_ids (so the SAME mapping source reproduces an identical graph); random otherwise (two
    # force_ids-less transplants must never mint colliding ids).
    if not model.get("Model::Appearance"):
        if force_ids:
            basis = "|".join(f"{k}={v}" for k, v in sorted(idmap.items()))
            app_id = "Appearance_" + hashlib.sha1(
                f"{basis}:Appearance".encode(), usedforsecurity=False).hexdigest()[:10]
            style_id = "Style_" + hashlib.sha1(
                f"{basis}:Style".encode(), usedforsecurity=False).hexdigest()[:10]
        else:
            app_id, style_id = _mint("Appearance"), _mint("Style")
        new[app_id] = {"Id": app_id, "Kind": "Appearance", "Model": model_id, "Appearance::Style": [style_id]}
        new[style_id] = {"Id": style_id, "Kind": "Style", "Appearance": app_id}
        model["Model::Appearance"] = [app_id]

    # Re-point every Resource at the dev AppRole: the capture's own Resource is a dynamic assignee
    # (ValueType "Field" + a Field scalar) whose source does not exist on this (dev-only) tenant.
    # Flattening to an AppRole assignee keeps exactly the captured AppRole-Resource shape
    # (shapes/app_role_grant.json): no stale Field key, no Field::Resource back-link left behind.
    role_id, role_name = app_role
    repointed = 0
    for node in new.values():
        if not isinstance(node, dict) or node.get("Kind") != "Resource":
            continue
        node["ValueType"] = "AppRole"
        node["Value"] = role_id
        node["DisplayValue"] = role_name
        stale_field = node.pop("Field", None)
        if stale_field and isinstance(new.get(stale_field), dict):
            kept = [r for r in new[stale_field].get("Field::Resource") or [] if r != node["Id"]]
            if kept:
                new[stale_field]["Field::Resource"] = kept
            else:
                new[stale_field].pop("Field::Resource", None)
        repointed += 1
    if repointed == 0:
        raise ValueError("transplant found no Resource node to re-point at the dev AppRole")

    return new


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(UTC).microsecond // 1000:03d}Z"


# Per-type keys the builder writes on every field it creates. Captured by diffing an API-built
# process against a UI-built COPY of the same process (2026-08-03).
#
# CORRECTED BELIEF (2026-08-08, vs the parity oracle): Textarea `AllowFormatting` and Attachment
# `CaptureOnly` were originally listed here as `False`, on the claim that omitting them left fields
# the builder would not render. A UI-built oracle process carries NEITHER key on its Textareas or
# its Attachment and renders fine — so neither is required for rendering, and a fresh builder-made
# field simply omits them. Setting them to `False` is an EXTRA key the oracle does not have, so it
# is now opt-in (FieldSpec.options, e.g. `AllowFormatting=true`), not a default. Same one-sample-
# not-universal trap as the styling/section-lever beliefs. Number's `DefaultValue`/`Decimalpoint`
# the oracle DOES carry, so they stay.
_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    "Number": {"DefaultValue": "0", "Decimalpoint": "2"},
}


def regroup_into_sections(draft: Draft, groups: list[tuple[str, list[str]]]) -> Draft:
    """Rebuild the form layout so each named section holds the given fields, in order.

    Reuses the EXISTING Field and Column nodes (ids, types and per-step Permission refs survive);
    only the Row/Section scaffolding above them is rebuilt. Fields not named in `groups` keep their
    order and land in a trailing section so nothing is ever dropped from the layout.

    Columns re-tile the 6-unit grid at FIELD_SPAN each, so no row overflows. Pure.

    A template-cloned form nests fields one layer deeper than an engine-built one (Section -> Row
    -> Grid Column -> Row -> Field Column, vs. Section -> Row -> Field Column). Every layout
    Column type OTHER than Field/Model/Button is scaffolding of this kind — Grid today, whatever
    the builder invents tomorrow — and gets dropped along with the old Rows; a table host
    (Type:"Model") and its own root Row/nested schema Row are never touched, since a table lives
    outside every Section (CLAUDE.md > Tables). `_sweep_dangling` runs at the end so any reference
    the rebuild left pointing at a deleted node — the old bug: an un-deleted Grid column still
    pointing at its now-gone child Rows — is stripped rather than surviving into a corrupt draft.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    model = new[model_id]

    col_of: dict[str, str] = {}
    for node in new.values():
        if isinstance(node, dict) and node.get("Kind") == "Field":
            col = node.get("Column")
            if not isinstance(col, str):  # an unwired field would KeyError far away from the cause
                raise ValueError(f"field {node.get('Name')!r} has no Column back-reference")
            col_of[node.get("Name", "")] = col

    named = {n for _, names in groups for n in names}
    leftover = [n for n in col_of if n not in named]
    plan = [(t, [n for n in names if n in col_of]) for t, names in groups]
    if leftover:
        plan.append(("Other", leftover))

    # drop the old scaffolding; Field and Column nodes are deliberately preserved, and so is
    # anything belonging to a child table (its host Row, its own nested schema Row) — a table
    # sits in its own root-level Row, outside every Section, and must survive a field regroup.
    KEEP_COLUMN_TYPES = {"Field", "Model", "Button"}
    table_ids = _table_model_ids(new)
    protected_rows = {v.get("Row") for v in new.values()
                      if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Model"}
    protected_rows |= {k for k, v in new.items()
                       if isinstance(v, dict) and v.get("Kind") == "Row"
                       and (v.get("Model") in table_ids or v.get("Button"))}

    # Remember, BEFORE anything is deleted, which section title each protected root row (a table
    # host) sat immediately after in the OLD Model::Row order — #10's "banner Section and its
    # table host must be ADJACENT" invariant must survive a regroup, not just the original build.
    # `None` means "before the first section" (or no section preceded it at all).
    pending_after: dict[str | None, list[str]] = {}
    _last_title: str | None = None
    for _rid in model.get("Model::Row") or []:
        if _rid in protected_rows:
            pending_after.setdefault(_last_title, []).append(_rid)
            continue
        _row = new.get(_rid) or {}
        _cols = _row.get("Row::Column") or []
        _sec = new.get(_cols[0]) if _cols else None
        if isinstance(_sec, dict) and _sec.get("Type") == "Section":
            _last_title = _sec.get("Name")

    for nid in [k for k, v in new.items()
                if isinstance(v, dict) and (
                    (v.get("Kind") == "Row" and k not in protected_rows)
                    or (v.get("Kind") == "Column" and v.get("Type") not in KEEP_COLUMN_TYPES)
                )]:
        del new[nid]

    top_rows: list[str] = []
    per_row = ROW_UNITS // FIELD_SPAN
    for s_i, (title, names) in enumerate(plan):
        # an empty `names` is a BANNER section (header + description, no fields). Create it
        # with Column::Row: [] rather than skipping — the caller asked for the section to exist,
        # and its position in `plan` preserves the requested display order. Learned from the
        # golden FDE-Log banner: an empty Section sibling to a table host, not wrapping it.
        top = _new_id("Row", model_id, 2000 + s_i, title)
        sec = _new_id("Column", model_id, 2000 + s_i, title)
        new[top] = {"Id": top, "Kind": "Row", "Model": model_id, "Row::Column": [sec]}
        new[sec] = {"Id": sec, "Kind": "Column", "Type": "Section", "Name": title,
                    "Start": 0, "End": ROW_UNITS, "Row": top, "Column::Row": []}
        top_rows.append(top)

        for ri, tiled in enumerate(_tile_into_rows([col_of[fname] for fname in names])):
            row = _new_id("Row", model_id, 3000 + s_i * 100 + ri * per_row, title)
            new[row] = {"Id": row, "Kind": "Row", "Column": sec, "Row::Column": []}
            new[sec]["Column::Row"].append(row)
            for col_id, start, end in tiled:
                new[col_id].update({"Row": row, "Start": start, "End": end})
                new[row]["Row::Column"].append(col_id)

    # splice the protected rows back in, immediately after the (new) row of whichever title
    # anchored them before; a title that no longer exists in `plan` falls back to the end rather
    # than being dropped.
    final_rows: list[str] = list(pending_after.pop(None, []))
    for title, top in zip((t for t, _ in plan), top_rows):
        final_rows.append(top)
        final_rows.extend(pending_after.pop(title, []))
    for _leftover in pending_after.values():
        final_rows.extend(_leftover)

    model["Model::Row"] = final_rows
    _sweep_dangling(new)
    return new


def apply_exact_layout(
    draft: Draft,
    layout: dict[str, list[list[tuple[str, int, int]]]],
    descriptions: dict[str, str] | None = None,
) -> Draft:
    """Rebuild each named section's rows to an EXACT per-field grid layout.

    `layout` is `{section_name: [[(field_name, Start, End), ...], ...]}` — one inner list per Row,
    in top-to-bottom order, each tuple placing one field column at explicit grid coordinates on
    the 6-unit row. This is the "I know where every field goes" API: the caller states the layout
    and the engine places columns at those coordinates instead of auto-tiling by type.

    `descriptions` optionally sets each section's `Description` (plain string OR a serialized
    rich-text doc — the builder writes the latter for formatted text; both coexist live). It is
    applied only to sections named in `layout`, alongside the row rebuild, in the same write.

    Only Row nodes (and the column Start/End/Row back-refs) are rebuilt; Field and Column ids are
    preserved, so `Column::Permission`, `Field::Event` and `Field::Node` survive untouched. A field
    named in the layout but absent from the draft, or a section that does not exist, raises — fail
    loud rather than silently drop a field off the form. Fields NOT named in their section's layout
    are left in place after the rebuilt rows (trailing rows), so nothing is ever dropped.

    Every caller-stated span is checked against the 6-unit grid FIRST (`validate_layout_spans`,
    which the live orchestration also runs ahead of its GET), before anything is copied: an
    out-of-grid, overlapping, over-crowded or duplicated placement is refused with the draft
    entirely unmutated, rather than written and then discovered as a whole flow that will not
    render. The leftover columns are tiled by the SAME `_tile_into_rows` the auto-layout path
    uses, in the section's pre-existing row/column order — the order the user already sees on the
    form, and (unlike the set it used to be read from) stable across processes.

    Pure: returns a new draft.
    """
    validate_layout_spans(layout)

    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)

    # field name -> its column id (root-model fields only; table children tile their own grid)
    col_of: dict[str, str] = {}
    for node in new.values():
        if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Model") == model_id:
            col = node.get("Column")
            if isinstance(col, str):
                col_of[node.get("Name", "")] = col

    sections = {v.get("Name", ""): sid for sid, v in new.items()
                if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Section"}

    for title, rows_spec in layout.items():
        if title not in sections:
            raise ValueError(f"layout names a section that does not exist: {title!r}")
        sid = sections[title]
        sec = new[sid]

        # which columns already live in this section? keep their ids so we can spot leftovers.
        # A LIST in the section's existing row/column order, not a set: leftovers are re-emitted
        # in this order, and Python randomizes string hashing per process, so reading them back
        # out of a set gave a different field order on every run of the same input.
        before_cols: list[str] = []
        seen_cols: set[str] = set()
        for rid in sec.get("Column::Row") or []:
            for cid in (new.get(rid) or {}).get("Row::Column") or []:
                if cid not in seen_cols:
                    seen_cols.add(cid)
                    before_cols.append(cid)
            new.pop(rid, None)  # drop old rows; columns are preserved

        placed: set[str] = set()
        new_rows: list[str] = []
        for ri, row in enumerate(rows_spec):
            if not row:
                continue
            rid = _new_id("Row", sid, 5000 + ri, title)
            new[rid] = {"Id": rid, "Kind": "Row", "Column": sid, "Row::Column": []}
            for fname, start, end in row:
                if fname not in col_of:
                    raise ValueError(f"layout places a field not in the draft: {fname!r} @ {title!r}")
                cid = col_of[fname]
                # a field pulled in from a section NOT named in this layout still sits in that
                # section's row — detach it there, or the column ends up listed in two rows
                # (the corruption doctor rule 8b flags). Same-section rows are already popped.
                old_rid = new[cid].get("Row")
                old_row = new.get(old_rid) if isinstance(old_rid, str) and old_rid != rid else None
                if isinstance(old_row, dict):
                    old_cols = old_row.get("Row::Column") or []
                    if cid in old_cols:
                        old_cols.remove(cid)
                    if not old_cols:
                        old_sec = new.get(old_row.get("Column") or "")
                        if isinstance(old_sec, dict) and old_rid in (old_sec.get("Column::Row") or []):
                            old_sec["Column::Row"].remove(old_rid)
                        new.pop(old_rid, None)
                new[cid].update({"Row": rid, "Start": start, "End": end})
                new[rid]["Row::Column"].append(cid)
                placed.add(cid)
            new_rows.append(rid)

        # any column that was in this section but not named in the layout goes in TRAILING ROWS,
        # so a partial layout spec (the documented, encouraged usage) never silently drops a field
        # off the form. Tiled by the shared `_tile_into_rows`, so however many leftovers there
        # are they stay on the grid: the old single-row packer just kept adding FIELD_SPAN with no
        # cap, and a 5-field leftover ran off the end at (6,8) and then (8,6).
        leftover = [c for c in before_cols if c not in placed]
        for li, tiled in enumerate(_tile_into_rows(leftover)):
            rid = _new_id("Row", sid, 5900 + li, title)
            new[rid] = {"Id": rid, "Kind": "Row", "Column": sid, "Row::Column": []}
            for cid, start, end in tiled:
                new[cid].update({"Row": rid, "Start": start, "End": end})
                new[rid]["Row::Column"].append(cid)
            new_rows.append(rid)

        sec["Column::Row"] = new_rows

        if descriptions and title in descriptions:
            sec["Description"] = descriptions[title]

    return new


# Units on the 6-unit row grid, by field type. A Textarea sitting in a 2-unit column is the single
# biggest reason an API-built form looks cramped beside a hand-built one — the UI-built
# MCP_Test_Process_Copy uses (0,6) full, (0,3)/(3,6) half AND thirds, while everything we generated
# used thirds for all 61 fields.
FIELD_WIDTH: dict[str, int] = {
    "Textarea": ROW_UNITS,     # canvas boxes, notes, summaries — need the room
    "Attachment": ROW_UNITS,
    "Text": 3, "Select": 3, "Date": 3, "Email": 3, "User": 3,
    "Number": 2, "Boolean": 2,  # short values stay short
}
DEFAULT_WIDTH = 2


def _resolve_widths(widths: dict[str, int] | None) -> dict[str, int]:
    if not widths:
        return dict(FIELD_WIDTH)
    return {**FIELD_WIDTH, **widths}


def _field_by_column(draft: Draft) -> dict[str, dict[str, Any]]:
    return {v["Column"]: v for v in _kind(draft, "Field").values() if v.get("Column")}


def _section_columns(draft: Draft) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in _kind(draft, "Column").items() if v.get("Type") == "Section"}


def _ordered_section_columns(draft: Draft, sec: dict[str, Any]) -> list[str]:
    cols: list[str] = []
    row_ids = sec.get("Column::Row")
    if not isinstance(row_ids, list):
        return cols
    for rid in row_ids:
        row_node = draft.get(rid)
        if isinstance(row_node, dict):
            cols.extend(row_node.get("Row::Column", []))
    return cols


def _column_width(col: str, field_of_col: dict[str, dict[str, Any]], width_of: dict[str, int]) -> int:
    ftype = str(field_of_col.get(col, {}).get("Type", ""))
    return min(width_of.get(ftype, DEFAULT_WIDTH), ROW_UNITS)


def _pack_repack_rows(
    ordered: list[str],
    field_of_col: dict[str, dict[str, Any]],
    width_of: dict[str, int],
) -> list[list[tuple[str, int]]]:
    rows: list[list[tuple[str, int]]] = []
    used = ROW_UNITS
    for col in ordered:
        w = _column_width(col, field_of_col, width_of)
        if used + w > ROW_UNITS:
            rows.append([])
            used = 0
        rows[-1].append((col, w))
        used += w
    return rows


def _write_repacked_row(
    draft: Draft,
    sid: str,
    sec_name: str,
    row_index: int,
    row: list[tuple[str, int]],
) -> str:
    rid = _new_id("Row", sid, 4000 + row_index, sec_name)
    draft[rid] = {"Id": rid, "Kind": "Row", "Column": sid, "Row::Column": [c for c, _ in row]}
    start = 0
    last_idx = len(row) - 1
    for j, (col, w) in enumerate(row):
        # stretch the last column to the row edge, so a short tail never leaves a ragged
        # gap (a 2 + 3 row would otherwise end at 5 with one dead unit)
        end = ROW_UNITS if j == last_idx else start + w
        draft[col].update({"Row": rid, "Start": start, "End": end})
        start = end
    return rid


def _apply_section_description(sec: dict[str, Any], descriptions: dict[str, str] | None) -> None:
    if not descriptions:
        return
    name = sec.get("Name")
    if name in descriptions:
        sec["Description"] = descriptions[name]


def _repack_section(
    draft: Draft,
    sid: str,
    sec: dict[str, Any],
    field_of_col: dict[str, dict[str, Any]],
    width_of: dict[str, int],
    section_descriptions: dict[str, str] | None,
) -> None:
    ordered = _ordered_section_columns(draft, sec)
    row_ids = sec.get("Column::Row")
    if isinstance(row_ids, list):
        for rid in row_ids:
            draft.pop(rid, None)

    rows = _pack_repack_rows(ordered, field_of_col, width_of)
    sec_name = sec.get("Name", "")
    sec["Column::Row"] = [
        _write_repacked_row(draft, sid, sec_name, i, row)
        for i, row in enumerate(rows)
    ]
    _apply_section_description(sec, section_descriptions)


def _apply_step_descriptions(draft: Draft, step_descriptions: dict[str, str] | None) -> None:
    if not step_descriptions:
        return
    for act in _kind(draft, "Activity").values():
        name = act.get("Name")
        if name in step_descriptions:
            act["Description"] = step_descriptions[name]


def repack_layout(
    draft: Draft,
    widths: dict[str, int] | None = None,
    section_descriptions: dict[str, str] | None = None,
    step_descriptions: dict[str, str] | None = None,
) -> Draft:
    """Re-tile every section's fields at per-type widths, and add section/step subtitles. Pure.

    Only Row nodes are rebuilt. Field and Column ids are preserved, so `Column::Permission` (both the
    field-level and the section-level kind) and `Field::Event` survive untouched.

    A row never exceeds ROW_UNITS — overflowing one is not cosmetic, it breaks rendering for the
    whole flow (observed live: 17 columns at Start=0 in a single Row).
    """
    new: Draft = copy.deepcopy(draft)
    width_of = _resolve_widths(widths)
    field_of_col = _field_by_column(new)

    for sid, sec in _section_columns(new).items():
        _repack_section(new, sid, sec, field_of_col, width_of, section_descriptions)

    _apply_step_descriptions(new, step_descriptions)
    return new


def rename_fields(draft: Draft, renames: dict[str, str]) -> Draft:
    """Rename form fields, `{current name: new name}`. Pure.

    The node id is untouched, so per-step Permissions, Field::Event and any submitted data stay
    attached — a delete-and-recreate would silently orphan all three.

    Only fields belonging to the ROOT model are renamed; child-table columns are left alone, because
    names are not unique across a form and its tables. Unknown or ambiguous names raise.
    """
    new: Draft = copy.deepcopy(draft)
    root = _model_id(new)
    for old, want in renames.items():
        hits = [k for k, v in _kind(new, "Field").items()
                if v.get("Name") == old and v.get("Model") == root]
        if not hits:
            raise ValueError(f"no form field named {old!r}")
        if len(hits) > 1:
            raise ValueError(f"{old!r} is ambiguous: {hits}")
        new[hits[0]]["Name"] = want
    return new


def set_required(draft: Draft, required: set[str]) -> Draft:
    """Set `Required` on ROOT-model fields: True for every name in `required`, False for the rest.

    Pure. Child-table columns are untouched. Unknown names raise, so a typo cannot silently leave a
    field un-required.

    A COMPUTED field must never be Required — the user cannot type into it, so the step can never be
    submitted. That is exactly how `Case ID` (auto-number) and `First Contact Date` (= Created At)
    blocked step 1 on 2026-08-05.
    """
    new: Draft = copy.deepcopy(draft)
    root = _model_id(new)
    fields = {k: v for k, v in _kind(new, "Field").items() if v.get("Model") == root}
    names = {v.get("Name") for v in fields.values()}
    missing = required - names
    if missing:
        raise ValueError(f"no such field(s): {sorted(missing)}")
    for node in fields.values():
        node["Required"] = node.get("Name") in required
    return new


def _is_field_match(name: str, fid: str, node: dict[str, Any]) -> bool:
    return node.get("Name") == name or fid == name


def _field_hits(draft: Draft, name: str) -> list[str]:
    hits = [k for k, v in _kind(draft, "Field").items() if _is_field_match(name, k, v)]
    if not hits:
        raise ValueError(f"no field named {name!r}")
    return hits


def _field_delete_closure(draft: Draft, fields: tuple[str, ...]) -> set[str]:
    doomed: set[str] = set()
    for name in fields:
        for fid in _field_hits(draft, name):
            doomed.add(fid)
            col = draft[fid].get("Column")
            if isinstance(col, str):
                doomed.add(col)
    return doomed


def _table_model_closure(draft: Draft, tid: str) -> set[str]:
    out = {tid}
    table = draft.get(tid, {})
    out.update(table.get("Model::Row", []))
    for cfid in table.get("Model::Field", []):
        out.add(cfid)
        col = draft.get(cfid, {}).get("Column")
        if isinstance(col, str):
            out.add(col)
    return out


def _table_cluster(draft: Draft, host: str) -> set[str]:
    doomed = {host}
    row = draft[host].get("Row")
    if isinstance(row, str):
        doomed.add(row)
    for tid in draft[host].get("Column::Model", []):
        doomed |= _table_model_closure(draft, tid)
    return doomed


def _table_host_map(draft: Draft) -> dict[str, str]:
    return {
        v["Name"]: k
        for k, v in _kind(draft, "Column").items()
        if v.get("Type") == "Model" and v.get("Name")
    }


def _table_delete_closure(draft: Draft, tables: tuple[str, ...]) -> set[str]:
    if not tables:
        return set()
    host_by_name = _table_host_map(draft)
    doomed: set[str] = set()
    for name in tables:
        host = host_by_name.get(name)
        if host is None:
            raise ValueError(f"no table named {name!r}")
        doomed |= _table_cluster(draft, host)
    return doomed


def _nodes_matching_key(draft: Draft, kind: str, key: str, doomed: set[str]) -> set[str]:
    return {k for k, v in _kind(draft, kind).items() if v.get(key) in doomed}


def _doomed_listeners(draft: Draft, doomed: set[str]) -> set[str]:
    return _nodes_matching_key(draft, "Permission", "Column", doomed) | _nodes_matching_key(
        draft, "Event", "Field", doomed
    )


def _str_roots(roots: list[Any]) -> list[str]:
    return [r for r in roots if isinstance(r, str)]


def _node_tree(draft: Draft, roots: list[Any]) -> set[str]:
    """One Expression's whole AST, following `Node::Node` down from each root."""
    out: set[str] = set()
    stack = _str_roots(roots)
    while stack:
        nid = stack.pop()
        if nid in out or nid not in draft:
            continue
        out.add(nid)
        stack.extend(draft[nid].get("Node::Node", []))
    return out


def _query_def_doomed(draft: Draft, nid: str, node: dict[str, Any], doomed: set[str]) -> set[str]:
    return {nid} if node.get("Field") in doomed else set()


def _expr_doomed(draft: Draft, nid: str, node: dict[str, Any], doomed: set[str]) -> set[str]:
    if node.get("Field") in doomed:
        return {nid} | _node_tree(draft, node.get("Expression::Node", []))
    return set()


def _property_cluster(draft: Draft, node: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for eid in node.get("Property::Expression", []):
        out.add(eid)
        expr = draft.get(eid, {})
        out |= _node_tree(draft, expr.get("Expression::Node", []))
    return out


def _prop_doomed(draft: Draft, nid: str, node: dict[str, Any], doomed: set[str]) -> set[str]:
    if node.get("Field") in doomed:
        return {nid} | _property_cluster(draft, node)
    return set()


def _criteria_is_doomed(node: dict[str, Any], doomed: set[str]) -> bool:
    return node.get("FieldValidation") in doomed or node.get("ColumnVisibility") in doomed


def _criteria_doomed(draft: Draft, nid: str, node: dict[str, Any], doomed: set[str]) -> set[str]:
    if not _criteria_is_doomed(node, doomed):
        return set()
    return {nid} | {c for c in node.get("Criteria::Condition", []) if isinstance(c, str)}


_CONFIG_CLUSTER_HANDLERS = {
    "QueryDefinition": _query_def_doomed,
    "Expression": _expr_doomed,
    "Property": _prop_doomed,
    "Criteria": _criteria_doomed,
}


def _config_cluster_closure(draft: Draft, doomed: set[str]) -> set[str]:
    out: set[str] = set()
    for nid, node in draft.items():
        if isinstance(node, dict):
            handler = _CONFIG_CLUSTER_HANDLERS.get(node.get("Kind"))
            if handler is not None:
                out |= handler(draft, nid, node, doomed)
    return out


def delete_closure(draft: Draft, fields: tuple[str, ...] = (), tables: tuple[str, ...] = ()) -> set[str]:
    """Every node id `delete_nodes` will remove for this request. Pure, READ-ONLY on `draft`.

    Split out of `delete_nodes` so the deleter and the reference AUDIT (`field_delete_blockers`)
    reason over ONE derivation of "what goes" — a second, drifting copy of this walk is how an
    audit ends up blessing a delete that removes something it never looked at.

    Three layers:
      1. the named nodes — a Field plus its Column; a table plus its whole cluster (host Column,
         host Row, nested Model, schema Row, every child Column/Field);
      2. the nodes those OWN — every Permission on a doomed Column, every Event on a doomed
         Field, and the field's own configuration cluster: its `QueryDefinition` (a User field's
         mandatory sibling), its computed `Expression` and that formula's whole Node tree, its
         `Property` chain (a SequenceNumber's Padding/Step/PrefixExpression, prefix Expression
         included), and any `Criteria` owning its validation rules or its conditional-visibility
         rule, Conditions and all. Every one of those has exactly ONE inbound reference — a list
         on the very node being deleted — so nothing can ever reach them again; and each keeps a
         SCALAR reference to a now-dead id, which `_sweep_dangling` (list-only, by design) cannot
         see and which is the deterministic publish-500 (#18).
      3. nothing else. A reference from a node that survives — another field's formula reading
         this one, another field's visibility triggered by this one, a script naming its id — is
         NOT swept, because removing it would silently change a field the caller never mentioned.
         Those are refusals, not sweeps: see `field_delete_blockers`.

    Unknown names raise rather than silently doing nothing — a typo must not read as success.
    """
    doomed = _field_delete_closure(draft, fields) | _table_delete_closure(draft, tables)
    doomed |= _doomed_listeners(draft, doomed)
    doomed |= _config_cluster_closure(draft, doomed)
    return doomed


def field_delete_blockers(
    draft: Draft, fields: tuple[str, ...] = (), tables: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Every reference to a doomed node that a SURVIVING node still holds — one sentence each.

    `delete_closure` sweeps a field's own cluster; it deliberately does not touch anything owned
    by a DIFFERENT field, because deleting another field's formula or visibility rule to make
    room for this delete would be a silent, unrequested change to the form. So those are reported
    here and the caller is refused (CLAUDE.md: fail loud, and a dangling scalar publishes 500 with
    zero diagnostics — #18). Each sentence names the remedy, because a refusal a caller cannot
    act on is just a dead end.

    Empty tuple = the delete is clean. Unknown names raise, via `delete_closure`.
    """
    doomed = delete_closure(draft, fields, tables)
    dead_fields = {k for k in doomed if (draft.get(k) or {}).get("Kind") == "Field"}
    # a doomed id must report as the NAME a human typed. A field column carries Name=None (the
    # name lives on its Field), so resolve through the Field node — an id in a refusal message is
    # a refusal the caller cannot act on.
    name_of: dict[str, str] = {k: (draft.get(k) or {}).get("Name") or k for k in doomed}
    for fid in dead_fields:
        col = (draft.get(fid) or {}).get("Column")
        if isinstance(col, str) and col in name_of:
            name_of[col] = (draft[fid].get("Name") or col)
    out: list[str] = []

    for nid, node in draft.items():
        if not isinstance(node, dict) or nid in doomed:
            continue                                   # a doomed node's own refs die with it
        kind = node.get("Kind")
        if kind == "Node" and node.get("Type") == "Field" and node.get("Field") in doomed:
            out.append(
                f"{name_of.get(node['Field'])!r} is read by an Expression that survives this "
                f"delete (Node {nid}) — a branch condition, goto gate or another field's computed "
                "formula. Rewrite or remove that expression first "
                "(forge_set_branch_conditions / forge_apply_fields computed=...)")
        elif kind == "Condition" and node.get("LHSOwnField") in doomed:
            out.append(
                f"{name_of.get(node['LHSOwnField'])!r} is the TRIGGER of another field's "
                f"conditional visibility (Condition {nid}) — re-point or remove that rule first "
                "(forge_apply_fields conditional_visibility=...)")
        elif kind == "Event":
            script = node.get("Script")
            hit = sorted(fid for fid in dead_fields
                         if isinstance(script, str) and fid in script)
            for fid in hit:
                out.append(
                    f"{name_of.get(fid)!r} is named by id in the Script of a surviving Event "
                    f"({nid}) — a script referencing a missing field breaks the WHOLE form at "
                    "load. Rewrite that event first (forge_set_events)")
    return tuple(out)


def delete_nodes(draft: Draft, fields: tuple[str, ...] = (), tables: tuple[str, ...] = ()) -> Draft:
    """Delete form fields and/or child tables by NAME, with every back-reference swept. Pure.

    Deleting a Field means deleting its Column, every Permission that targets that Column, and the
    field's own configuration cluster (events, query definition, computed formula, validation and
    conditional-visibility Criteria, SequenceNumber Properties) — `delete_closure` is the single
    derivation of what goes, and its docstring is the full list. Deleting a table means the whole
    cluster: host Column, host Row, the nested Model, its schema Row, and every child Column/Field.
    A surviving list entry pointing at a deleted node PUTs fine (200) but makes PUBLISH fail with a
    bare MetadataError, so the sweep is not optional.

    This does NOT check whether a node that SURVIVES still points at what it just deleted — that
    audit is `field_delete_blockers`, and a caller that skips it can still build a dangling graph.
    Unknown names raise rather than silently doing nothing — a typo must not read as success.
    """
    doomed = delete_closure(draft, fields, tables)
    new: Draft = copy.deepcopy(draft)

    for nid in doomed:
        new.pop(nid, None)

    for node in new.values():                     # sweep every dangling list reference
        if not isinstance(node, dict):
            continue
        for key, val in list(node.items()):
            if key == "Id" or not isinstance(val, list):
                continue
            kept = [x for x in val if not (isinstance(x, str) and x in doomed)]
            if len(kept) != len(val):
                node[key] = kept
    return new


def unbound_select(ft: FieldType, referred_list: Any) -> bool:
    """THE predicate behind every "a Select must name its list" refusal in this module.

    A Select's OPTIONS live in a SEPARATE list flow, named by `ReferredList`; one written without
    it is a dropdown bound to nothing, which PUTs 200 and then dies on publish with a bare 500
    MetadataError carrying zero diagnostic content (2026-08-19 diagnosis, CLAUDE.md ReferredList
    #13). TWO paths in this module mint a `Field` node from a caller's spec — `apply_changes` for
    a root form field and `add_table` for a table CHILD column — and they must refuse the same
    node for the same reason: sealing only the first left the identical publish-500 reachable
    through the second door, on a flow `forge_add_table` had just built. One derivation, so the
    two cannot drift apart again. `verify.doctor` rule 7b is the read-side sibling (wider, because
    it audits drafts this engine did not build: the whole captured list-backed family, not just
    Select).
    """
    return ft is FieldType.SELECT and not referred_list


def add_table(
    draft: Draft,
    name: str,
    columns: list[tuple[str, FieldType | str]] | list[tuple[str, FieldType | str, dict[str, Any] | None]],
    max_rows: int | None = None,
    allow_import: bool = False,
    after_section: str | None = None,
) -> Draft:
    """Add a child table. Pure. No-op if a table of that name already exists.

    A table is NOT a field type — it is a `Column{Type:"Model"}` hosting a nested `Model`
    (captured 2026-08-04, see FINDINGS.md):

        root Model  --Model::Model-->  table Model
        top-level Row --Row::Column--> host Column{Type:"Model", MaxRow, Column::Model:[table]}
        table Model --Model::Row--> ONE schema Row --Row::Column--> child Column{Start:0,End:0}

    `max_rows` writes `MaxRow`, which is Kissflow's NATIVE row cap — the MAX 2 / MAX 5 containment
    rule needs no client-side enforcement. Child columns carry Start=0/End=0: the 6-unit grid does
    not apply inside a table.

    `after_section` (#10) names a Section whose root row the host row must land directly AFTER in
    root `Model::Row`. An empty banner Section renders ONLY as a caption right above its table —
    appending the host last strands the banner and the whole form fails to render (CLAUDE.md >
    Tables). Unknown name raises before any write. Default None keeps the append behavior.

    A child Select must name its list (`unbound_select`), exactly as a root field must in
    `apply_changes` — the options dict is where a table column carries `ReferredList`. Every
    column is normalized and checked BEFORE the first node is minted, so a refused spec leaves the
    draft untouched rather than half-built.
    """
    # 1) validate everything first (fail loud, before touching the graph)
    normalized: list[tuple[str, FieldType, dict[str, Any] | None]] = []
    for col in columns:
        col_name, col_type = col[0], col[1]
        col_opts = col[2] if len(col) > 2 else None
        ft = FieldType(col_type) if not isinstance(col_type, FieldType) else col_type
        if unbound_select(ft, (col_opts or {}).get("ReferredList")):
            raise ValueError(
                f"table {name!r} column {col_name!r} is Type Select with no ReferredList — a "
                f"Select bound to no list publishes 500 MetadataError with zero diagnostics; "
                f"create the list with forge_create_list, then name it in the column's own "
                f"options: ({col_name!r}, 'Select', {{'ReferredList': '<list id>'}}) "
                f"(CLAUDE.md ReferredList #13)"
            )
        normalized.append((col_name, ft, col_opts))

    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    root = new[model_id]

    for node in new.values():
        if isinstance(node, dict) and node.get("Type") == "Model" and node.get("Name") == name:
            return new                                   # idempotent

    table_id = _new_id("Model", model_id, 0, name)
    host_col = _new_id("Column", model_id, 5000, name)
    host_row = _new_id("Row", model_id, 5000, name)
    schema_row = _new_id("Row", table_id, 0, name)

    new[host_row] = {"Id": host_row, "Kind": "Row", "Model": model_id, "Row::Column": [host_col]}
    host: dict[str, Any] = {
        "Id": host_col, "Kind": "Column", "Type": "Model", "Start": 0, "End": ROW_UNITS,
        "Name": name, "AllowImport": allow_import, "Row": host_row, "Column::Model": [table_id],
    }
    if max_rows is not None:
        host["MaxRow"] = max_rows
    new[host_col] = host

    child_cols: list[str] = []
    child_fields: list[str] = []
    for i, (col_name, ft, col_opts) in enumerate(normalized):
        cid = _new_id("Column", table_id, i, col_name)
        fid = _new_id("Field", table_id, i, col_name)
        new[cid] = {"Id": cid, "Kind": "Column", "Type": "Field", "Row": schema_row,
                    "Start": 0, "End": 0, "Column::Field": [fid]}
        field: dict[str, Any] = {"Id": fid, "Kind": "Field", "Type": ft.value, "CreatedAt": _now(),
                                 "Model": table_id, "Name": col_name, "Column": cid}
        field.update(_TYPE_DEFAULTS.get(ft.value, {}))
        if col_opts:
            field.update(col_opts)  # opt-in per-column keys (Decimalpoint, CaptureOnly, ...), verbatim
        new[fid] = field
        child_cols.append(cid)
        child_fields.append(fid)

    new[schema_row] = {"Id": schema_row, "Kind": "Row", "Model": table_id, "Row::Column": child_cols}
    new[table_id] = {"Id": table_id, "Kind": "Model", "Model": model_id, "Name": name,
                     "CreatedAt": _now(), "Column": host_col,
                     "Model::Row": [schema_row], "Model::Field": child_fields}

    root.setdefault("Model::Model", []).append(table_id)
    rows = root.setdefault("Model::Row", [])
    if after_section is None:
        rows.append(host_row)
    else:
        anchor = next((v.get("Row") for v in new.values()
                       if isinstance(v, dict) and v.get("Kind") == "Column"
                       and v.get("Type") == "Section" and v.get("Name") == after_section), None)
        if anchor not in rows:
            raise ValueError(f"after_section {after_section!r}: no Section of that name has a root row")
        rows.insert(rows.index(anchor) + 1, host_row)
    return new


def add_sequence_number(
    draft: Draft,
    field_name: str,
    section_name: str,
    prefix: str,
    padding: str,
    step_activity_name: str,
    start: int = 0,
    end: int = FIELD_SPAN,
) -> Draft:
    """Add an auto-numbered item-id field (`Type:"SequenceNumber"`) in its own hidden row at the
    end of a named section. Pure. No-op if a SequenceNumber field of that name already exists.

    Captured from a UI-built oracle (CLAUDE.md "SequenceNumber = auto-numbered item id"). The node
    tree is NOT just a Field — it carries three Property nodes the runtime stamps:

        Field{Type:"SequenceNumber", Model:<root>, Column:<hidden col>, Field::Property:[3]}
          Property{Name:"Padding",          ValueType:"Value",      Value:<padding>}        # e.g. "0001"
          Property{Name:"Step",             ValueType:"Value",      Value:<activity id>}    # stamped here
          Property{Name:"PrefixExpression",  ValueType:"Expression", Property::Expression:[expr]}
            Expression{ExpressionStr:'concatenate("<prefix>")', Property:<prop>, Expression::Node:[root]}
              Node{Type:"Function", Value:"concatenate", Node::Node:[literal], DataType/Category:"String"}
              Node{Type:"Static",  Value:<prefix>, Node:<root>, DataType:"String"}

    The host `Column` is `IsHidden:true` and the builder writes NO Permissions for it (hidden
    columns have no per-step visibility). The Step stamp's target activity is resolved by NAME
    (`step_activity_name`) since the rebuild's activity ids differ from any oracle's. Call this
    AFTER `apply_exact_layout` so the section's rows are already placed; the new row is appended.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    model = new[model_id]

    if any(isinstance(v, dict) and v.get("Type") == "SequenceNumber" and v.get("Name") == field_name
           for v in new.values()):
        return new                                   # idempotent

    sections = {v.get("Name", ""): sid for sid, v in new.items()
                if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Section"}
    if section_name not in sections:
        raise ValueError(f"add_sequence_number: section not found: {section_name!r}")
    sid = sections[section_name]

    act_id = next((v.get("Id") for v in new.values()
                   if isinstance(v, dict) and v.get("Kind") == "Activity"
                   and v.get("Name") == step_activity_name), None)
    if not act_id:
        raise ValueError(f"add_sequence_number: activity not found: {step_activity_name!r}")

    fid = _new_id("Field", model_id, 0, field_name)
    cid = _new_id("Column", model_id, 0, field_name)
    rid = _new_id("Row", sid, 6000, field_name)
    pad_id = _new_id("Property", model_id, 1, field_name)
    pre_id = _new_id("Property", model_id, 2, field_name)
    step_id = _new_id("Property", model_id, 3, field_name)
    expr_id = _new_id("Expression", model_id, 0, field_name)
    root_node = _new_id("Node", model_id, 0, field_name)
    lit_node = _new_id("Node", model_id, 1, field_name)

    new[rid] = {"Id": rid, "Kind": "Row", "Column": sid, "Row::Column": [cid]}
    new[sid]["Column::Row"] = (new[sid].get("Column::Row") or []) + [rid]

    new[cid] = {"Id": cid, "Kind": "Column", "Type": "Field", "Start": start, "End": end,
                "Row": rid, "IsHidden": True, "Column::Field": [fid]}

    new[fid] = {"Id": fid, "Kind": "Field", "Type": "SequenceNumber", "CreatedAt": _now(),
                "Model": model_id, "Name": field_name, "Column": cid,
                "Field::Property": [pad_id, pre_id, step_id]}
    model.setdefault("Model::Field", []).append(fid)

    new[pad_id] = {"Id": pad_id, "Kind": "Property", "Name": "Padding", "Field": fid,
                   "Value": padding, "ValueType": "Value"}
    new[pre_id] = {"Id": pre_id, "Kind": "Property", "Name": "PrefixExpression", "Field": fid,
                   "ValueType": "Expression", "Property::Expression": [expr_id]}
    new[step_id] = {"Id": step_id, "Kind": "Property", "Name": "Step", "Field": fid,
                    "Value": act_id, "ValueType": "Value"}

    new[expr_id] = {"Id": expr_id, "Kind": "Expression",
                    "ExpressionStr": f'concatenate("{prefix}")', "Property": pre_id,
                    "Expression::Node": [root_node]}
    new[root_node] = {"Id": root_node, "Kind": "Node", "Type": "Function", "Value": "concatenate",
                      "Expression": expr_id, "Node::Node": [lit_node],
                      "DataType": "String", "Category": "String"}
    new[lit_node] = {"Id": lit_node, "Kind": "Node", "Type": "Static", "Value": prefix,
                     "DataType": "String", "Node": root_node}
    return new


def add_field_validation(
    draft: Draft,
    field_name: str,
    operator: str,
    value: str,
    rhs_type: str = "Value",
    error_message: str | None = None,
) -> Draft:
    """Attach a per-field validation rule. Pure. Idempotent on (field_name, operator, value).

    Kissflow has no formula type; a per-field validation is a flat Condition tree (captured from a
    UI-built oracle, CLAUDE.md F7), NOT an Expression/Node AST:

        Field --FieldValidation::Criteria--> Criteria{FieldValidation:<fid>, Criteria::Condition:[...]}
          Condition{Operator, HasArguments:true, Criteria:<cid>, RHSType:"Value", RHSValue:<literal>,
                    ErrorMessage:<human-readable failure text>}

    One Criteria per field (the builder writes one); each rule is one Condition under it. A second
    rule on the same field appends a Condition to the existing Criteria. `operator` is e.g.
    "CONTAINS" / "MAX_LENGTH"; `value` is the literal (a string); `rhs_type` defaults to "Value".

    `error_message` (shapes/field_validation_criteria.json, live-captured 2026-08-12, #48) is the
    Condition's own human-readable failure text — the platform writes one on every Condition it
    creates; omitted here means the key is simply not written (the engine's own additive-Criteria-
    reuse behavior still differs from the platform's one-Criteria-per-rule pattern — see that
    shape's notes — but is left unchanged, only the missing key is closed).
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    fld = next((v for v in new.values()
                if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == field_name), None)
    if not fld:
        raise ValueError(f"add_field_validation: field not found: {field_name!r}")
    fid = fld["Id"]

    for cid in fld.get("FieldValidation::Criteria") or []:
        for condid in (new.get(cid, {}).get("Criteria::Condition") or []):
            c = new.get(condid, {})
            if c.get("Operator") == operator and str(c.get("RHSValue")) == str(value):
                return new                                   # idempotent

    existing = fld.get("FieldValidation::Criteria") or []
    if existing:
        cid = existing[0]
    else:
        cid = _new_id("Criteria", model_id, 0, field_name)
        new[cid] = {"Id": cid, "Kind": "Criteria", "FieldValidation": fid, "Criteria::Condition": []}
        fld["FieldValidation::Criteria"] = [cid]
    cond_id = _new_id("Condition", model_id, len(new[cid].get("Criteria::Condition", [])), field_name)
    condition: dict[str, Any] = {"Id": cond_id, "Kind": "Condition", "Operator": operator,
                                 "HasArguments": True, "Criteria": cid, "RHSType": rhs_type,
                                 "RHSValue": value}
    if error_message is not None:
        condition["ErrorMessage"] = error_message
    new[cond_id] = condition
    new[cid]["Criteria::Condition"] = (new[cid].get("Criteria::Condition") or []) + [cond_id]
    return new


# Function catalog captured live off the builder's Formula tool (docs/capabilities/config.computed.md,
# #48): `rand randBetween dateDiff calendarDays currency number if concatenate date dateTime
# dateFromText dateTimeFromText now initiatedat today isBlank false true not`. Not enforced as a
# closed set here (a caller may reasonably use a function the sweep never happened to exercise) —
# kept as a comment, not a validation gate, per this project's "never guess, but don't over-refuse
# either" balance: refuse a MALFORMED formula shape, not an unfamiliar function name.


def _computed_arg_node(
    new: Draft, model_id: str, expr_id: str, parent_id: str, i: int, name: str, arg: dict[str, Any],
) -> str:
    """One leaf/branch Node of a computed-field formula AST. `arg` is `{"field": <name>}`,
    `{"static": <value>}`, or a nested `{"fn": <name>, "args": [...]}`. Mutates `new` in place;
    returns the new node's id. Raises ValueError on a field ref that does not resolve."""
    if "field" in arg:
        ref = next((v for v in new.values()
                    if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == arg["field"]),
                   None)
        if ref is None:
            raise ValueError(f"set_field_computed({name!r}): no field named {arg['field']!r} to reference")
        nid = _new_id("Node", expr_id, i, f"field:{arg['field']}")
        new[nid] = {"Id": nid, "Kind": "Node", "Type": "Field", "Field": ref["Id"],
                    "DataType": ref.get("Type", "String"), "Node": parent_id}
        if nid not in (ref.get("Field::Node") or []):
            ref.setdefault("Field::Node", []).append(nid)
        return nid
    if "fn" in arg:
        return _computed_fn_node(new, model_id, expr_id, parent_id, i, name, arg)
    if "static" in arg:
        value = arg["static"]
        data_type = arg.get("data_type") or ("Number" if isinstance(value, (int, float)) else "String")
        nid = _new_id("Node", expr_id, i, f"static:{value}")
        new[nid] = {"Id": nid, "Kind": "Node", "Type": "Static", "Value": value,
                    "DataType": data_type, "Node": parent_id}
        return nid
    raise ValueError(f"set_field_computed({name!r}): each arg needs one of field/static/fn, got {arg!r}")


def _computed_fn_node(
    new: Draft, model_id: str, expr_id: str, parent_id: str | None, i: int, name: str,
    formula: dict[str, Any],
) -> str:
    fn = formula.get("fn")
    args = formula.get("args") or []
    if not isinstance(fn, str) or not fn:
        raise ValueError(f"set_field_computed({name!r}): formula needs a non-empty 'fn' string")
    data_type = formula.get("data_type", "String")
    nid = _new_id("Node", expr_id, i, f"fn:{fn}")
    child_ids = []
    node: dict[str, Any] = {"Id": nid, "Kind": "Node", "Type": "Function", "Value": fn,
                            "DataType": data_type, "Category": data_type}
    if parent_id is None:
        node["Expression"] = expr_id      # the ROOT node owns the Expression back-ref
    else:
        node["Node"] = parent_id          # a nested function call owns its parent Node back-ref
    new[nid] = node
    for j, arg in enumerate(args):
        child_ids.append(_computed_arg_node(new, model_id, expr_id, nid, j, name, arg))
    if child_ids:
        new[nid]["Node::Node"] = child_ids
    new[nid]["FieldRefCount"] = sum(1 for c in child_ids if new[c].get("Type") == "Field")
    return nid


def _formula_str(arg: dict[str, Any]) -> str:
    """Best-effort human-readable mirror for ExpressionStr — NEVER evaluated, same "readable
    mirror only" rule as every other Expression in this codebase."""
    if "field" in arg:
        return str(arg["field"])
    if "static" in arg:
        return repr(arg["static"])
    if "fn" in arg:
        inner = ", ".join(_formula_str(a) for a in (arg.get("args") or []))
        return f'{arg["fn"]}({inner})'
    return "?"


def set_field_computed(draft: Draft, field_name: str, formula: dict[str, Any]) -> Draft:
    """Attach a computed-field formula: the FOURTH Expression owner, `Field` (docs/capabilities/
    config.computed.md, live-captured 2026-08-12, #48) — replaces the old "Kissflow has no
    formula/computed field type" belief; field events (kfforge.graph.set_field_events) remain a
    separate, still-valid script-based mechanism. Pure. Idempotent: replaces any existing
    Field::Expression on the named field (same "delete old, rebuild" idiom as set_field_events).

    `formula` is `{"fn": <function name>, "args": [...], "data_type": <optional, default
    "String">}` — a small AST, not a raw string. Each entry of `args` is one of:
    `{"field": <field name>}` (resolved to that field's id — raises if it does not exist),
    `{"static": <literal>, "data_type": <optional>}`, or a nested `{"fn": ..., "args": [...]}`.
    The root Function node carries NO `Syntax` key (a prefix call, unlike the infix `=` roots of a
    branch/goto condition — captured live, see the shape's own note).

    Raises ValueError, draft entirely unmutated on failure (a deep copy is only committed to
    `draft` at the very end — see below), when `field_name` does not exist, `formula` is
    malformed, or an arg's `field` reference does not resolve.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    fld = next((v for v in new.values()
                if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == field_name), None)
    if not fld:
        raise ValueError(f"set_field_computed: field not found: {field_name!r}")
    fid = fld["Id"]

    for old in fld.get("Field::Expression") or []:
        old_expr = new.pop(old, None) or {}
        for root_id in old_expr.get("Expression::Node") or []:
            stack = [root_id]
            while stack:
                nid = stack.pop()
                node = new.pop(nid, None)
                if node:
                    stack.extend(node.get("Node::Node") or [])
    fld.pop("Field::Expression", None)

    expr_id = _new_id("Expression", fid, 0, field_name)
    root_id = _computed_fn_node(new, model_id, expr_id, None, 0, field_name, formula)
    new[expr_id] = {"Id": expr_id, "Kind": "Expression", "Field": fid,
                    "ExpressionStr": _formula_str(formula), "Expression::Node": [root_id]}
    fld["Field::Expression"] = [expr_id]
    return new


def set_conditional_visibility(
    draft: Draft,
    field_name: str,
    trigger_field_name: str,
    operator: str,
    rhs: str,
) -> Draft:
    """Attach form-level conditional visibility: the THIRD Criteria owner family,
    `ColumnVisibility` (docs/capabilities/config.conditional-visibility.md, live-captured
    2026-08-12, #48) — distinct from per-step Permission nodes AND from page Container Criteria.
    Pure. Idempotent: replaces any existing ColumnVisibility::Criteria on the target field.

    The TARGET field's column gets static `IsHidden: true` plus a `ColumnVisibility::Criteria` ->
    `Criteria{IsOR: false}` -> `Condition{Operator, HasArguments: false, LHSOwnField: <TRIGGER
    field's column id — not a Field id>, RHSValue: str(rhs)}`. The trigger column gets the
    bidirectional `LHSOwnField::Condition` back-ref. Raises ValueError, draft entirely unmutated,
    when either field name does not exist.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)

    target = next((v for v in new.values()
                   if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Name") == field_name),
                  None)
    if not target:
        raise ValueError(f"set_conditional_visibility: field not found: {field_name!r}")
    trigger = next((v for v in new.values()
                    if isinstance(v, dict) and v.get("Kind") == "Field"
                    and v.get("Name") == trigger_field_name), None)
    if not trigger:
        raise ValueError(f"set_conditional_visibility: trigger field not found: {trigger_field_name!r}")

    target_col_id = target.get("Column")
    trigger_col_id = trigger.get("Column")
    if not isinstance(target_col_id, str) or target_col_id not in new:
        raise ValueError(f"set_conditional_visibility: field {field_name!r} has no valid Column")
    if not isinstance(trigger_col_id, str) or trigger_col_id not in new:
        raise ValueError(f"set_conditional_visibility: trigger {trigger_field_name!r} has no valid Column")
    target_col = new[target_col_id]
    trigger_col = new[trigger_col_id]

    for old_cid in target_col.get("ColumnVisibility::Criteria") or []:
        old_criteria = new.pop(old_cid, None) or {}
        for old_condid in old_criteria.get("Criteria::Condition") or []:
            old_cond = new.pop(old_condid, None) or {}
            old_trigger_col = old_cond.get("LHSOwnField")
            if isinstance(old_trigger_col, str) and old_trigger_col in new:
                remaining = [c for c in (new[old_trigger_col].get("LHSOwnField::Condition") or [])
                            if c != old_condid]
                if remaining:
                    new[old_trigger_col]["LHSOwnField::Condition"] = remaining
                else:
                    new[old_trigger_col].pop("LHSOwnField::Condition", None)

    cid = _new_id("Criteria", model_id, 0, f"visibility:{field_name}")
    cond_id = _new_id("Condition", model_id, 0, f"visibility:{field_name}")
    new[cond_id] = {"Id": cond_id, "Kind": "Condition", "Operator": operator, "HasArguments": False,
                    "LHSOwnField": trigger_col_id, "Criteria": cid, "RHSValue": str(rhs)}
    new[cid] = {"Id": cid, "Kind": "Criteria", "IsOR": False, "ColumnVisibility": target_col_id,
               "Criteria::Condition": [cond_id]}
    target_col["IsHidden"] = True
    target_col["ColumnVisibility::Criteria"] = [cid]
    if cond_id not in (trigger_col.get("LHSOwnField::Condition") or []):
        trigger_col.setdefault("LHSOwnField::Condition", []).append(cond_id)
    return new


def set_field_events(draft: Draft, events: dict[str, list[tuple[str, str]]]) -> Draft:
    """Attach SDK events to fields. `events` maps a field NAME to [(trigger, script), ...]. Pure.

    Captured shape: `Field::Event[]` back-ref on the field, plus
    `Event{Id, Kind:"Event", Field, Trigger, Script}`. Replaces every existing event on the named
    fields so re-running is idempotent; fields not named keep theirs.

    ⚠️ The builder's editor parses a script as a PLAIN FUNCTION BODY — a top-level `await` is a
    SyntaxError there, and `KFSDK` is undefined (only `kf` is injected). Both are rejected here
    rather than written and discovered at render time.
    """
    new: Draft = copy.deepcopy(draft)
    by_name = {v["Name"]: k for k, v in _kind(new, "Field").items() if v.get("Name")}

    for fname, specs in events.items():
        fid = by_name.get(fname)
        if fid is None:
            raise ValueError(f"no field named {fname!r}")
        for old in new[fid].get("Field::Event") or []:
            new.pop(old, None)

        ids: list[str] = []
        for i, (trigger, script) in enumerate(specs):
            if "KFSDK" in script:
                raise ValueError(f"{fname!r}: KFSDK is undefined in a form event — use the injected kf")
            # A script referencing a field that no longer exists breaks the WHOLE form at load:
            # "Configuration for <id> is not present in container <flow>". Kissflow validates the
            # refs, so a stale id is not a silent no-op — catch it here instead of live.
            for ref in re.findall(r'\b(Field_\w+)\b', script):
                if ref not in draft:
                    raise ValueError(f"{fname!r}: script references missing field {ref!r}")
            body = re.sub(r"\(async\s*\(\)\s*=>\s*\{[\s\S]*\}\)\(\);?", "", script)
            if re.search(r"\bawait\b", body):
                raise ValueError(f"{fname!r}: top-level await — wrap the script in (async () => {{...}})()")
            eid = _new_id("Event", fid, i, trigger)
            new[eid] = {"Id": eid, "Kind": "Event", "Field": fid,
                        "Trigger": trigger, "Script": script}
            ids.append(eid)
        new[fid]["Field::Event"] = ids
    return new


def _style_wire_value(prop: str, v: str | dict[str, Any]) -> dict[str, Any]:
    """Normalize one style property to its wire shape: a bare token string wraps as
    {"ref": token} (the dominant, form-proven shape); an explicit {"ref": ...} or
    {"value": ...} dict passes through verbatim (#11 — the old bare-string type rejected the
    real captured shape at the tool boundary, so styles never landed at all)."""
    if isinstance(v, dict):
        if v and set(v) <= {"ref", "value"}:
            return v
        raise ValueError(f"style {prop!r}: a dict value must use 'ref' or 'value', got {v!r}")
    return {"ref": v}


def _write_style_props(style_node: dict[str, Any], props: dict[str, Any]) -> None:
    """Merge props into a Style node's Value. None removes (back to the theme default — the only
    way to undo, since Kissflow persists non-default values only). Mutates in place."""
    value = dict(style_node.get("Value") or {})
    for prop, token in props.items():
        if token is None:
            value.pop(prop, None)
        else:
            value[prop] = _style_wire_value(prop, token)
    if value:
        style_node["Value"] = value
    else:
        style_node.pop("Value", None)          # an empty Value is what "unstyled" looks like


def set_section_style(
    draft: Draft,
    styles: dict[str, dict[str, Any]],
    root_style: dict[str, Any] | None = None,
    hint_text_position: str | None = None,
) -> Draft:
    """Colour sections AND (optionally) the root Model's own chain (#11). Pure.

    `styles` maps a section NAME to {property: value}; `root_style` writes the same shape onto
    the ROOT Model's Appearance/Style chain (the one CLAUDE.md's Node-graph invariants make
    mandatory), and `hint_text_position` sets `HintTextPosition` on the root Appearance node
    (oracle carries "Icon"). A value is a bare token string (wrapped as {"ref": ...}), an
    explicit {"ref": ...}/{"value": ...} dict (verbatim), or None (property REMOVED — back to
    the theme default, the only way to undo a colour).

    Captured shape (builder-written, 2026-08-04; root chain + HintTextPosition read off the live
    oracle 2026-08-10, #11):
        Column{Type:Section} --Column::Appearance--> Appearance{Column} --Appearance::Style--> Style
        Model --Model::Appearance--> Appearance{Model, HintTextPosition?} --Appearance::Style--> Style
        Style.Value = {"Section.Bg.Color": {"ref": "Color.Info.300"}, ...}

    On a FORM every captured colour is a TOKEN REF, never hex. ⚠️ The API does NOT validate them:
    `Color.Totally.Bogus.999` was accepted, published and read back verbatim (two-arm test,
    2026-08-04). A wrong token therefore fails SILENTLY at render time. Only use tokens seen in the
    builder's own dropdown. Idempotent: an existing Appearance/Style pair is reused, never
    duplicated — and every Appearance this writes owns exactly one Style, because an Appearance
    with an EMPTY Appearance::Style breaks the whole form's render (CLAUDE.md render-breakers).
    """
    new: Draft = copy.deepcopy(draft)
    by_name = {v["Name"]: k for k, v in _kind(new, "Column").items()
               if v.get("Type") == "Section" and v.get("Name")}

    def _chain(owner_id: str, owner_key: str, back_key: str, name: str) -> str:
        """Ensure owner --back_key--> Appearance --Appearance::Style--> Style; return style id."""
        owner = new[owner_id]
        existing = (owner.get(back_key) or [None])[0]
        if existing and existing in new:
            app_id = existing
        else:
            app_id = _new_id("Appearance", owner_id, 0, name)
            new[app_id] = {"Id": app_id, "Kind": "Appearance", owner_key: owner_id,
                           "Appearance::Style": []}
            owner[back_key] = [app_id]
        style_id = (new[app_id].get("Appearance::Style") or [None])[0]
        if not style_id or style_id not in new:
            style_id = _new_id("Style", owner_id, 0, name)
            new[style_id] = {"Id": style_id, "Kind": "Style", "Appearance": app_id}
            new[app_id]["Appearance::Style"] = [style_id]
        return style_id

    for name, props in styles.items():
        sid = by_name.get(name)
        if sid is None:
            raise ValueError(f"no section named {name!r}")
        _write_style_props(new[_chain(sid, "Column", "Column::Appearance", name)], props)

    if root_style is not None or hint_text_position is not None:
        model_id = _model_id(new)
        style_id = _chain(model_id, "Model", "Model::Appearance", "Root")
        if root_style:
            _write_style_props(new[style_id], root_style)
        if hint_text_position is not None:
            new[new[style_id]["Appearance"]]["HintTextPosition"] = hint_text_position
    return new


def _sweep_dangling(draft: Draft) -> None:
    """Drop every reference to a node that no longer exists. Mutates in place.

    A relation/back-reference list is keyed with "::" everywhere in this graph (Row::Column,
    Column::Row, Model::Row, Activity::Permission, ...) — the SAME criterion verify.doctor's own
    dangling-ref check uses (kfforge/verify.py). A plain key with no "::" holds data, never a node
    id (e.g. a Permission node's own `"Permission": ["Editable"]`), so it is left alone. This used
    to filter by a fixed set of id PREFIXES (Activity_/ProcessDef_/Resource_/Permission_) — narrow
    enough that a caller deleting a different kind of node (Row/Column, from regroup_into_sections)
    got no sweep at all and left orphaned refs behind (issue: template-shell regroup corruption).
    Generalising to the same "::"-key rule as doctor closes that gap for every past and future
    deletion, not just the four kinds this function originally knew about.

    Columns keep a `Column::Permission` back-reference list. Leaving one pointing at a deleted
    Permission still PUTs fine (200) but makes PUBLISH fail with a bare MetadataError.

    This sweeps by "target is absent", NOT "target was deleted by me" — a draft can already carry
    orphans from an earlier partial write, and those must go too.
    """
    for node in draft.values():
        if not isinstance(node, dict):
            continue
        for key, val in list(node.items()):
            if key == "Id" or not isinstance(val, list) or "::" not in key:
                continue
            kept = [x for x in val if not (isinstance(x, str) and x not in draft)]
            if len(kept) == len(val):
                continue
            if kept:
                node[key] = kept
            else:
                del node[key]


Step = tuple[str, str | None]                       # (step name, app-role id or None)
Branch = tuple[str, list[Step]]                     # (branch name, its steps)


ParallelSpec = tuple[str, list[Branch]]                      # (parallel name, its branches)


def build_workflow(
    draft: Draft,
    steps: list[Step],
    parallel: ParallelSpec | None = None,
    parallel_after: int | None = None,
    roles: dict[str, str] | None = None,
    step_meta: dict[str, dict[str, Any]] | None = None,
    parallels: list[tuple[ParallelSpec, int]] | None = None,
) -> Draft:
    """Replace the whole workflow: Start -> steps -> [Parallel branches]* -> ... -> End.

    Shape copied from a live captured parallel node:
      Parallel Activity {NodeType:"Parallel", Activity::ProcessDef:[branch pd ids]}
      branch ProcessDef {Name, Activity:<parallel activity id>, ProcessDef::Activity:[...]}
    There are still no edges — order within each ProcessDef::Activity IS the flow.

    Supports N sequential Parallel gateways via `parallels`: a list of `(parallel_spec,
    after_index)` pairs, each meaning exactly what the single `parallel`/`parallel_after` pair
    meant before — `after_index` is the same 0-indexed position into `steps`. Passing both
    `parallels` and `parallel` is ambiguous and raises ValueError. Two or more parallels sharing
    the same `after_index` are inserted in list order, back to back, right after that step.

    DESTRUCTIVE: every existing Activity/ProcessDef/Resource is replaced, so per-step Permission
    nodes that referenced them are dropped too. Snapshot before calling. `roles` maps a role id to
    its display name, used to label the Resource (assignee) written on each step. Pure.
    """
    if parallels is not None and parallel is not None:
        raise ValueError(
            "build_workflow: pass either 'parallel'/'parallel_after' or 'parallels', not both"
        )
    if parallels is not None:
        specs: list[tuple[ParallelSpec, int]] = list(parallels)
    elif parallel is not None and parallel_after is not None:
        specs = [(parallel, parallel_after)]
    else:
        specs = []

    # Every branch NAME across every parallel must be globally unique. A branch id is
    # `_new_id("ProcessDef", model_id, branch_index, name)` — a hash of (model, kind, index,
    # name) — so two branches sharing a name (even across different splits) would either collide
    # outright or make the branch-local rework-loop derivation (which keys on branch/stage names,
    # see CLAUDE.md Conditional routing) genuinely ambiguous. Hard refuse rather than silently
    # overwrite one branch with another.
    seen_branch_names: dict[str, None] = {}
    for (_pname, branches), _after in specs:
        for bname, _bsteps in branches:
            if bname in seen_branch_names:
                raise ValueError(
                    f"build_workflow: duplicate branch name {bname!r} across parallels — "
                    "a branch id is a hash of (model, kind, index, name), so two branches "
                    "sharing a name would collide (silently overwriting one branch's "
                    "ProcessDef with the other's) and make the branch-local rework-loop "
                    "derivation ambiguous; refusing rather than silently overwriting"
                )
            seen_branch_names[bname] = None

    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)
    model = new[model_id]
    roles = roles or {}
    step_meta = step_meta or {}

    # Names of the activities about to die, BEFORE deletion — a SequenceNumber's Step Property
    # holds a SCALAR activity id the list-only sweep never touches; left dangling it makes
    # publish 500 MetadataError deterministically with zero diagnostics (#18, isolated live
    # 2026-08-12 by subsystem bisect). Repointed by NAME after the rebuild, below.
    old_activity_names = {k: v.get("Name") for k, v in new.items()
                          if isinstance(v, dict) and v.get("Kind") == "Activity"}

    for nid in [k for k, v in new.items() if isinstance(v, dict)
                and v.get("Kind") in ("Activity", "ProcessDef", "Resource", "Permission")]:
        del new[nid]
    _sweep_dangling(new)

    root_pd = _new_id("ProcessDef", model_id, 0, "root")
    counter = [0]
    branch_index = [100]   # monotonic across ALL branches of ALL parallels — keeps branch pd ids
                            # globally unique even when two parallels each start their own branches
                            # at b_i == 0.

    def _activity(name: str, node_type: str, pd: str, role: str | None) -> str:
        counter[0] += 1
        aid = _new_id("Activity", model_id, counter[0], name)
        node: dict[str, Any] = {"Id": aid, "Kind": "Activity", "NodeType": node_type,
                                "Name": name, "ProcessDef": pd}
        if role:
            rid = _new_id("Resource", model_id, counter[0], name)
            new[rid] = {"Id": rid, "Kind": "Resource", "ValueType": "AppRole", "Value": role,
                        "DisplayValue": roles.get(role, role), "Activity": aid}
            node["Activity::Resource"] = [rid]
        # opt-in per-step metadata: `suspended` writes IsSuspended+SuspendedAt (the step is
        # SKIPPED at runtime, CLAUDE.md "IsSuspended = the step is SKIPPED"); `description` is the
        # step's prose. Start/EndEvent carry neither, so meta absent for them = no-op.
        meta = step_meta.get(name)
        if meta:
            if meta.get("suspended"):
                node["IsSuspended"] = True
                node["SuspendedAt"] = _now()
            if meta.get("description"):
                node["Description"] = meta["description"]
        new[aid] = node
        return aid

    def _insert_parallel(pname: str, branches: list[Branch]) -> str:
        counter[0] += 1
        par = _new_id("Activity", model_id, counter[0], pname)
        branch_ids: list[str] = []
        for bname, bsteps in branches:
            bpd = _new_id("ProcessDef", model_id, branch_index[0], bname)
            branch_index[0] += 1
            new[bpd] = {"Id": bpd, "Kind": "ProcessDef", "Name": bname, "Activity": par,
                        "ProcessDef::Activity": [_activity(n, "UserTask", bpd, r)
                                                 for n, r in bsteps]}
            branch_ids.append(bpd)
        new[par] = {"Id": par, "Kind": "Activity", "NodeType": "Parallel", "Name": pname,
                    "ProcessDef": root_pd, "Activity::ProcessDef": branch_ids}
        return par

    chain: list[str] = [_activity("Start", "StartEvent", root_pd, None)]
    for i, (name, role) in enumerate(steps):
        chain.append(_activity(name, "UserTask", root_pd, role))
        for (pname, branches), after_index in specs:
            if after_index == i:
                chain.append(_insert_parallel(pname, branches))
    chain.append(_activity("End", "EndEvent", root_pd, None))

    new[root_pd] = {"Id": root_pd, "Kind": "ProcessDef", "WorkflowType": "Sequence",
                    "Model": model_id, "ProcessDef::Activity": chain}
    new["SendBackToInitiator"] = {"Id": "SendBackToInitiator", "Kind": "Activity",
                                  "NodeType": "SendBackToInitiator", "BaseMetadata": chain[0]}
    model["Model::ProcessDef"] = [root_pd]
    model["RootProcessDef"] = root_pd

    # Repoint every Step-stamp Property left dangling by the rebuild (#18): same-name activity
    # when the rebuilt workflow still has one, else the new StartEvent (a sequence number stamps
    # at intake by default) — never a dangling scalar, which is the exact publish-500 condition.
    new_by_name = {v.get("Name"): k for k, v in new.items()
                   if isinstance(v, dict) and v.get("Kind") == "Activity" and v.get("Name")}
    for node in new.values():
        if not (isinstance(node, dict) and node.get("Kind") == "Property"
                and node.get("Name") == "Step"):
            continue
        tgt = node.get("Value")
        if isinstance(tgt, str) and tgt not in new:
            old_name = old_activity_names.get(tgt)
            node["Value"] = new_by_name.get(old_name) or chain[0]
    return new


def add_goto_task(
    draft: Draft,
    *,
    target_activity_id: str,
    name: str | None = None,
    branch_process_def_id: str | None = None,
) -> tuple[Draft, str]:
    """Add a GotoTask: a backward-jump edge node targeting `target_activity_id`. Pure.

    `build_workflow` only ever produces a straight-line/parallel chain — nothing else in this
    module writes the one genuine edge node a Sequence workflow has (CLAUDE.md "A CORRECTED
    BELIEF... GotoTask is an edge node"). This is that missing builder, shape copied verbatim from
    shapes/goto_task.json (captured 2026-08-05 from a UI-built flow): the new Activity carries
    `NodeType:"GotoTask"`, a scalar `Goto` forward-pointer at the target, and joins the SAME
    ProcessDef::Activity chain as its target (a branch-local jump, never cross-branch). The target
    gets the bidirectional `Goto::Activity` back-ref.

    ⚠️ A CORRECTION to CLAUDE.md's own "sits LAST in ProcessDef::Activity", found live 2026-08-06
    building Node G's acceptance suite: that note was captured off shapes/goto_task.json's
    MINIMAL 2-node illustration (one UserTask + the GotoTask, no Start/End shown at all), where
    "last" and "last of the two elements shown" were indistinguishable. Against a REAL workflow
    that has a terminal EndEvent, appending the GotoTask AFTER it — literally last in the array —
    PUTs 400 `KISSFLOW_ERROR_00011 InvalidArguments` (an unhelpful, field-less error; found via a
    two-arm live experiment: identical draft, only the insertion point differs). The position that
    PUTs 200 is LAST AMONG THE REAL ACTIVITIES, immediately BEFORE a trailing EndEvent — so this
    inserts there when the chain ends in one, and only falls back to a plain append (matching the
    original minimal capture exactly) when it doesn't.

    ⚠️ Node M (2026-08-07): `branch_process_def_id` is a NEW, opt-in lever — the gap it closes.
    Without it, the chain that hosts the new GotoTask was always DERIVED from the target's own
    `ProcessDef`, with no way for a caller to say which chain they actually meant. That is silently
    wrong exactly when a caller resolves `target_activity_id` to a step OUTSIDE the branch they
    intended (a shared root-chain step, say) while meaning to build a per-branch loop: the GotoTask
    lands last in THAT step's own chain instead — for a root-chain target, that means after the
    LAST root-chain activity (i.e. after the Parallel gateway itself), evaluated once for the whole
    item instead of scoped to one branch (reproduced live 2026-08-07, node M: a target 2 steps
    before a 2-branch Parallel landed the GotoTask after the LAST root step, not inside either
    branch). Passing `branch_process_def_id` explicitly turns that silent misplacement into a loud,
    pre-write ValueError: the target must ALREADY belong to that exact ProcessDef, or this raises
    rather than building a shape `verify.doctor`'s own rule 2b ("jumps out of its own branch") would
    flag anyway — CLAUDE.md Workflow's "branch-local jump, never cross-branch" is proven live on
    the oracle app's own two GotoTasks (both same-branch) and is enforced here, not relaxed:
    `branch_process_def_id` PINS and VALIDATES the intended branch, it does not enable a cross-
    branch jump. Omit it (the default, `None`) and behavior is BYTE-IDENTICAL to before this
    parameter existed — the chain is derived from the target's own ProcessDef, root-chain callers
    included.

    Carries no condition of its own and no Permission (like every GotoTask/Parallel — see
    NO_PERMISSION_NODETYPES): pair with `kfforge.expr.build_goto_gate` to add the Boolean loop
    condition, or the Goto loops forever (verify.doctor's rule 2b flags a bare one).

    `name` defaults to "Goto-<target activity name>", the convention every UI-built one followed
    (shapes/goto_task.json's own note). The new activity's id is deterministic on the TARGET (like
    every other id this module mints) — unaffected by `branch_process_def_id`, which can only ever
    equal the target's own ProcessDef or raise, never redirect the id elsewhere — so re-running with
    the same target is idempotent: same id, no duplicate chain entry, no duplicate back-ref.

    Returns (new draft, new GotoTask activity id). Raises ValueError, draft entirely unmutated, when
    `target_activity_id` is not a real Activity node, that Activity has no valid `ProcessDef`
    back-reference to join, `branch_process_def_id` is given but is not a real ProcessDef node, or
    `branch_process_def_id` is given but does not match the target's own ProcessDef.
    """
    target = draft.get(target_activity_id)
    if not isinstance(target, dict) or target.get("Kind") != "Activity":
        raise ValueError(f"no Activity {target_activity_id!r} in draft to jump back to")
    target_pd_id = target.get("ProcessDef")
    if not isinstance(target_pd_id, str) or target_pd_id not in draft:
        raise ValueError(f"target activity {target_activity_id!r} has no valid ProcessDef back-ref")

    if branch_process_def_id is None:
        pd_id = target_pd_id
    else:
        branch = draft.get(branch_process_def_id)
        if not isinstance(branch, dict) or branch.get("Kind") != "ProcessDef":
            raise ValueError(f"no ProcessDef {branch_process_def_id!r} in draft")
        if branch_process_def_id != target_pd_id:
            raise ValueError(
                f"target activity {target_activity_id!r} belongs to ProcessDef {target_pd_id!r}, "
                f"not the requested branch {branch_process_def_id!r} — a GotoTask must stay within "
                f"its own branch (CLAUDE.md Workflow: 'a branch-local jump, never cross-branch')"
            )
        pd_id = branch_process_def_id

    new: Draft = copy.deepcopy(draft)
    target = new[target_activity_id]
    pd = new[pd_id]
    target_name = target.get("Name", target_activity_id)

    goto_id = _new_id("Activity", pd_id, 0, f"goto:{target_activity_id}")
    new[goto_id] = {
        "Id": goto_id, "Kind": "Activity", "NodeType": "GotoTask",
        "Name": name or f"Goto-{target_name}", "ProcessDef": pd_id,
        "CreatedAt": _now(), "Goto": target_activity_id,
    }
    if goto_id not in (target.get("Goto::Activity") or []):
        target.setdefault("Goto::Activity", []).append(goto_id)

    chain = list(pd.get("ProcessDef::Activity") or [])
    if goto_id not in chain:
        # last among the REAL activities, but BEFORE a trailing EndEvent if one is present —
        # see the correction in this function's own docstring (live-proven 2026-08-06: appending
        # strictly last, after the EndEvent too, PUTs 400).
        if chain and new.get(chain[-1], {}).get("NodeType") == "EndEvent":
            chain = [*chain[:-1], goto_id, chain[-1]]
        else:
            chain.append(goto_id)
    pd["ProcessDef::Activity"] = chain
    return new, goto_id


Matrix = dict[str, dict[str, Visibility]]        # section name -> activity id -> visibility

# The builder writes no Permission for these; the oracle has none on either. A Parallel is a
# container, SendBackToInitiator is not part of any ProcessDef::Activity chain at all, and a
# GotoTask is a no-form backward jump (it renders nothing, so it carries no per-step visibility).
NO_PERMISSION_NODETYPES = ("Parallel", "SendBackToInitiator", "GotoTask")


def _table_model_ids(draft: Draft) -> set[str]:
    """Ids of every NESTED table Model, detected two independent ways so a live read-back that
    drops one signal still resolves the table: (1) a Model that carries a host `Column` back-ref
    (CLAUDE.md > Tables: `Model{..., Column:<host>}`), and (2) any Model named in a host column's
    `Column::Model` list. Either alone is enough — the union survives Kissflow echoing back only
    one of the two on a live draft, which is exactly how the coverage check used to reject a
    table-bearing flow (host + child columns read as "outside every section")."""
    by_backref = {k for k, v in _kind(draft, "Model").items() if v.get("Column")}
    by_host = {tid for v in _kind(draft, "Column").values()
               for tid in (v.get("Column::Model") or []) if isinstance(tid, str)}
    return by_backref | by_host


@dataclass(frozen=True)
class SectionLayout:
    """One frozen fact base: everything the visibility machinery knows about a draft's
    sections and columns, resolved ONCE per draft by `section_layout`.

    Writer (`set_step_permissions`), auditor (`verify.doctor`) and preview
    (`tools.plan_step_visibility`) all consume this same object, so a change to one
    membership / no-Permission rule lands in one function instead of three copies of the
    same graph walk.

    - `section_id_of_name`: section NAME -> its Section Column id. A Section always beats a
      same-named table-host Model (the golden banner-above-a-same-named-table pattern,
      e23f8f2); a Model name is kept only as a fallback when no Section owns it.
    - `members`: unit id -> the column ids it governs. A Section maps to the columns it
      contains (a child TABLE maps to its own host column — Kissflow shows/hides the whole
      table, not its columns).
    - `no_permission_columns`: IsHidden and SequenceNumber columns — the builder writes zero
      Permissions for them (#9).
    - `table_host_columns` / `table_child_columns`: a table's host column and the field
      columns inside the table take no Permissions either (CLAUDE.md > Tables, Visibility).
    """

    section_id_of_name: dict[str, str]
    members: dict[str, tuple[str, ...]]
    no_permission_columns: frozenset[str]
    table_host_columns: frozenset[str]
    table_child_columns: frozenset[str]

    def owner_section(self, column_id: str) -> str | None:
        """The NAME of the Section directly containing `column_id`, or None when the column
        sits outside every Section (a table host's own root Row, a table child, ...). Any
        column in a Section's rows belongs to it — a Model host nested inside a Section is
        credited to that Section."""
        for name, sid in self.section_id_of_name.items():
            if column_id in self.members.get(sid, ()):
                return name
        return None


def section_layout(draft: Draft) -> SectionLayout:
    """Resolve the visibility fact base for one draft, once. Pure; O(nodes)."""
    cols = _kind(draft, "Column")
    fields = _kind(draft, "Field")

    # A section-owner name resolves ONLY to its Section node. A table-host Model column can
    # carry the SAME Name (a banner Section sitting above a same-named table, e.g. "FDE Log");
    # Section always wins regardless of iteration order; a Model name is kept only as a
    # fallback when no Section owns it.
    section_id_of_name: dict[str, str] = {}
    for cid, col in cols.items():
        name = col.get("Name")
        if not name:
            continue
        is_section = col.get("Type") == "Section"
        is_model_fallback = (col.get("Type") == "Model"
                             and name not in section_id_of_name)
        if is_section or is_model_fallback:
            section_id_of_name[name] = cid

    # a Section maps to the columns it contains; a child TABLE maps to its own host column
    members: dict[str, tuple[str, ...]] = {}
    for cid, col in cols.items():
        if col.get("Type") == "Section":
            members[cid] = tuple(
                c for rid in col.get("Column::Row") or []
                for c in (draft.get(rid) or {}).get("Row::Column") or []
            )
        elif col.get("Type") == "Model":
            members[cid] = (cid,)

    # columns the builder never permissions (CLAUDE.md > Visibility): any `IsHidden` column
    # and any SequenceNumber field's column. Property-based, not name-based, so the exclusion
    # holds on any app and any call order.
    no_permission = {cid for cid, col in cols.items() if col.get("IsHidden")}
    no_permission |= {c for f in fields.values()
                      if f.get("Type") == "SequenceNumber"
                      and isinstance(c := f.get("Column"), str)}

    # a host is `Type:"Model"` carrying `Column::Model`, sits in its OWN root-level Row
    # (never a Section), and takes NO Permissions. Detected by either signal so a read-back
    # missing one still excludes it from the section-coverage rule.
    table_hosts = {cid for cid, col in cols.items()
                   if col.get("Type") == "Model" or col.get("Column::Model")}

    # nested table Models, detected two independent ways so a live read-back that drops one
    # signal still resolves the table: (1) a Model that carries a host `Column` back-ref, and
    # (2) any Model named in a host column's `Column::Model` list.
    tables = _table_model_ids(draft)

    # field columns INSIDE a child table: they are `Type:"Field"` but belong to the nested
    # Model, not the form, so they are never step-permissioned individually.
    table_children = {c for f in fields.values()
                      if f.get("Model") in tables
                      and isinstance(c := f.get("Column"), str)}

    return SectionLayout(
        section_id_of_name=section_id_of_name,
        members=members,
        no_permission_columns=frozenset(no_permission),
        table_host_columns=frozenset(table_hosts),
        table_child_columns=frozenset(table_children),
    )


def _kind(draft: Draft, kind: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _leaf_field_columns(draft: Draft, row_ids: list[str]) -> list[str]:
    """Walk a list of Row ids and return every FIELD-type Column reachable underneath, recursing
    through any wrapper Column that isn't itself a Field or a table host (a template's Grid,
    Section -> Row -> Grid -> Row -> Field) so a field several layers deep is still found."""
    out: list[str] = []
    for rid in row_ids:
        for cid in (draft.get(rid) or {}).get("Row::Column") or []:
            col = draft.get(cid) or {}
            if col.get("Type") in ("Field", "Model"):
                out.append(cid)
            else:                                    # a wrapper column (Grid, ...) — recurse
                out.extend(_leaf_field_columns(draft, col.get("Column::Row") or []))
    return out


def current_groups(draft: Draft) -> list[tuple[str, list[str]]]:
    """The draft's CURRENT section -> [field name] layout, top-to-bottom, root-model fields only.

    Recurses through any nested wrapper Column via `_leaf_field_columns` (a template's Grid, or
    whatever the builder invents next), so a field several layers deep is still found —
    `_section_members`'s successor (`section_layout(...).members`) deliberately stays one level
    shallow (it feeds the visibility matrix, which permissions a Grid the same way it permissions
    any other column), so it is not reused here.

    Feeds `merge_groups`: seeding the FULL current layout before overlaying a caller's partial
    `groups` is what stops `regroup_into_sections` from dumping every untouched field into "Other".
    """
    model_id = _model_id(draft)
    model = draft[model_id]
    row_order = {rid: i for i, rid in enumerate(model.get("Model::Row") or [])}

    id_to_name: dict[str, str] = {}
    for node in draft.values():
        if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Model") == model_id:
            col = node.get("Column")
            if isinstance(col, str):
                id_to_name[col] = node.get("Name", "")

    sections = [(sid, v) for sid, v in _kind(draft, "Column").items() if v.get("Type") == "Section"]
    sections.sort(key=lambda sv: row_order.get(sv[1].get("Row"), len(row_order)))

    out: list[tuple[str, list[str]]] = []
    for sid, sec in sections:
        cols = _leaf_field_columns(draft, sec.get("Column::Row") or [])
        names = [id_to_name[cid] for cid in cols if cid in id_to_name]
        out.append((sec.get("Name", ""), names))
    return out


def merge_groups(draft: Draft, groups: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    """Overlay a caller's PARTIAL `groups` onto the draft's CURRENT section membership.

    `regroup_into_sections` treats `groups` as the COMPLETE layout: anything not named collapses
    into a trailing "Other" section. That is right for a caller who states the whole form, and
    silently wrong for the common "add one field to an existing section" call — every OTHER field
    the caller didn't mention would otherwise be dumped into "Other" (the template-shell regroup
    corruption this fixes). This seeds the full map from `current_groups(draft)` first, then moves
    only the fields the caller actually named into the caller's requested section; every other
    field keeps its current section untouched. A field in NO current section AND named in NO group
    still falls through to `regroup_into_sections`'s own "Other" handling.

    A section drained to zero fields purely as a side effect of this overlay is dropped from the
    result (nobody asked for a stray empty section); a section that was ALREADY an intentional
    empty banner, or one the caller named directly (even with an empty list — an explicit "no new
    fields here", or a fresh banner request), is kept.
    """
    plan: dict[str, list[str]] = {}
    order: list[str] = []
    originally_empty: set[str] = set()
    for title, names in current_groups(draft):
        plan[title] = list(names)
        order.append(title)
        if not names:
            originally_empty.add(title)

    for title, names in groups:
        if title not in plan:
            plan[title] = []
            order.append(title)
        for name in names:
            for other in plan.values():
                if name in other:
                    other.remove(name)
            plan[title].append(name)

    caller_titles = {t for t, _ in groups}
    return [(title, plan[title]) for title in order
            if plan[title] or title in originally_empty or title in caller_titles]


def _walk_workflow(draft: Draft) -> tuple[dict[str, int], dict[str, str | None]]:
    """Return (activity id -> position, activity id -> branch ProcessDef id or None).

    Position comes from the ROOT `ProcessDef::Activity` order. A Parallel's branch activities all
    take the Parallel's own index, because they happen at the same point in the flow — that shared
    index is what lets `progressive_matrix` keep sibling branches hidden from each other.
    """
    roots = [v for v in _kind(draft, "ProcessDef").values() if v.get("WorkflowType") == "Sequence"]
    if len(roots) != 1:
        raise ValueError(f"expected exactly one root ProcessDef (WorkflowType=Sequence), got {len(roots)}")

    pos: dict[str, int] = {}
    branch: dict[str, str | None] = {}
    for i, aid in enumerate(roots[0].get("ProcessDef::Activity") or []):
        pos[aid], branch[aid] = i, None
        node = draft.get(aid) or {}
        for bpd in node.get("Activity::ProcessDef") or []:
            for baid in (draft.get(bpd) or {}).get("ProcessDef::Activity") or []:
                pos[baid], branch[baid] = i, bpd
    return pos, branch


def progressive_matrix(draft: Draft, owners: dict[str, list[str]]) -> Matrix:
    """Section-by-step visibility: show a section at the step that owns it, and only there.

    `owners` maps a section NAME to the workflow step names that own it. Pure; see spec.md for the
    rule table. A section with no owner comes out ReadOnly everywhere rather than being dropped —
    silence would mean "keeps whatever default", which is exactly the bug this replaces.

    Raises ValueError on a section name or a step name in `owners` that does not resolve against
    `draft`, the same contract `field_override_matrix` already had. This used to DROP both
    silently: a mistyped section key matched no section and simply never appeared, and a mistyped
    step name matched no activity, which read as "this section has no owner" and quietly emitted
    ReadOnly-everywhere. Both fed a DESTRUCTIVE rebuild (`set_step_permissions` deletes every
    Permission first), so the caller's typo became a whole section nobody can edit, discovered two
    steps later by `verify.doctor` — a name the caller supplied that lands in no bucket at all is
    the doctrine-2 hole this closes. A section the caller deliberately leaves OUT of `owners` is
    untouched by this rule: that is the documented unowned case, not an unresolved name.
    """
    pos, branch = _walk_workflow(draft)
    acts = _kind(draft, "Activity")
    bearing = [a for a, n in acts.items() if n.get("NodeType") not in NO_PERMISSION_NODETYPES]

    orphans = [a for a in bearing if a not in pos]
    if orphans:
        raise ValueError(f"activities outside the workflow chain, cannot place them: {orphans}")

    sections = {v["Name"]: k for k, v in _kind(draft, "Column").items()
                if v.get("Type") in ("Section", "Model") and v.get("Name")}

    unknown_sections = sorted(n for n in owners if n not in sections)
    if unknown_sections:
        raise ValueError(f"owners names section(s) not on this form: {unknown_sections} — "
                         f"available: {sorted(sections)}")
    step_names = {acts[a].get("Name") for a in bearing}
    unknown_steps = sorted({s for names in owners.values() for s in (names or [])
                            if s not in step_names})
    if unknown_steps:
        raise ValueError(f"owners names step(s) not on this workflow: {unknown_steps} — "
                         f"available: {sorted(n for n in step_names if n)}")

    matrix: Matrix = {}
    for name in sections:
        owned = {a for a in bearing if acts[a].get("Name") in (owners.get(name) or [])}
        if not owned:
            matrix[name] = dict.fromkeys(bearing, Visibility.READONLY)
            continue
        first = min(pos[a] for a in owned)
        own_branches = {branch[a] for a in owned}
        row: dict[str, Visibility] = {}
        for a in bearing:
            if a in owned:
                row[a] = Visibility.EDITABLE
            elif pos[a] < first:
                row[a] = Visibility.HIDDEN
            elif pos[a] == first and branch[a] is not None and branch[a] not in own_branches:
                row[a] = Visibility.HIDDEN          # sibling branch — 4c stays hidden inside 4b
            else:
                row[a] = Visibility.READONLY
        matrix[name] = row
    return matrix


def field_override_matrix(
    draft: Draft, field_owners: dict[str, list[str]]
) -> Matrix:
    """Per-FIELD editable-step matrix, the field-level lever `progressive_matrix` cannot express
    (an app whose sections only HIDE, with editability expressed per field). `field_owners` maps a
    FIELD NAME to the workflow step names where it is Editable; every other field keeps its
    section's matrix.

    Rule (per-step, validated 0-mismatch against a reference app's 1408 field×step cells):

      - a step in the editable set  -> Editable
      - a ROOT step (branch is None): before the first editable step -> Hidden, else ReadOnly
      - a BRANCH step (branch set):
          * in a branch the field IS editable in (own branch) but not itself editable -> Hidden
          * a sibling branch of a branch-OWNED field (editable in some real branch)  -> Hidden
          * a branch step of a root-OWNED field (editable only on the root spine):
              Hidden if the field is also editable on a tail root step (past the branch block),
              else ReadOnly. A header field (Start/Use-case only) stays ReadOnly through the
              branch; a field that re-emerges after the branch is Hidden during the detour.

    Pure; raises ValueError on a STEP name that does not resolve, same contract as
    `progressive_matrix`. An unresolvable FIELD name is refused too, but one function later, by
    `set_step_permissions` ("field_matrix names a field that does not exist") — still offline and
    still before any write. It is deliberately NOT also checked here: a field column carries
    `Name: None`, so the name resolves through the Field node's own `Column` back-ref, and a
    second copy of that walk is exactly how two versions of "which fields exist" drift apart.
    A field named but with an empty editable list is ReadOnly everywhere (no sibling-branch
    hiding — there is no "own branch" to be private to); omit it instead if you want the section
    default.
    """
    pos, branch = _walk_workflow(draft)
    acts = _kind(draft, "Activity")
    bearing = [a for a, n in acts.items() if n.get("NodeType") not in NO_PERMISSION_NODETYPES]
    orphans = [a for a in bearing if a not in pos]
    if orphans:
        raise ValueError(f"activities outside the workflow chain, cannot place them: {orphans}")

    max_branch_pos = max((pos[a] for a in bearing if branch[a] is not None), default=0)
    known_steps = {acts[a].get("Name"): a for a in bearing}
    matrix: Matrix = {}
    for fname, step_names in field_owners.items():
        owned = {known_steps[s] for s in step_names if s in known_steps}
        unknown = [s for s in step_names if s not in known_steps]
        if unknown:
            raise ValueError(f"field {fname!r} owns unknown step(s): {unknown}")
        if not owned:
            matrix[fname] = dict.fromkeys(bearing, Visibility.READONLY)
            continue
        first = min(pos[a] for a in owned)
        own_branches = {branch[a] for a in owned}
        branch_owned = any(b is not None for b in own_branches)
        has_tail = any(pos[a] > max_branch_pos for a in owned)
        row: dict[str, Visibility] = {}
        for a in bearing:
            if a in owned:
                row[a] = Visibility.EDITABLE
            elif branch[a] is None:                       # root step
                row[a] = Visibility.HIDDEN if pos[a] < first else Visibility.READONLY
            elif branch[a] in own_branches:                # own branch, not editable
                row[a] = Visibility.HIDDEN
            elif branch_owned:                             # sibling branch of a branch-owned field
                row[a] = Visibility.HIDDEN
            else:                                          # branch step of a root-owned field
                row[a] = Visibility.HIDDEN if has_tail else Visibility.READONLY
        matrix[fname] = row
    return matrix


def set_step_permissions(draft: Draft, matrix: Matrix, field_matrix: Matrix | None = None) -> Draft:
    """Rebuild the per-step Permission matrix from scratch. Pure: returns a NEW draft.

    Shape and both back-references copied from the oracle (see types.Visibility). Existing
    Permission nodes are DELETED rather than merged — a leftover node would silently keep an old
    visibility, and a leftover back-reference PUTs fine (200) but makes PUBLISH fail with a bare
    MetadataError, so `_sweep_dangling` runs straight after the delete.
    """
    new: Draft = copy.deepcopy(draft)
    model_id = _model_id(new)

    for nid in [k for k, v in new.items() if isinstance(v, dict) and v.get("Kind") == "Permission"]:
        del new[nid]
    _sweep_dangling(new)

    layout = section_layout(new)   # one fact base: name resolution, membership, exclusions
    members = layout.members
    sec_id_of_name = layout.section_id_of_name
    excluded = layout.no_permission_columns
    table_hosts = layout.table_host_columns

    # field-level overrides: field NAME -> the single field column id they govern (a Field node's
    # Column; field columns themselves carry Name=None, so resolve through the Field node).
    field_col_of_name: dict[str, str] = {}
    if field_matrix:
        for f in _kind(new, "Field").values():
            fname = f.get("Name")
            cid = f.get("Column")
            if isinstance(fname, str) and isinstance(cid, str) and fname in field_matrix:
                if fname in field_col_of_name and field_col_of_name[fname] != cid:
                    raise ValueError(f"field name {fname!r} is ambiguous: two columns")
                field_col_of_name[fname] = cid
        missing = [n for n in field_matrix if n not in field_col_of_name]
        if missing:
            raise ValueError(f"field_matrix names a field that does not exist: {missing}")
    overridden_cols = set(field_col_of_name.values())
    excluded = layout.no_permission_columns
    table_hosts = layout.table_host_columns  # a table host takes no Permission (CLAUDE.md > Tables)
    banned = [n for n, c in field_col_of_name.items() if c in excluded]
    if banned:
        raise ValueError(f"field_matrix targets columns that take no Permissions "
                         f"(IsHidden or SequenceNumber): {banned}")

    covered = {c for name in matrix for c in members.get(sec_id_of_name.get(name, ""), [])}
    # A table's HOST column (Type:"Model") and the field columns INSIDE the table legitimately live
    # outside every Section — a table host sits in its own root Row, never a Section, and takes no
    # Permissions (CLAUDE.md > Tables, Visibility). Excluding them is what lets a flow have BOTH a
    # table and a step-visibility matrix; without it set_visibility and add_table were mutually
    # exclusive (a table-bearing flow rejected here as "columns outside every section").
    all_field_cols = ({k for k, v in _kind(new, "Column").items() if v.get("Type") == "Field"}
                      - layout.table_child_columns - table_hosts - excluded)
    if all_field_cols - covered:
        # a sparse matrix means those fields silently keep their default visibility -> fail loud
        raise ValueError(f"field columns outside every matrix section: {sorted(all_field_cols - covered)}")

    def _write_row(col_id: str, row: dict[str, Visibility]) -> None:
        for act_id, vis in row.items():
            pid = _new_id("Permission", model_id, 0, f"{col_id}:{act_id}")
            if pid in new:
                raise ValueError(f"permission id collision on {pid}")
            new[pid] = {"Id": pid, "Kind": "Permission", "Column": col_id,
                        "Permission": Visibility(vis).value, "Activity": act_id}
            new[col_id].setdefault("Column::Permission", []).append(pid)
            new[act_id].setdefault("Activity::Permission", []).append(pid)

    for name, row in matrix.items():
        sid = sec_id_of_name.get(name)
        if sid is None:
            raise ValueError(f"matrix names a section that does not exist: {name!r}")
        for col_id in members[sid]:
            if col_id in overridden_cols or col_id in excluded or col_id in table_hosts:
                continue            # own row in field_matrix, a no-Permission column (#9), or a
                                    # table host (Kissflow shows/hides the whole table, not its cell)
            _write_row(col_id, row)
    for fname, row in (field_matrix or {}).items():
        _write_row(field_col_of_name[fname], row)
    return new


def field_names(draft: Draft) -> set[str]:
    """Names of every existing Field node — the basis for idempotent reconcile."""
    return {
        n.get("Name", "")
        for n in draft.values()
        if isinstance(n, dict) and n.get("Kind") == "Field"
    }


def parse_draft(draft: Draft) -> list[ParsedField]:
    """Extract every Field node from the graph."""
    out: list[ParsedField] = []
    for node in draft.values():
        if isinstance(node, dict) and node.get("Kind") == "Field":
            out.append(
                ParsedField(
                    field_id=node["Id"],
                    name=node.get("Name", ""),
                    type=FieldType(node["Type"]),  # raises on a type outside the enum (data integrity)
                    required=bool(node.get("Required", False)),
                    column_id=node.get("Column"),
                )
            )
    return out


def apply_changes(draft: Draft, changes: list[FieldSpec]) -> Draft:
    """Return a NEW draft graph with the field changes applied. Pure: input is not mutated.

    MVP: only ADD new fields (field_id is None). Edit/delete land in a later wave.
    Invalid field types are rejected BEFORE any graph mutation.
    """
    # 1) validate everything first (fail loud, before touching the graph), and SKIP any
    #    field whose name already exists (idempotent reconcile — never duplicate).
    existing = field_names(draft)
    validated: list[tuple[FieldSpec, FieldType]] = []
    for spec in changes:
        ft = FieldType(spec.type)  # ValueError if unknown -> rejected up front
        if spec.field_id is not None:
            raise NotImplementedError("field edit not in MVP; only create (field_id=None)")
        if spec.name in existing:
            continue  # already present -> re-applying the manifest never duplicates
        # A Select's OPTIONS live in a SEPARATE list flow, named by `ReferredList` — exactly the
        # way a User field's directory source lives in a sibling QueryDefinition below. Minting one
        # with no list is a dropdown bound to nothing: it PUTs 200 and publish then dies 500
        # MetadataError with zero diagnostic content (2026-08-19 diagnosis). Refuse at compile and
        # name the fix (ADR-0004) rather than write a field that cannot publish; the User branch
        # below auto-repairs its own version of this defect, and minting a bare Select silently
        # twenty lines apart was the inconsistency that let it through. The predicate is shared
        # with `add_table`'s table-child columns (`unbound_select`) — one rule, both mint paths.
        if unbound_select(ft, spec.referred_list):
            raise ValueError(
                f"field {spec.name!r} is Type Select with no referred_list — a Select bound to no "
                f"list publishes 500 MetadataError with zero diagnostics; create the list with "
                f"forge_create_list and pass referred_list=<list id> (CLAUDE.md ReferredList #13)"
            )
        validated.append((spec, ft))

    new: Draft = copy.deepcopy(draft)  # ponytail: deepcopy is fine at builder sizes (~hundreds of nodes)
    model_id = _model_id(new)
    model = new[model_id]
    _ensure_appearance(new, model_id)  # without it the builder page renders "There was an error"

    for i, (spec, ft) in enumerate(validated):
        # id prefix is capitalised to match every node Kissflow itself writes (Field_/Column_/Row_)
        fid = _new_id("Field", model_id, i, spec.name)
        col_id = _new_id("Column", model_id, i, spec.name)
        row_id, start, end = _alloc_slot(new, model_id, i)

        new[col_id] = {
            "Id": col_id, "Kind": "Column", "Type": "Field",
            "Start": start, "End": end, "Row": row_id, "Column::Field": [fid],
        }
        new[row_id].setdefault("Row::Column", []).append(col_id)

        # `Model` is the field's back-reference to its model. EVERY field Kissflow writes carries it;
        # without it the API still accepts and publishes the flow, but the builder fails to render.
        field_node: dict[str, Any] = {
            "Id": fid, "Kind": "Field", "Type": ft.value, "CreatedAt": _now(),
            "Model": model_id, "Name": spec.name, "Column": col_id,
            "Required": bool(spec.required),
        }
        field_node.update(_TYPE_DEFAULTS.get(ft.value, {}))
        if spec.referred_list is not None:
            field_node["ReferredList"] = spec.referred_list
        if spec.options:
            field_node.update(spec.options)  # opt-in per-type keys, written verbatim
        new[fid] = field_node

        # A User field needs a sibling QueryDefinition or the whole batch fails to PUBLISH
        # (KISSFLOW_ERROR_04211 — a BARE Field{Type:"User"} is the blocker, CLAUDE.md #59 /
        # shapes/field_user_reference.json). LHSModel is "User" (account directory) by default;
        # override to "_employee" (or another live source) via options["LHSModel"] — it belongs on
        # the QueryDefinition, so it must NOT stay on the Field node.
        if ft is FieldType.USER:
            lhs = field_node.pop("LHSModel", "User")
            qid = _new_id("QueryDefinition", model_id, i, spec.name)
            new[qid] = {"Id": qid, "Kind": "QueryDefinition", "Field": fid,
                        "FlowType": "User", "LHSModel": lhs, "LookupField": []}
            field_node["Field::QueryDefinition"] = [qid]

        model.setdefault("Model::Field", []).append(fid)

    return new
