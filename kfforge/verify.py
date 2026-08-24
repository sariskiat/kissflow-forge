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


def _owning_table_name(nodes: dict[str, Any], field: dict[str, Any]) -> str | None:
    """The NAME of the child table this field belongs to, or None when it is a root form field.

    A table is a nested Model hosted by a `Column{Type:"Model"}` (CLAUDE.md > Tables), so a child
    field's `Model` back-ref names the table Model rather than the root. The name is read off the
    table Model and falls back to its HOST column — the two carry the same name when this engine
    writes the table, and a live read-back that drops one still resolves the other, the same
    two-signal discipline `graph._table_model_ids` uses.

    Only ever used to pick which REMEDY a problem sentence states, so an unnamed table degrades to
    the root-field remedy rather than a sentence naming `None`.
    """
    owner = nodes.get(field.get("Model"))
    if not isinstance(owner, dict) or owner.get("Kind") != "Model":
        return None
    host = nodes.get(owner.get("Column"))
    if not isinstance(host, dict):                     # a root Model has no host column
        return None
    name = owner.get("Name") or host.get("Name")
    return name if isinstance(name, str) and name else None


def _validate_root(draft: Draft) -> str:
    root = draft.get("Root")
    if not isinstance(root, str) or root not in draft:
        raise ValueError("draft has no Root key — not a flow draft?")
    return root


def _check_role_scoped_visibility_claims(
    claims: tuple[str, ...] | list[str],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    checked["role_scoped_visibility_claims"] = len(claims)
    for claim in claims:
        problems.append(
            f"{claim}: role-scoped visibility is API-impossible; restructure to step-scoped "
            f"(coverage row role-scoped-visibility, #6)"
        )


def _check_single_event(
    event: dict[str, Any],
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
) -> bool:
    owner = nodes.get(event.get("Field"), {}).get("Name", event.get("Field"))
    script = event.get("Script") or ""
    for ref in set(_PLATFORM_REF_RE.findall(script)):
        if ref not in draft:
            problems.append(f"event on {owner!r} writes to missing field {ref}")
    if event.get("Field") not in draft:
        problems.append(f"event {event['Id']} is attached to a missing field")
    return bool(script)


def _check_event_scripts(
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> int:
    events = [v for v in nodes.values() if v.get("Kind") == "Event"]
    checked["events"] = len(events)
    unvalidatable = 0
    for e in events:
        if _check_single_event(e, draft, nodes, problems):
            unvalidatable += 1
    return unvalidatable


def _lookup_field_options(
    field_sibling: dict[str, Any] | None,
    nodes: dict[str, Any],
    list_options: dict[str, list[str]],
) -> list[str] | None:
    if field_sibling is None:
        return None
    fnode = nodes.get(field_sibling.get("Field")) or {}
    if fnode.get("Type") == "Select":
        return list_options.get(fnode.get("ReferredList"))
    return None


def _check_branch_static_literal(
    branch: str | None,
    n: dict[str, Any],
    field_sibling: dict[str, Any] | None,
    nodes: dict[str, Any],
    list_options: dict[str, list[str]],
    problems: list[str],
    unvalidated: list[str],
) -> None:
    value = n.get("Value")
    options = _lookup_field_options(field_sibling, nodes, list_options)
    if options is None:
        unvalidated.append(
            f"branch {branch!r} literal {value!r} not validated "
            f"(no list options given for its field)"
        )
    elif value not in options:
        problems.append(f"branch {branch!r} tests {value!r}, not in {options}")


def _check_branch_children(
    branch: str | None,
    children: list[tuple[str, dict[str, Any]]],
    draft: Draft,
    nodes: dict[str, Any],
    list_options: dict[str, list[str]],
    problems: list[str],
    unvalidated: list[str],
) -> int:
    field_sibling = next((n for _, n in children if n.get("Type") == "Field"), None)
    literals = 0
    for _cid, n in children:
        if n.get("Type") == "Field" and n.get("Field") not in draft:
            problems.append(f"branch {branch!r} references missing field {n.get('Field')}")
            continue
        if n.get("Type") == "Static":
            literals += 1
            _check_branch_static_literal(
                branch, n, field_sibling, nodes, list_options, problems, unvalidated
            )
    return literals


def _check_branch_expression(
    expr_node: dict[str, Any],
    draft: Draft,
    nodes: dict[str, Any],
    list_options: dict[str, list[str]],
    problems: list[str],
    unvalidated: list[str],
) -> int:
    branch = nodes.get(expr_node.get("ProcessDef"), {}).get("Name")
    literals = 0
    for root_id in expr_node.get("Expression::Node") or []:
        children = [
            (cid, nodes.get(cid) or {})
            for cid in (nodes.get(root_id) or {}).get("Node::Node") or []
        ]
        literals += _check_branch_children(
            branch, children, draft, nodes, list_options, problems, unvalidated
        )
    return literals


def _check_branch_conditions(
    draft: Draft,
    nodes: dict[str, Any],
    list_options: dict[str, list[str]],
    problems: list[str],
    unvalidated: list[str],
    checked: dict[str, int],
) -> None:
    branch_exprs = [v for v in nodes.values() if v.get("Kind") == "Expression" and v.get("ProcessDef")]
    literals_checked = sum(
        _check_branch_expression(x, draft, nodes, list_options, problems, unvalidated)
        for x in branch_exprs
    )
    checked["branch_literals"] = literals_checked


def _check_goto_target(
    g: dict[str, Any],
    nodes: dict[str, Any],
    problems: list[str],
) -> None:
    name = g.get("Name")
    target = nodes.get(g.get("Goto"))
    if not target:
        problems.append(f"goto {name!r} jumps to missing activity {g.get('Goto')}")
    elif target.get("ProcessDef") != g.get("ProcessDef"):
        problems.append(f"goto {name!r} jumps out of its own branch, to {target.get('Name')!r}")
    elif g["Id"] not in (target.get("Goto::Activity") or []):
        problems.append(f"goto {name!r} missing the Goto::Activity back-ref on its target")


def _check_goto_gate_field(
    name: str | None,
    n: dict[str, Any],
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
) -> None:
    if n.get("Type") != "Field":
        return
    if n["Field"] not in draft:
        problems.append(f"goto {name!r} tests missing field {n['Field']}")
        return
    gate = nodes[n["Field"]]
    if gate.get("Type") == "Select" and not gate.get("Required"):
        problems.append(
            f"goto {name!r} tests optional Select {gate.get('Name')!r} — blank "
            f"never equals the literal, so the loop is skipped, not entered"
        )


def _check_goto_expressions(
    g: dict[str, Any],
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
) -> None:
    name = g.get("Name")
    exprs = g.get("Activity::Expression") or []
    if not exprs:
        problems.append(f"goto {name!r} has NO condition — it loops forever")
        return
    for xid in exprs:
        for root_id in (nodes.get(xid) or {}).get("Expression::Node") or []:
            for cid in (nodes.get(root_id) or {}).get("Node::Node") or []:
                _check_goto_gate_field(name, nodes.get(cid) or {}, draft, nodes, problems)


def _check_gotos(
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    gotos = [v for v in nodes.values() if v.get("NodeType") == "GotoTask"]
    checked["gotos"] = len(gotos)
    for g in gotos:
        _check_goto_target(g, nodes, problems)
        _check_goto_expressions(g, draft, nodes, problems)


def _check_node_dangling_list_refs(
    nid: str,
    node: dict[str, Any],
    draft: Draft,
    problems: list[str],
) -> int:
    checked_count = 0
    for key, val in node.items():
        if isinstance(val, list) and "::" in key:
            for ref in val:
                if isinstance(ref, str):
                    checked_count += 1
                    if ref not in draft:
                        problems.append(f"{nid}.{key} -> missing {ref}")
    return checked_count


def _check_dangling_list_refs(
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    dangling_checked = sum(
        _check_node_dangling_list_refs(nid, node, draft, problems)
        for nid, node in nodes.items()
    )
    checked["dangling_refs"] = dangling_checked


def _check_step_stamps(
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    step_stamps = 0
    for nid, node in nodes.items():
        if node.get("Kind") == "Property" and node.get("Name") == "Step":
            step_stamps += 1
            tgt = node.get("Value")
            if isinstance(tgt, str) and (draft.get(tgt) or {}).get("Kind") != "Activity":
                problems.append(
                    f"sequence Step stamp {nid} -> missing activity {tgt} (publish will 500 "
                    f"MetadataError — repoint it or rebuild via build_workflow, which now "
                    f"repoints by name)"
                )
    checked["step_stamps"] = step_stamps


def _check_single_scalar_ref(
    nid: str,
    key: str,
    ref: Any,
    draft: Draft,
    problems: list[str],
) -> tuple[int, int]:
    if not isinstance(ref, str) or not ref:
        return 0, 0
    if ref.startswith("_"):
        return 0, 1
    if ref not in draft:
        problems.append(
            f"{nid}.{key} -> missing {ref} (scalar reference — the list-only sweep never "
            f"visits it; PUT 200s, publish dies 500 MetadataError with zero diagnostics)"
        )
    return 1, 0


def _check_scalar_refs(
    draft: Draft,
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    scalar_refs = 0
    system_scalar_refs = 0
    for nid, node in nodes.items():
        for key in _SCALAR_REF_KEYS.get(node.get("Kind"), ()):
            s, sys = _check_single_scalar_ref(nid, key, node.get(key), draft, problems)
            scalar_refs += s
            system_scalar_refs += sys
    checked["scalar_refs"] = scalar_refs
    checked["system_scalar_refs"] = system_scalar_refs


def _process_permission_node(
    pm: dict[str, Any],
    nodes: dict[str, Any],
    layout: Any,
    suspended_steps: set[str | None],
    editable: dict[str, set[str]],
    malformed: list[str],
) -> None:
    if pm.get("Kind") != "Permission" or pm.get("Permission") != "Editable":
        return
    step = nodes.get(pm.get("Activity"), {}).get("Name")
    if step in suspended_steps:
        return
    col_id = pm.get("Column")
    if not isinstance(col_id, str) or not isinstance(pm.get("Activity"), str):
        malformed.append(pm.get("Id", "<no Id>"))
        return
    col = nodes.get(col_id, {})
    keys = {layout.owner_section(col_id) or col.get("Name", "?")}
    if col.get("Type") == "Model" and col.get("Name"):
        keys.add(col["Name"])
    for key in keys:
        editable.setdefault(key, set()).add(step)


def _collect_editable_and_malformed_permissions(
    nodes: dict[str, Any],
    layout: Any,
) -> tuple[dict[str, set[str]], list[str]]:
    malformed: list[str] = []
    susp = {v.get("Name") for v in nodes.values() if v.get("Kind") == "Activity" and v.get("IsSuspended")}
    editable: dict[str, set[str]] = {}
    for pm in nodes.values():
        _process_permission_node(pm, nodes, layout, susp, editable, malformed)
    return editable, malformed


def _check_editable_sections(
    nodes: dict[str, Any],
    editable: dict[str, set[str]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    sections_checked = 0
    for sv in nodes.values():
        if sv.get("Type") in ("Section", "Model") and sv.get("Name"):
            sections_checked += 1
            if sv.get("Type") == "Section" and not sv.get("Column::Row"):
                continue
            if not editable.get(sv["Name"]):
                problems.append(f"section {sv['Name']!r} is never editable at any live step")
    checked["sections"] = sections_checked


def _check_required_fields(
    root: str,
    nodes: dict[str, Any],
    layout: Any,
    editable: dict[str, set[str]],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    required_fields = [
        v for v in nodes.values()
        if v.get("Kind") == "Field" and v.get("Model") == root and v.get("Required")
    ]
    checked["required_fields"] = len(required_fields)
    for f in required_fields:
        if not editable.get(layout.owner_section(f.get("Column")) or "?"):
            problems.append(
                f"field {f['Name']!r} is Required but never editable — that step cannot be submitted"
            )


def _format_malformed_permissions(malformed_permissions: list[str]) -> str:
    sample = ", ".join(sorted(malformed_permissions)[:5])
    suffix = " ..." if len(malformed_permissions) > 5 else ""
    return (
        f"{len(malformed_permissions)} Permission node(s) missing a Column/Activity "
        f"reference: {sample}{suffix} — the builder writes both on every Permission; "
        f"a node without them gates nothing"
    )


def _check_permission_matrix(
    nodes: dict[str, Any],
    layout: Any,
    malformed_permissions: list[str],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    units = (
        {k for k, v in nodes.items() if v.get("Kind") == "Column" and v.get("Type") == "Field"}
        - layout.table_child_columns
        - layout.no_permission_columns
    )
    acts = [
        k for k, v in nodes.items()
        if v.get("Kind") == "Activity" and v.get("NodeType") not in ROUTING_NODE_TYPES
    ]
    have = {
        (c, a) for p in nodes.values()
        if p.get("Kind") == "Permission"
        and isinstance(c := p.get("Column"), str)
        and isinstance(a := p.get("Activity"), str)
    }
    checked["permission_pairs"] = len(units) * len(acts)
    checked["malformed_permissions"] = len(malformed_permissions)
    if malformed_permissions:
        problems.append(_format_malformed_permissions(malformed_permissions))
    gaps = len({(u, a) for u in units for a in acts} - have)
    if gaps:
        problems.append(f"permission matrix is sparse: {gaps} (unit, step) pairs unset")


def _has_app_role_assignee(res_ids: list[str], nodes: dict[str, Any]) -> bool:
    for r in res_ids:
        res = nodes.get(r) or {}
        if res.get("Value") and res.get("ValueType") == "AppRole":
            return True
    return False


def _check_step_assignees(
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    real_steps = [
        (k, v) for k, v in nodes.items()
        if v.get("Kind") == "Activity" and v.get("NodeType") == "UserTask" and not v.get("IsSuspended")
    ]
    checked["step_assignees"] = len(real_steps)
    for _aid, v in real_steps:
        res_ids = v.get("Activity::Resource") or []
        if not _has_app_role_assignee(res_ids, nodes):
            problems.append(
                f"step {v.get('Name')!r} has no AppRole assignee — submit will 500 (CLAUDE.md "
                f"Members first: wire a Resource with ValueType 'AppRole' on every step)"
            )


def _check_user_fields(
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    user_fields = [v for v in nodes.values() if v.get("Kind") == "Field" and v.get("Type") == "User"]
    checked["user_fields"] = len(user_fields)
    for f in user_fields:
        qids = f.get("Field::QueryDefinition") or []
        has_query_def = any((nodes.get(q) or {}).get("Kind") == "QueryDefinition" for q in qids)
        if not has_query_def:
            problems.append(
                f"User field {f.get('Name')!r} has no QueryDefinition sibling — publish will fail "
                f"(KISSFLOW_ERROR_04211, CLAUDE.md #59)"
            )


def _format_list_backed_field_problem(
    f: dict[str, Any],
    table: str | None,
) -> str:
    name = f.get("Name")
    head = (f"{f.get('Type')} field {name!r} has no ReferredList — a dropdown bound "
            f"to no list; PUT 200s and publish dies 500 MetadataError with zero "
            f"diagnostics (CLAUDE.md ReferredList wiring #13 — ")
    if table is None:
        return head + "mint the list with forge_create_list, then re-apply the field with referred_list=<list id>)"
    return (
        head + f"mint the list with forge_create_list, then REBUILD table {table!r}: "
               f"forge_delete_fields(tables=[{table!r}]) followed by forge_add_table "
               f"with the column stated as [{name!r}, {f.get('Type')!r}, "
               f'{{"ReferredList": "<list id>"}}]. A table CHILD has no in-place '
               f"edit: forge_apply_fields only creates ROOT fields, so re-applying "
               f"this name would leave the table untouched and add a second, "
               f"root-level field of the same name)"
    )


def _check_list_backed_fields(
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    list_backed = [
        v for v in nodes.values()
        if v.get("Kind") == "Field" and v.get("Type") in LIST_BACKED_FIELD_TYPES
    ]
    checked["list_backed_fields"] = len(list_backed)
    for f in list_backed:
        ref = f.get("ReferredList")
        if not isinstance(ref, str) or not ref:
            table = _owning_table_name(nodes, f)
            problems.append(_format_list_backed_field_problem(f, table))


def _check_placeholder_names(
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    todo_names = [v for v in nodes.values() if v.get("Kind") == "Field"]
    checked["placeholder_names"] = len(todo_names)
    for f in todo_names:
        name = f.get("Name")
        if isinstance(name, str) and _TODO_MARKER in name:
            problems.append(
                f"field name {name!r} carries a shipped TODO placeholder — a developer note is "
                f"being published as a user-facing label "
                f"(shapes/process_template_identity_shell.json; move the note out of Name)"
            )


def _check_column_span_validity(
    label: str,
    start: Any,
    end: Any,
    problems: list[str],
) -> bool:
    if not isinstance(start, int) or not isinstance(end, int):
        problems.append(
            f"column {label!r} has no numeric grid span (Start={start!r}, End={end!r}) — the "
            f"builder cannot place it on the {ROW_UNITS}-unit row grid"
        )
        return False
    if not (0 <= start < end <= ROW_UNITS):
        problems.append(
            f"column {label!r} sits at (Start={start}, End={end}), off the {ROW_UNITS}-unit "
            f"row grid (0 <= Start < End <= {ROW_UNITS}) — the builder fails to render the "
            f"whole flow"
        )
        return False
    return True


def _check_row_overlaps(
    by_row: dict[str, list[tuple[int, int, str]]],
    problems: list[str],
) -> None:
    for rid, spans in by_row.items():
        spans.sort()
        for i, (s1, e1, n1) in enumerate(spans):
            for s2, e2, n2 in spans[i + 1:]:
                if s2 >= e1:
                    break
                problems.append(
                    f"columns {n1!r} ({s1}, {e1}) and {n2!r} ({s2}, {e2}) overlap in row {rid} — "
                    f"two columns cannot share a unit of the {ROW_UNITS}-unit row grid"
                )


def _check_column_geometry(
    nodes: dict[str, Any],
    layout: Any,
    problems: list[str],
    checked: dict[str, int],
) -> None:
    name_of_col = {
        c: v.get("Name", "?") for v in nodes.values()
        if v.get("Kind") == "Field" and isinstance(c := v.get("Column"), str)
    }
    geometry_checked = 0
    by_row: dict[str, list[tuple[int, int, str]]] = {}
    for cid, col in nodes.items():
        if col.get("Kind") != "Column" or col.get("Type") != "Field":
            continue
        if cid in layout.table_child_columns:
            continue
        geometry_checked += 1
        label = name_of_col.get(cid, cid)
        start, end = col.get("Start"), col.get("End")
        if not _check_column_span_validity(label, start, end, problems):
            continue
        if isinstance(rid := col.get("Row"), str):
            by_row.setdefault(rid, []).append((start, end, label))
    _check_row_overlaps(by_row, problems)
    checked["column_geometry"] = geometry_checked


def _check_row_column_claims(
    nodes: dict[str, Any],
    problems: list[str],
    checked: dict[str, int],
) -> None:
    row_claims = 0
    for rid, row in nodes.items():
        if row.get("Kind") != "Row":
            continue
        for cid in row.get("Row::Column") or []:
            col = nodes.get(cid)
            if not isinstance(col, dict):
                continue
            row_claims += 1
            own = col.get("Row")
            if isinstance(own, str) and own != rid:
                problems.append(
                    f"column {cid} is listed in row {rid} but its own Row back-ref names {own} — "
                    f"two rows claim the same column, so one row renders it and the other renders "
                    f"a hole"
                )
    checked["row_column_claims"] = row_claims


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
    root = _validate_root(draft)
    nodes = _nodes(draft)
    resolved_options = list_options if list_options is not None else {}
    problems: list[str] = []
    unvalidated: list[str] = []
    checked: dict[str, int] = {}
    layout = section_layout(draft)

    _check_role_scoped_visibility_claims(visibility_role_claims, problems, checked)
    unvalidatable_scripts = _check_event_scripts(draft, nodes, problems, checked)
    _check_branch_conditions(draft, nodes, resolved_options, problems, unvalidated, checked)
    _check_gotos(draft, nodes, problems, checked)
    _check_dangling_list_refs(draft, nodes, problems, checked)
    _check_step_stamps(draft, nodes, problems, checked)
    _check_scalar_refs(draft, nodes, problems, checked)

    editable, malformed_permissions = _collect_editable_and_malformed_permissions(nodes, layout)
    _check_editable_sections(nodes, editable, problems, checked)
    _check_required_fields(root, nodes, layout, editable, problems, checked)
    _check_permission_matrix(nodes, layout, malformed_permissions, problems, checked)

    _check_step_assignees(nodes, problems, checked)
    _check_user_fields(nodes, problems, checked)
    _check_list_backed_fields(nodes, problems, checked)
    _check_placeholder_names(nodes, problems, checked)
    _check_column_geometry(nodes, layout, problems, checked)
    _check_row_column_claims(nodes, problems, checked)

    return DoctorReport(
        problems=tuple(problems),
        checked=checked,
        unvalidated=tuple(unvalidated),
        unvalidatable_scripts=unvalidatable_scripts,
    )
