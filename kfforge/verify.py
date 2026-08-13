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

from .graph import NO_PERMISSION_NODETYPES, _no_permission_columns, _table_child_columns

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

    # 4. a section nobody can ever edit, and Required fields nobody can ever fill
    susp = {v.get("Name") for v in N.values() if v.get("Kind") == "Activity" and v.get("IsSuspended")}
    secof: dict[str, str] = {}
    for sv in N.values():
        if sv.get("Type") == "Section":
            for r in sv.get("Column::Row") or []:
                for cc in (N.get(r) or {}).get("Row::Column") or []:
                    secof[cc] = sv["Name"]
    editable: dict[str, set[str]] = {}
    for pm in N.values():
        if pm.get("Kind") != "Permission" or pm.get("Permission") != "Editable":
            continue
        step = N.get(pm.get("Activity"), {}).get("Name")
        if step in susp:                       # a suspended step never runs
            continue
        col = N.get(pm["Column"], {})
        keys = {secof.get(pm["Column"], col.get("Name", "?"))}
        # A table host (Type:"Model") NESTED inside a section is reachable under two different
        # names: the enclosing section's (via secof) and its own. A table sitting at the top
        # level has no enclosing section, so the two names coincide there and the gap stays
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
        if not editable.get(secof.get(f.get("Column"), "?")):
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
             - _table_child_columns(draft) - _no_permission_columns(draft))
    acts = [k for k, v in N.items() if v.get("Kind") == "Activity"
            and v.get("NodeType") not in ROUTING_NODE_TYPES]
    have = {(p["Column"], p["Activity"]) for p in N.values() if p.get("Kind") == "Permission"}
    checked["permission_pairs"] = len(units) * len(acts)
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

    return DoctorReport(
        problems=tuple(problems),
        checked=checked,
        unvalidated=tuple(unvalidated),
        unvalidatable_scripts=unvalidatable_scripts,
    )
