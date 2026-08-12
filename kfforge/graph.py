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
import re
from datetime import UTC, datetime
from typing import Any

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

    # drop the old scaffolding; Field and Column nodes are deliberately preserved
    for nid in [k for k, v in new.items()
                if isinstance(v, dict) and (v.get("Kind") == "Row"
                                            or (v.get("Kind") == "Column" and v.get("Type") == "Section"))]:
        if new[nid].get("Kind") == "Row" and new[nid].get("Button"):
            continue  # Button::Row is not part of the field layout
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

        for i, fname in enumerate(names):
            if i % per_row == 0:
                row = _new_id("Row", model_id, 3000 + s_i * 100 + i, title)
                new[row] = {"Id": row, "Kind": "Row", "Column": sec, "Row::Column": []}
                new[sec]["Column::Row"].append(row)
            row = new[sec]["Column::Row"][-1]
            col_id = col_of[fname]
            slot = len(new[row]["Row::Column"])
            new[col_id].update({"Row": row, "Start": slot * FIELD_SPAN,
                                "End": (slot + 1) * FIELD_SPAN})
            new[row]["Row::Column"].append(col_id)

    model["Model::Row"] = top_rows
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
    are left in place after the rebuilt rows (trailing row), so nothing is ever dropped.

    Pure: returns a new draft.
    """
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

        # which columns already live in this section? keep their ids so we can spot leftovers
        before_cols: set[str] = set()
        for rid in sec.get("Column::Row") or []:
            before_cols.update((new.get(rid) or {}).get("Row::Column") or [])
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
                new[cid].update({"Row": rid, "Start": start, "End": end})
                new[rid]["Row::Column"].append(cid)
                placed.add(cid)
            new_rows.append(rid)

        # any column that was in this section but not named in the layout goes in a trailing row,
        # so a partial layout spec never silently drops a field off the form.
        leftover = [c for c in before_cols if c not in placed]
        if leftover:
            rid = _new_id("Row", sid, 5900, title)
            new[rid] = {"Id": rid, "Kind": "Row", "Column": sid, "Row::Column": []}
            start = 0
            for j, cid in enumerate(leftover):
                end = ROW_UNITS if j == len(leftover) - 1 else start + FIELD_SPAN
                new[cid].update({"Row": rid, "Start": start, "End": end})
                new[rid]["Row::Column"].append(cid)
                start = end
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
    width_of = {**FIELD_WIDTH, **(widths or {})}

    field_of_col = {v["Column"]: v for v in new.values()
                    if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Column")}
    sections = {k: v for k, v in _kind(new, "Column").items() if v.get("Type") == "Section"}

    for sid, sec in sections.items():
        ordered = [c for r in sec.get("Column::Row") or []
                   for c in (new.get(r) or {}).get("Row::Column") or []]
        for rid in sec.get("Column::Row") or []:     # drop the old rows, keep the columns
            new.pop(rid, None)

        rows: list[list[tuple[str, int]]] = []
        used = 0
        for col in ordered:
            ftype = str(field_of_col.get(col, {}).get("Type", ""))
            w = min(width_of.get(ftype, DEFAULT_WIDTH), ROW_UNITS)
            if not rows or used + w > ROW_UNITS:
                rows.append([])
                used = 0
            rows[-1].append((col, w))
            used += w

        row_ids: list[str] = []
        for i, row in enumerate(rows):
            rid = _new_id("Row", sid, 4000 + i, sec.get("Name", ""))
            new[rid] = {"Id": rid, "Kind": "Row", "Column": sid, "Row::Column": [c for c, _ in row]}
            start = 0
            for j, (col, w) in enumerate(row):
                # stretch the last column to the row edge, so a short tail never leaves a ragged
                # gap (a 2 + 3 row would otherwise end at 5 with one dead unit)
                end = ROW_UNITS if j == len(row) - 1 else start + w
                new[col].update({"Row": rid, "Start": start, "End": end})
                start = end
            row_ids.append(rid)
        sec["Column::Row"] = row_ids

        if section_descriptions and sec.get("Name") in section_descriptions:
            sec["Description"] = section_descriptions[sec["Name"]]

    if step_descriptions:
        for act in _kind(new, "Activity").values():
            if act.get("Name") in step_descriptions:
                act["Description"] = step_descriptions[act["Name"]]
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


def delete_nodes(draft: Draft, fields: tuple[str, ...] = (), tables: tuple[str, ...] = ()) -> Draft:
    """Delete form fields and/or child tables by NAME, with every back-reference swept. Pure.

    Deleting a Field means deleting its Column and every Permission that targets that Column.
    Deleting a table means the whole cluster: host Column, host Row, the nested Model, its schema
    Row, and every child Column/Field. A surviving list entry pointing at a deleted node PUTs fine
    (200) but makes PUBLISH fail with a bare MetadataError, so the sweep is not optional.

    Unknown names raise rather than silently doing nothing — a typo must not read as success.
    """
    new: Draft = copy.deepcopy(draft)
    doomed: set[str] = set()

    # NAMES ARE NOT UNIQUE — a form and its child tables all had a field called "Untitled field",
    # and a name->id dict silently kept only the last, so a delete quietly hit the wrong one.
    # Match every field with the name, and accept a raw node id to disambiguate.
    for name in fields:
        hits = [k for k, v in _kind(new, "Field").items()
                if v.get("Name") == name or k == name]
        if not hits:
            raise ValueError(f"no field named {name!r}")
        for fid in hits:
            doomed.add(fid)
            col = new[fid].get("Column")
            if isinstance(col, str):
                doomed.add(col)

    host_by_name = {v["Name"]: k for k, v in _kind(new, "Column").items()
                    if v.get("Type") == "Model" and v.get("Name")}
    for name in tables:
        host = host_by_name.get(name)
        if host is None:
            raise ValueError(f"no table named {name!r}")
        doomed.add(host)
        if isinstance(row := new[host].get("Row"), str):
            doomed.add(row)
        for tid in new[host].get("Column::Model") or []:
            doomed.add(tid)
            table = new.get(tid) or {}
            doomed.update(table.get("Model::Row") or [])
            for cfid in table.get("Model::Field") or []:
                doomed.add(cfid)
                if isinstance(c := (new.get(cfid) or {}).get("Column"), str):
                    doomed.add(c)

    # every Permission aimed at a doomed Column goes with it
    doomed |= {k for k, v in _kind(new, "Permission").items() if v.get("Column") in doomed}
    # ...and every Event on a doomed Field
    doomed |= {k for k, v in _kind(new, "Event").items() if v.get("Field") in doomed}

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
    """
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
    for i, col in enumerate(columns):
        col_name = col[0]
        col_type = col[1]
        col_opts = col[2] if len(col) > 2 else None
        ft = FieldType(col_type) if not isinstance(col_type, FieldType) else col_type
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
) -> Draft:
    """Attach a per-field validation rule. Pure. Idempotent on (field_name, operator, value).

    Kissflow has no formula type; a per-field validation is a flat Condition tree (captured from a
    UI-built oracle, CLAUDE.md F7), NOT an Expression/Node AST:

        Field --FieldValidation::Criteria--> Criteria{FieldValidation:<fid>, Criteria::Condition:[...]}
          Condition{Operator, HasArguments:true, Criteria:<cid>, RHSType:"Value", RHSValue:<literal>}

    One Criteria per field (the builder writes one); each rule is one Condition under it. A second
    rule on the same field appends a Condition to the existing Criteria. `operator` is e.g.
    "CONTAINS" / "MAX_LENGTH"; `value` is the literal (a string); `rhs_type` defaults to "Value".
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
    new[cond_id] = {"Id": cond_id, "Kind": "Condition", "Operator": operator, "HasArguments": True,
                    "Criteria": cid, "RHSType": rhs_type, "RHSValue": value}
    new[cid]["Criteria::Condition"] = (new[cid].get("Criteria::Condition") or []) + [cond_id]
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


_REF_KINDS = ("Activity_", "ProcessDef_", "Resource_", "Permission_")


def _sweep_dangling(draft: Draft) -> None:
    """Drop every reference to a workflow node that no longer exists. Mutates in place.

    Columns keep a `Column::Permission` back-reference list. Leaving one pointing at a deleted
    Permission still PUTs fine (200) but makes PUBLISH fail with a bare MetadataError.

    This sweeps by "target is absent", NOT "target was deleted by me" — a draft can already carry
    orphans from an earlier partial write, and those must go too.
    """
    for node in draft.values():
        if not isinstance(node, dict):
            continue
        for key, val in list(node.items()):
            if key == "Id" or not isinstance(val, list):
                continue
            kept = [x for x in val
                    if not (isinstance(x, str) and x.startswith(_REF_KINDS) and x not in draft)]
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


def _kind(draft: Draft, kind: str) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in draft.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _no_permission_columns(draft: Draft) -> set[str]:
    """Columns the builder never permissions (CLAUDE.md > Visibility): any `IsHidden` column
    (a hidden column has no per-step visibility to set) and any SequenceNumber field's column.
    Property-based, not name-based, so the exclusion holds on any app and any call order."""
    hidden = {k for k, v in _kind(draft, "Column").items() if v.get("IsHidden")}
    seq = {c for f in _kind(draft, "Field").values()
           if f.get("Type") == "SequenceNumber" and isinstance(c := f.get("Column"), str)}
    return hidden | seq


def _table_child_columns(draft: Draft) -> set[str]:
    """Columns that live INSIDE a child table. They are `Type:"Field"` but belong to the nested
    Model, not the form, so they are never step-permissioned individually — the table as a whole is."""
    tables = {k for k, v in _kind(draft, "Model").items() if v.get("Column")}
    return {c for f in _kind(draft, "Field").values()
            if f.get("Model") in tables and isinstance(c := f.get("Column"), str)}


def _section_members(draft: Draft) -> dict[str, list[str]]:
    """Visibility unit id -> the column ids it governs.

    A Section maps to the field columns it contains. A child TABLE maps to itself: its host column
    (`Type:"Model"`) is one unit, because Kissflow shows or hides the whole table, not its columns.
    """
    out: dict[str, list[str]] = {}
    for sid, sec in _kind(draft, "Column").items():
        if sec.get("Type") == "Section":
            out[sid] = [cid
                        for rid in sec.get("Column::Row") or []
                        for cid in (draft.get(rid) or {}).get("Row::Column") or []]
        elif sec.get("Type") == "Model":
            out[sid] = [sid]
    return out


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
    """
    pos, branch = _walk_workflow(draft)
    acts = _kind(draft, "Activity")
    bearing = [a for a, n in acts.items() if n.get("NodeType") not in NO_PERMISSION_NODETYPES]

    orphans = [a for a in bearing if a not in pos]
    if orphans:
        raise ValueError(f"activities outside the workflow chain, cannot place them: {orphans}")

    sections = {v["Name"]: k for k, v in _kind(draft, "Column").items()
                if v.get("Type") in ("Section", "Model") and v.get("Name")}
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

    Pure; raises ValueError on a field/step name that does not resolve, same contract as
    `progressive_matrix`. A field named but with an empty editable list is ReadOnly everywhere
    (no sibling-branch hiding — there is no "own branch" to be private to); omit it instead if
    you want the section default.
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

    members = _section_members(new)
    sec_id_of_name = {v["Name"]: k for k, v in _kind(new, "Column").items()
                      if v.get("Type") in ("Section", "Model") and v.get("Name")}

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
    excluded = _no_permission_columns(new)
    banned = [n for n, c in field_col_of_name.items() if c in excluded]
    if banned:
        raise ValueError(f"field_matrix targets columns that take no Permissions "
                         f"(IsHidden or SequenceNumber): {banned}")

    covered = {c for name in matrix for c in members.get(sec_id_of_name.get(name, ""), [])}
    all_field_cols = ({k for k, v in _kind(new, "Column").items() if v.get("Type") == "Field"}
                      - _table_child_columns(new) - excluded)
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
            if col_id in overridden_cols or col_id in excluded:
                continue            # own row in field_matrix, or a no-Permission column (#9)
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

        model.setdefault("Model::Field", []).append(fid)

    return new
