"""Generic health check for a flow's draft graph: every reference that would break the form at
load, leave a branch or loop silently misconfigured, or leave a section nobody can ever edit.

Pure and offline: no network, no Kissflow calls, no assumptions baked in about any ONE app's
fields, lists, or workflow names. Every piece of app-specific knowledge a rule needs (which list
backs a Select field, what its legal values are) is supplied by the CALLER through
`list_options`; this module never hardcodes an app's data. Reports; never mutates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .graph import NO_PERMISSION_NODETYPES, ROW_UNITS, section_layout

Draft = dict[str, Any]

# Prefixes Kissflow's own builder stamps on every node id IT writes (Field_, Column_, ...). A
# hand-named / custom-slug field id (e.g. an auto-number field a builder user named directly)
# carries none of these, so a script referencing one is indistinguishable from ordinary prose —
# see `unvalidatable_scripts` below, which exists precisely because this list can never be
# complete proof that a script's references are all accounted for.
PLATFORM_ID_PREFIXES: tuple[str, ...] = (
    "Field_", "Column_", "Row_", "Model_", "Activity_", "Event_",
    "ProcessDef_", "Resource_", "Permission_", "Appearance_", "Style_",
)
_PLATFORM_REF_RE = re.compile(
    r"\b((?:" + "|".join(re.escape(p) for p in PLATFORM_ID_PREFIXES) + r")\w+)\b"
)

# Node types that render no form of their own, so the builder writes zero Permission nodes for
# them — platform semantics, not knowledge of any one app. GotoTask is a backward-jump edge node;
# Parallel and SendBackToInitiator are routing containers. None of the three ever carries a
# Permission, so none of the three belongs in a permission-matrix completeness count.
ROUTING_NODE_TYPES: tuple[str, ...] = (*NO_PERMISSION_NODETYPES, "GotoTask")

# Field `Type` strings whose OPTIONS live OUTSIDE the node, in a separate list flow named by
# `ReferredList`. Every capture in this family carries the key: shapes/field_select.json,
# field_multiselect.json, field_radio.json (a Radio is Type:"Select" plus Widget:"Radio", so
# "Select" already covers it — never branch on `Widget`), field_checkbox.json (its own Type, NOT
# Select+Widget, despite the name), field_checklist.json. A member of this family with no
# `ReferredList` is a dropdown bound to nothing.
#
# The set is the captured family and NOTHING else — never inferred from a field's NAME, and never
# widened to `Text`, which CLAUDE.md documents as a legitimate deciding-field type for a branch
# condition. A `Boolean` is a toggle, not a pick-from-a-list (shapes/field_boolean.json).
LIST_BACKED_FIELD_TYPES: frozenset[str] = frozenset({
    "Select", "Multiselect", "Checkbox", "Checklist",
})

# Kind -> the SCALAR keys on that kind whose value is a reference to another node in the SAME
# draft. Harvested empirically from every shapes/*.json capture plus a live 329-node draft; an
# explicit allowlist, never an "id-shaped string" heuristic, because the graph is full of
# id-shaped scalars that resolve to nothing BY DESIGN: `Activity.NodeType` is literally
# "SendBackToInitiator", `Resource.Value` is an account AppRole id, `Field.ReferredList` is a
# separate LIST FLOW's id, `Model._application_id` an app id, `QueryDefinition.LHSModel` a
# dataset name. A heuristic flags every one of them on a perfectly healthy flow.
#
# `Property.Value` is deliberately absent: rule 3b already owns it, and only rule 3b knows the
# stamp is the one with Name == "Step".
_SCALAR_REF_KEYS: dict[str, tuple[str, ...]] = {
    "Model":           ("RootProcessDef", "Column", "Model"),
    "Activity":        ("ProcessDef", "Goto", "BaseMetadata"),
    "ProcessDef":      ("Model", "Activity"),
    "Resource":        ("Activity",),
    "Permission":      ("Activity", "Column"),
    "Column":          ("Row", "Initiator"),
    "Row":             ("Model", "Column", "Button"),
    "Field":           ("Model", "Column"),
    "Appearance":      ("Model", "Column"),
    "Style":           ("Appearance",),
    "Expression":      ("Activity", "ProcessDef", "Property", "Field"),
    "Node":            ("Field", "Node", "Expression"),
    "Property":        ("Field",),
    "Event":           ("Field",),
    "QueryDefinition": ("Field",),
    "Criteria":        ("FieldValidation", "ColumnVisibility", "Container"),
    "Condition":       ("Criteria", "LHSOwnField"),
}

# The literal a de-identified template shape used to ship inside a Field's user-facing `Name`.
_TODO_MARKER = "TODO:"


@dataclass(frozen=True)
class DoctorReport:
    """Every check this module runs lands in exactly one bucket, never silently: a concrete
    `problems` sentence, a per-rule `checked` count of units examined, a branch literal recorded
    in `unvalidated` for lack of an options map, or a script folded into `unvalidatable_scripts`
    because its references can never be fully proven.
    """
    problems: tuple[str, ...]
    checked: dict[str, int]
    unvalidated: tuple[str, ...]
    unvalidatable_scripts: int

    def ok(self) -> bool:
        return not self.problems


def _nodes(draft: Draft) -> dict[str, Any]:
    return {k: v for k, v in draft.items() if isinstance(v, dict)}


def doctor(
    draft: Draft,
    *,
    list_options: dict[str, list[str]] | None = None,
    visibility_role_claims: tuple[str, ...] | list[str] = (),
) -> DoctorReport:
    """Audit one flow's draft graph offline. Read-only: reports, never mutates `draft`.

    `list_options` maps a Kissflow LIST id (the value of a Select field's `ReferredList`) to its
    live legal option values. A branch's literal is checked against real options ONLY when its
    sibling comparison is against a Select field whose list id is a key of this map; every other
    literal is recorded in `unvalidated` — never silently accepted, never silently flagged.

    `visibility_role_claims` carries the SPEC's role-scoped visibility claims (one human-readable
    sentence each), supplied by the caller because the graph itself can never hold one — a
    Permission node is (column, step), never (column, role), so a role-scoped claim is
    API-impossible and each one FAILs the audit outright with a stated reason (#6, ADR-0004:
    refuse, never best-effort). Compile threads these from `VisibilityEntry.role` into the plan's
    doctor op; a caller with no spec in hand just leaves it empty.
    """
    root = draft.get("Root")
    if not isinstance(root, str) or root not in draft:
        raise ValueError("draft has no Root key — not a flow draft?")

    N = _nodes(draft)
    list_options = list_options or {}
    problems: list[str] = []
    unvalidated: list[str] = []
    checked: dict[str, int] = {}
    unvalidatable_scripts = 0
    layout = section_layout(draft)   # the shared fact base rules 4/5 read (membership + exclusions)

    # 0. role-scoped visibility claims  <- API-impossible, refused here, never built best-effort
    checked["role_scoped_visibility_claims"] = len(visibility_role_claims)
    for claim in visibility_role_claims:
        problems.append(
            f"{claim}: role-scoped visibility is API-impossible; restructure to step-scoped "
            f"(coverage row role-scoped-visibility, #6)"
        )

    # 1. event scripts pointing at a node that no longer exists  <- breaks the form at load
    events = [v for v in N.values() if v.get("Kind") == "Event"]
    checked["events"] = len(events)
    for e in events:
        owner = N.get(e.get("Field"), {}).get("Name", e.get("Field"))
        script = e.get("Script") or ""
        if script:
            # A reference by custom-slug id (no platform prefix) reads exactly like prose, so no
            # regex can prove this script's references are ALL accounted for — only that the
            # platform-prefixed ones it contains are valid. Count the residual uncertainty.
            unvalidatable_scripts += 1
        for ref in set(_PLATFORM_REF_RE.findall(script)):
            if ref not in draft:
                problems.append(f"event on {owner!r} writes to missing field {ref}")
        if e.get("Field") not in draft:
            problems.append(f"event {e['Id']} is attached to a missing field")

    # 2. branch conditions whose literal matches no real list option  <- branch never fires
    #    An Expression may instead hang off a Property (used for a computed value elsewhere on
    #    the form) rather than a ProcessDef. Only the ones bound to a ProcessDef are branch
    #    conditions — filter on that before treating an Expression as routing.
    branch_exprs = [v for v in N.values() if v.get("Kind") == "Expression" and v.get("ProcessDef")]
    literals_checked = 0
    for x in branch_exprs:
        branch = N.get(x.get("ProcessDef"), {}).get("Name")
        for root_id in x.get("Expression::Node") or []:
            children = [(cid, N.get(cid) or {})
                        for cid in (N.get(root_id) or {}).get("Node::Node") or []]
            # the sibling this literal is compared against — its Select list is what makes the
            # literal provable at all
            field_sibling = next((n for _, n in children if n.get("Type") == "Field"), None)
            for _cid, n in children:
                if n.get("Type") == "Field" and n.get("Field") not in draft:
                    problems.append(f"branch {branch!r} references missing field {n.get('Field')}")
                    continue
                if n.get("Type") != "Static":
                    continue
                literals_checked += 1
                value = n.get("Value")
                options: list[str] | None = None
                if field_sibling is not None:
                    fnode = N.get(field_sibling.get("Field")) or {}
                    if fnode.get("Type") == "Select":
                        options = list_options.get(fnode.get("ReferredList"))
                if options is None:
                    unvalidated.append(
                        f"branch {branch!r} literal {value!r} not validated "
                        f"(no list options given for its field)")
                elif value not in options:
                    problems.append(f"branch {branch!r} tests {value!r}, not in {options}")
    checked["branch_literals"] = literals_checked

    # 2b. GotoTask loops  <- a Goto with no condition is an unconditional backward jump
    gotos = [v for v in N.values() if v.get("NodeType") == "GotoTask"]
    checked["gotos"] = len(gotos)
    for g in gotos:
        name = g.get("Name")
        target = N.get(g.get("Goto"))
        if not target:
            problems.append(f"goto {name!r} jumps to missing activity {g.get('Goto')}")
        elif target.get("ProcessDef") != g.get("ProcessDef"):
            problems.append(f"goto {name!r} jumps out of its own branch, to {target.get('Name')!r}")
        elif g["Id"] not in (target.get("Goto::Activity") or []):
            problems.append(f"goto {name!r} missing the Goto::Activity back-ref on its target")
        exprs = g.get("Activity::Expression") or []
        if not exprs:
            problems.append(f"goto {name!r} has NO condition — it loops forever")
        for xid in exprs:
            for root_id in (N.get(xid) or {}).get("Expression::Node") or []:
                for cid in (N.get(root_id) or {}).get("Node::Node") or []:
                    n = N.get(cid) or {}
                    if n.get("Type") != "Field":
                        continue
                    if n["Field"] not in draft:
                        problems.append(f"goto {name!r} tests missing field {n['Field']}")
                        continue
                    # a gate the item can leave BLANK is a gate that silently decides the loop
                    gate = N[n["Field"]]
                    if gate.get("Type") == "Select" and not gate.get("Required"):
                        problems.append(
                            f"goto {name!r} tests optional Select {gate.get('Name')!r} — blank "
                            f"never equals the literal, so the loop is skipped, not entered")

    # 3. dangling list references anywhere  <- PUTs fine, fails PUBLISH
    dangling_checked = 0
    for nid, node in N.items():
        for key, val in node.items():
            if not (isinstance(val, list) and "::" in key):
                continue
            for ref in val:
                if not isinstance(ref, str):
                    continue
                dangling_checked += 1
                if ref not in draft:
                    problems.append(f"{nid}.{key} -> missing {ref}")
    checked["dangling_refs"] = dangling_checked

    # 3b. a Step-stamp Property pointing at a deleted Activity — a SCALAR reference the list
    # sweep above never visits. THE publish-500 condition (#18, isolated live 2026-08-12 by
    # subsystem bisect on a flow that was doctor-clean while 500ing deterministically): PUTs
    # fine, publish dies MetadataError with zero diagnostic content.
    step_stamps = 0
    for nid, node in N.items():
        if node.get("Kind") == "Property" and node.get("Name") == "Step":
            step_stamps += 1
            tgt = node.get("Value")
            if isinstance(tgt, str) and (draft.get(tgt) or {}).get("Kind") != "Activity":
                problems.append(
                    f"sequence Step stamp {nid} -> missing activity {tgt} (publish will 500 "
                    f"MetadataError — repoint it or rebuild via build_workflow, which now "
                    f"repoints by name)")
    checked["step_stamps"] = step_stamps

    # 3c. EVERY other dangling SCALAR reference — the whole class rule 3b guards one instance of.
    # Rule 3 sweeps `::` LIST refs only (`isinstance(val, list) and "::" in key`), so an owner
    # back-ref written as a bare string was never visited by anything: PUTs 200, publish dies 500
    # MetadataError with zero diagnostic content, exactly like #18.
    #
    # REPORT-ONLY, deliberately, and NOT mirrored into `graph._sweep_dangling`: that sweep DELETES,
    # and deleting a dangling `Field.Column` or `Permission.Activity` would strand the node rather
    # than repair it. The list sweep stays list-only; the scalar surface is named here instead.
    scalar_refs = 0
    for nid, node in N.items():
        for key in _SCALAR_REF_KEYS.get(node.get("Kind"), ()):
            ref = node.get(key)
            if not isinstance(ref, str) or not ref:
                continue
            scalar_refs += 1
            if ref not in draft:
                problems.append(
                    f"{nid}.{key} -> missing {ref} (scalar reference — the list-only sweep never "
                    f"visits it; PUT 200s, publish dies 500 MetadataError with zero diagnostics)")
    checked["scalar_refs"] = scalar_refs

    # 4. a section nobody can ever edit, and Required fields nobody can ever fill
    malformed_permissions: list[str] = []
    susp = {v.get("Name") for v in N.values() if v.get("Kind") == "Activity" and v.get("IsSuspended")}
    editable: dict[str, set[str]] = {}
    for pm in N.values():
        if pm.get("Kind") != "Permission" or pm.get("Permission") != "Editable":
            continue
        step = N.get(pm.get("Activity"), {}).get("Name")
        if step in susp:                       # a suspended step never runs
            continue
        # A Permission missing `Column`/`Activity` is malformed, not absent — report it and skip,
        # never subscript it. doctor runs on flows this engine did NOT build (SKILL.md: run it
        # after every edit), so a UI- or copilot-built node with a key we assume is present used
        # to escape `forge_doctor` as a bare KeyError, across the tool boundary, as an EXCEPTION
        # rather than as data. Doctrine 7: this function reports, it never raises.
        col_id = pm.get("Column")
        if not isinstance(col_id, str) or not isinstance(pm.get("Activity"), str):
            malformed_permissions.append(pm.get("Id", "<no Id>"))
            continue
        col = N.get(col_id, {})
        # the column's owning Section (layout.owner_section), else its own name — the same
        # attribution the old per-column walk computed, sourced from the shared fact base now
        keys = {layout.owner_section(col_id) or col.get("Name", "?")}
        # A table host (Type:"Model") NESTED inside a section is reachable under two different
        # names: the enclosing section's (via owner_section) and its own. A table sitting at the
        # top level has no enclosing section, so the two names coincide there and the gap stays
        # invisible until a table is built INSIDE a section. Credit the host's own name too, or a
        # section-nested table false-flags as "never editable".
        if col.get("Type") == "Model" and col.get("Name"):
            keys.add(col["Name"])
        for key in keys:
            editable.setdefault(key, set()).add(step)

    sections_checked = 0
    for sv in N.values():
        if sv.get("Type") not in ("Section", "Model") or not sv.get("Name"):
            continue
        sections_checked += 1
        # a Section with no member columns is a pure text banner (a heading with nothing under
        # it): nothing in it can be edited, so "never editable" is its correct, healthy state
        if sv.get("Type") == "Section" and not sv.get("Column::Row"):
            continue
        if not editable.get(sv["Name"]):
            problems.append(f"section {sv['Name']!r} is never editable at any live step")
    checked["sections"] = sections_checked

    required_checked = 0
    for f in [v for v in N.values() if v.get("Kind") == "Field"
              and v.get("Model") == root and v.get("Required")]:
        required_checked += 1
        if not editable.get(layout.owner_section(f.get("Column")) or "?"):
            problems.append(
                f"field {f['Name']!r} is Required but never editable — that step cannot be submitted")
    checked["required_fields"] = required_checked

    # 5. sparse permission matrix  <- fields silently keep a default visibility
    # A hidden or SequenceNumber column has no per-step visibility to set — the builder writes
    # zero Permissions for a system-filled column, which is never shown on a form (#9). A table
    # HOST column (Type:"Model") likewise takes NO Permission — Kissflow shows/hides the whole
    # table, not its host cell (CLAUDE.md > Tables, Visibility). `set_step_permissions` skips hosts
    # by design, so counting them here made a table-bearing flow's matrix read "sparse" by exactly
    # one host-column x every step, even when every real field was covered — must exclude them too.
    units = ({k for k, v in N.items() if v.get("Kind") == "Column" and v.get("Type") == "Field"}
             - layout.table_child_columns - layout.no_permission_columns)
    acts = [k for k, v in N.items() if v.get("Kind") == "Activity"
            and v.get("NodeType") not in ROUTING_NODE_TYPES]
    have = {(c, a) for p in N.values() if p.get("Kind") == "Permission"
            and isinstance(c := p.get("Column"), str) and isinstance(a := p.get("Activity"), str)}
    checked["permission_pairs"] = len(units) * len(acts)
    checked["malformed_permissions"] = len(malformed_permissions)
    if malformed_permissions:
        problems.append(
            f"{len(malformed_permissions)} Permission node(s) missing a Column/Activity "
            f"reference: {', '.join(sorted(malformed_permissions)[:5])}"
            + (" ..." if len(malformed_permissions) > 5 else "")
            + " — the builder writes both on every Permission; a node without them gates nothing")
    gaps = len({(u, a) for u in units for a in acts} - have)
    if gaps:
        problems.append(f"permission matrix is sparse: {gaps} (unit, step) pairs unset")

    # 6. a UserTask with no assignee  <- submit 500s with a generic, non-diagnostic processError
    # (CLAUDE.md Members first: "membership alone is not enough — the step also needs a real
    # ASSIGNEE"). Only UserTask takes an assignee — a StartEvent is gated by InitiateItems
    # membership, an EndEvent is terminal, neither carries a Resource. A suspended step is walked
    # past at runtime, so its missing assignee never bites; skip it. The assignee is a Resource with
    # a real Value on the step's Activity::Resource.
    real_steps = [(k, v) for k, v in N.items() if v.get("Kind") == "Activity"
                  and v.get("NodeType") == "UserTask" and not v.get("IsSuspended")]
    checked["step_assignees"] = len(real_steps)
    for _aid, v in real_steps:
        res_ids = v.get("Activity::Resource") or []
        # Must be an AppRole assignee with a real Value. A ValueType:"User" Resource publishes but
        # is SILENTLY IGNORED at runtime (CLAUDE.md Members first: "use AppRole for assignees, not
        # User") — it reads as assigned but still 500s on submit, the exact class this rule catches.
        if not any((N.get(r) or {}).get("Value")
                   and (N.get(r) or {}).get("ValueType") == "AppRole" for r in res_ids):
            problems.append(
                f"step {v.get('Name')!r} has no AppRole assignee — submit will 500 (CLAUDE.md "
                f"Members first: wire a Resource with ValueType 'AppRole' on every step)")

    # 7. a bare User field with no sibling QueryDefinition  <- blocks PUBLISH outright
    # (KISSFLOW_ERROR_04211, CLAUDE.md #59 / shapes/field_user_reference.json). apply_changes mints
    # the sibling for engine-built User fields, but a template-cloned or hand-built one may lack it.
    user_fields = [v for v in N.values() if v.get("Kind") == "Field" and v.get("Type") == "User"]
    checked["user_fields"] = len(user_fields)
    for f in user_fields:
        qids = f.get("Field::QueryDefinition") or []
        if not any((N.get(q) or {}).get("Kind") == "QueryDefinition" for q in qids):
            problems.append(
                f"User field {f.get('Name')!r} has no QueryDefinition sibling — publish will fail "
                f"(KISSFLOW_ERROR_04211, CLAUDE.md #59)")

    # 7b. a list-backed field bound to NO list  <- the SAME defect class as rule 7, one field type
    # over. A Select/Multiselect/Checkbox/Checklist takes its options from a separate LIST FLOW via
    # `ReferredList`, and publish has to materialise that option source; with the key absent there
    # is nothing to resolve and publish dies MetadataError with zero diagnostic content, while
    # every other rule reads the flow as healthy (isolated 2026-08-19 as the sole structural
    # deviation in a doctor-clean draft that 500'd deterministically). `apply_changes` used to mint
    # exactly this — auto-repairing the bare User field of rule 7 while writing a bare Select
    # silently twenty lines apart; it now refuses at compile, and this is the safety net for the
    # drafts THIS ENGINE DID NOT BUILD (template-cloned, copilot-built, hand-built).
    #
    # The `ReferredList` TARGET is deliberately never resolved: a list is a separate flow, never a
    # node in this graph, so `ReferredList not in draft` would false-flag every correctly wired
    # Select in existence. A table-child Select is NOT excluded — it needs its list just the same.
    list_backed = [v for v in N.values() if v.get("Kind") == "Field"
                   and v.get("Type") in LIST_BACKED_FIELD_TYPES]
    checked["list_backed_fields"] = len(list_backed)
    for f in list_backed:
        ref = f.get("ReferredList")
        if not isinstance(ref, str) or not ref:
            problems.append(
                f"{f.get('Type')} field {f.get('Name')!r} has no ReferredList — a dropdown bound "
                f"to no list; PUT 200s and publish dies 500 MetadataError with zero diagnostics "
                f"(CLAUDE.md ReferredList wiring #13 — mint the list with forge_create_list, then "
                f"re-apply the field with referred_list=<list id>)")

    # 7c. a developer TODO note shipped as a user-facing field LABEL. Not a publish blocker — a
    # certain repo defect regardless: a de-identified template shape carried its own reconnect
    # notes inside `Field.Name`, so they reached the form of every process built with
    # `from_template=True` (the default). Deliberately NOT a name-LENGTH rule: no maximum name
    # length is captured anywhere in shapes/ or docs/capabilities/, and inventing a bound would be
    # a guess (#10). The literal marker is unambiguous and repo-caused.
    todo_names = [v for v in N.values() if v.get("Kind") == "Field"]
    checked["placeholder_names"] = len(todo_names)
    for f in todo_names:
        name = f.get("Name")
        if isinstance(name, str) and _TODO_MARKER in name:
            problems.append(
                f"field name {name!r} carries a shipped TODO placeholder — a developer note is "
                f"being published as a user-facing label "
                f"(shapes/process_template_identity_shell.json; move the note out of Name)")

    # 8. a field column sitting off the 6-unit row grid  <- breaks rendering for the WHOLE flow
    # (CLAUDE.md > Node-graph invariants; observed live as "There was an error / Reload" on every
    # step of a flow whose columns overflowed one row). The engine's own layout paths tile the
    # grid correctly, so this is the safety net for drafts THIS ENGINE DID NOT BUILD — a
    # human-built or copilot-built form, or one an older engine mis-packed and left behind.
    # A table's CHILD columns carry Start=0/End=0 by design (CLAUDE.md > Tables: "the 6-unit row
    # grid does not apply inside a table"), so they come out of the fact base rather than
    # false-flagging every table-bearing flow. A table HOST is Type:"Model", never counted here.
    name_of_col = {c: v.get("Name", "?") for v in N.values()
                   if v.get("Kind") == "Field" and isinstance(c := v.get("Column"), str)}
    geometry_checked = 0
    by_row: dict[str, list[tuple[int, int, str]]] = {}
    for cid, col in N.items():
        if col.get("Kind") != "Column" or col.get("Type") != "Field":
            continue
        if cid in layout.table_child_columns:
            continue
        geometry_checked += 1
        label = name_of_col.get(cid, cid)
        start, end = col.get("Start"), col.get("End")
        if not isinstance(start, int) or not isinstance(end, int):
            problems.append(
                f"column {label!r} has no numeric grid span (Start={start!r}, End={end!r}) — the "
                f"builder cannot place it on the {ROW_UNITS}-unit row grid")
            continue
        if not (0 <= start < end <= ROW_UNITS):
            problems.append(
                f"column {label!r} sits at (Start={start}, End={end}), off the {ROW_UNITS}-unit "
                f"row grid (0 <= Start < End <= {ROW_UNITS}) — the builder fails to render the "
                f"whole flow")
            continue
        if isinstance(rid := col.get("Row"), str):
            by_row.setdefault(rid, []).append((start, end, label))
    for rid, spans in by_row.items():
        # every PAIR, not just adjacent ones: a wide column can swallow two narrow ones that do
        # not touch each other, and a row that only reports its first collision reads as
        # one-column-off when it is actually three
        spans.sort()
        for i, (s1, e1, n1) in enumerate(spans):
            for s2, e2, n2 in spans[i + 1:]:
                if s2 >= e1:
                    break                        # sorted by Start: nothing further can overlap
                problems.append(
                    f"columns {n1!r} ({s1}, {e1}) and {n2!r} ({s2}, {e2}) overlap in row {rid} — "
                    f"two columns cannot share a unit of the {ROW_UNITS}-unit row grid")
    checked["column_geometry"] = geometry_checked

    # 8b. ONE column claimed by TWO rows (D8a). The geometry walk above groups by the column's own
    # `Row` back-ref, so a column sitting in two Rows' `Row::Column` shows up once per group and
    # every span reads clean — the corruption is only visible from the ROW side, comparing each
    # membership entry against the column's own single-valued back-ref. `apply_exact_layout` used
    # to write exactly this when the same field was named twice in one layout spec (refused there
    # now); a hand-edited or copilot-built draft can still arrive with it.
    #
    # A COUNT rule ("at most 3 columns per row") deliberately does NOT live here: the shipped
    # shapes/process_template_identity_shell.json — a de-identified capture of a REAL published
    # production template — carries a Row with FOUR field columns at (0,2) (2,4) (4,5) (5,6), so a
    # >3 rule would fire on every from_template=True flow. CLAUDE.md's "at most 3 columns per row"
    # is the consequence of FIELD_SPAN=2 and is enforced where it belongs, on what this engine
    # WRITES (`graph.validate_layout_spans`), not asserted about drafts it did not build (#10).
    row_claims = 0
    for rid, row in N.items():
        if row.get("Kind") != "Row":
            continue
        for cid in row.get("Row::Column") or []:
            col = N.get(cid)
            if not isinstance(col, dict):
                continue          # a dangling membership is rule 3's finding, not this one
            row_claims += 1
            own = col.get("Row")
            if isinstance(own, str) and own != rid:
                problems.append(
                    f"column {cid} is listed in row {rid} but its own Row back-ref names {own} — "
                    f"two rows claim the same column, so one row renders it and the other renders "
                    f"a hole")
    checked["row_column_claims"] = row_claims

    return DoctorReport(
        problems=tuple(problems),
        checked=checked,
        unvalidated=tuple(unvalidated),
        unvalidatable_scripts=unvalidatable_scripts,
    )
