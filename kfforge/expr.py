"""Expression/Node AST builder for Kissflow branch conditions and GotoTask loop gates.

Pure and offline: no network, no Kissflow calls. Shapes captured live and documented in CLAUDE.md
(Expressions, Gate polarity, Workflow) and shapes/expression_branch.json,
shapes/expression_goto_condition.json, shapes/goto_task.json.

An Expression's owner key is one of three, each meaning something different (CLAUDE.md
Expressions): `ProcessDef` = a branch condition, `Activity` = a GotoTask loop condition,
`Property` = a value-generator prefix (e.g. a SequenceNumber scheme). `expression_owner` is the
one place that classification is made; every mutating function below branches off it.
"""
from __future__ import annotations

import copy
from typing import Any

from .graph import _new_id

Draft = dict[str, Any]

# Wire DataType for a Field-ref Node's operand, keyed by the compared field's own `Type`. Only
# Select is directly captured (shapes/expression_branch.json: a Select's value is plain-string on
# the wire, so its comparison Category is "String", never "Select"). Text is included by the
# identical reasoning — its wire value is unambiguously a string too — but has not itself been
# captured off a UI-built Text-field branch condition. Every other field type is refused rather
# than guessed (Number/Date in particular could plausibly use a non-"String" wire DataType):
# CLAUDE.md's "never guess a literal — read it" extends here to "never guess a wire shape".
_BRANCH_FIELD_DATA_TYPE: dict[str, str] = {
    "Select": "String",
    "Text": "String",  # UNCAPTURED — reasoned from Select, no UI-built Text branch ever captured
}


def expression_owner(node: dict[str, Any]) -> str:
    """Classify an Expression node by its owner key.

    Returns "branch" (ProcessDef-owned), "goto" (Activity-owned) or "property" (Property-owned).
    Exactly one of the three keys must be present (CLAUDE.md Expressions: "Always branch on which
    key is present before treating an Expression as routing logic"). Zero or more than one present
    raises rather than guessing, so a malformed or ambiguous node is never silently misclassified.
    """
    present = [name for key, name in
               (("ProcessDef", "branch"), ("Activity", "goto"), ("Property", "property"))
               if key in node]
    if len(present) != 1:
        raise ValueError(
            f"Expression {node.get('Id', node)!r} has {len(present)} owner key(s) among "
            f"ProcessDef/Activity/Property, expected exactly 1"
        )
    return present[0]


def build_branch_condition(
    draft: Draft,
    *,
    process_def_id: str,
    field_id: str,
    literal: str,
    options: list[str] | None,
) -> Draft:
    """Attach a ProcessDef-owned branch condition: `<field> = "<literal>"`.

    Writes the captured shape (shapes/expression_branch.json): a ProcessDef-owned Expression
    holding an infix "=" Node AST — a Field lhs, a Static rhs — plus the bidirectional
    `Field::Node` back-ref and an `ExpressionStr` mirror that addresses the field by ID, never by
    name. Pure: returns a NEW draft, input untouched.

    `options`, when given, is validated BEFORE any mutation: a literal that cannot match a real
    list option must never be written (CLAUDE.md Expressions: "never guess a literal — read it").
    `options=None` skips that check; the caller owns the risk of an unvalidated literal.

    Raises ValueError, draft entirely unmutated, when: `process_def_id` or `field_id` is not in
    the draft, the field's `Type` has no captured wire DataType for a string comparison (see
    `_BRANCH_FIELD_DATA_TYPE`), or `options` is given and `literal` is not in it.
    """
    if process_def_id not in draft:
        raise ValueError(f"no ProcessDef {process_def_id!r} in draft")
    if field_id not in draft:
        raise ValueError(f"no field {field_id!r} in draft")

    field_type = draft[field_id].get("Type")
    data_type = _BRANCH_FIELD_DATA_TYPE.get(field_type)
    if data_type is None:
        raise ValueError(
            f"field {field_id!r} has Type {field_type!r} — no captured wire DataType for a "
            f"branch-condition string comparison (captured: {sorted(_BRANCH_FIELD_DATA_TYPE)})"
        )
    if options is not None and literal not in options:
        raise ValueError(f"literal {literal!r} is not one of the field's real options {options}")

    new: Draft = copy.deepcopy(draft)

    expr_id = _new_id("Expression", process_def_id, 0, f"{field_id}:{literal}")
    root_id = _new_id("Node", process_def_id, 0, f"{field_id}:{literal}:root")
    lhs_id = _new_id("Node", process_def_id, 0, f"{field_id}:{literal}:lhs")
    rhs_id = _new_id("Node", process_def_id, 0, f"{field_id}:{literal}:rhs")

    new[lhs_id] = {"Id": lhs_id, "Kind": "Node", "Type": "Field", "Field": field_id,
                   "DataType": data_type, "Node": root_id}
    new[rhs_id] = {"Id": rhs_id, "Kind": "Node", "Type": "Static", "Value": literal,
                   "DataType": data_type, "Node": root_id}
    new[root_id] = {"Id": root_id, "Kind": "Node", "Type": "Function", "Value": "=",
                    "Syntax": "Infix", "Expression": expr_id, "FieldRefCount": 1,
                    "Node::Node": [lhs_id, rhs_id], "DataType": "Boolean", "Category": data_type}
    new[expr_id] = {"Id": expr_id, "Kind": "Expression", "ExpressionStr": f'{field_id} = "{literal}"',
                    "ProcessDef": process_def_id, "Expression::Node": [root_id]}

    if expr_id not in (new[process_def_id].get("ProcessDef::Expression") or []):
        new[process_def_id].setdefault("ProcessDef::Expression", []).append(expr_id)
    if lhs_id not in (new[field_id].get("Field::Node") or []):
        new[field_id].setdefault("Field::Node", []).append(lhs_id)
    return new


def remove_condition(draft: Draft, *, expression_id: str) -> Draft:
    """Delete a branch or goto condition — the Expression node, its WHOLE Node AST subtree at ANY
    depth, and the `Field::Node` back-ref(s) it left on every field it referenced anywhere in that
    subtree. Pure: returns a NEW draft, input untouched.

    The counterpart to `build_branch_condition`/`build_goto_gate`, for a caller that wants SET
    semantics ("this branch's condition is now X") rather than ADD semantics: remove whatever
    condition was already on the owner before attaching a new one, so a re-run with a changed field
    or literal never leaves two conditions stacked on the same ProcessDef/Activity — matching
    `graph.set_step_permissions`/`graph.set_field_events`'s own "delete existing, then rebuild"
    idiom rather than inventing a new one (build_branch_condition/build_goto_gate are already
    idempotent on their own for a repeat call with IDENTICAL args — same deterministic id, same
    dict — but NOT for a repeat call whose field or literal changed, since that mints a different
    id and simply appends alongside the stale one).

    ⚠️ Node M review (2026-08-07): the subtree walk below is a full traversal, not a fixed
    root-then-children walk. Every `build_*` function in THIS module only ever writes a 2-level AST
    (root `=`, two leaf children), which a shallower walk would have looked correct against — but
    `apply_branch_conditions` calls this on ANY pre-existing ProcessDef Expression, including one a
    HUMAN built in the UI (a compound `AND`/`OR` of several comparisons is a deeper tree, unproven
    here but entirely plausible from the builder), and a walk that stops after one level would
    delete the Expression and its immediate children while stranding the INNER comparisons' own
    leaf nodes — plus leaving `Field::Node` pointed at now-deleted node ids for every field only
    those deeper leaves referenced. The walk here follows `Node::Node` all the way down, however
    deep, and a `doomed_nodes` revisit-guard means a malformed cycle (never produced by any builder
    in this pack, but a hand-edited draft could carry one) degrades to "already handled," never an
    infinite loop.

    Works on either owner kind (`expression_owner`: "branch" -> `ProcessDef`, "goto" -> `Activity`)
    — a "property" owner (a SequenceNumber prefix, not a condition at all) is refused, same
    restriction `rewire_condition` already applies, since removing one would silently break
    whatever value-generator depends on it.

    Raises ValueError, draft entirely unmutated, when `expression_id` is not in the draft, or its
    owner is Property-owned.
    """
    if expression_id not in draft:
        raise ValueError(f"no Expression {expression_id!r} in draft")
    expr = draft[expression_id]
    owner = expression_owner(expr)
    if owner == "property":
        raise ValueError(
            f"Expression {expression_id!r} is Property-owned (a value-generator prefix, not a "
            f"branch/goto condition) — remove_condition only removes ProcessDef or Activity conditions"
        )
    owner_key = "ProcessDef" if owner == "branch" else "Activity"
    owner_id = expr.get(owner_key)
    back_ref_key = f"{owner_key}::Expression"

    # Full subtree walk (iterative, not recursive: no Python call-stack depth concern on a
    # deliberately-crafted or unusually large AST). `doomed_nodes` doubles as the visited-set, so a
    # cycle just stops re-expanding instead of looping forever.
    doomed_nodes: set[str] = set()
    field_ids: set[str] = set()
    stack = list(expr.get("Expression::Node") or [])
    while stack:
        node_id = stack.pop()
        if node_id in doomed_nodes:
            continue
        doomed_nodes.add(node_id)
        node = draft.get(node_id) or {}
        if node.get("Type") == "Field" and isinstance(node.get("Field"), str):
            field_ids.add(node["Field"])
        stack.extend(node.get("Node::Node") or [])

    new: Draft = copy.deepcopy(draft)
    for nid in doomed_nodes:
        new.pop(nid, None)
    new.pop(expression_id, None)

    if isinstance(owner_id, str) and owner_id in new:
        remaining = [e for e in (new[owner_id].get(back_ref_key) or []) if e != expression_id]
        if remaining:
            new[owner_id][back_ref_key] = remaining
        else:
            new[owner_id].pop(back_ref_key, None)

    for fid in field_ids:
        if fid not in new:
            continue
        remaining_nodes = [n for n in (new[fid].get("Field::Node") or []) if n not in doomed_nodes]
        if remaining_nodes:
            new[fid]["Field::Node"] = remaining_nodes
        else:
            new[fid].pop("Field::Node", None)

    return new


def build_goto_gate(draft: Draft, *, goto_activity_id: str, field_id: str) -> Draft:
    """Attach an Activity-owned loop condition to a GotoTask: `<field> = false()`.

    Writes the captured shape (shapes/expression_goto_condition.json): an Activity-owned
    Expression holding an infix "=" Node AST comparing a Boolean field against the zero-arg
    `false()` Function literal — never a Static, which would be a string and never match a
    Boolean (CLAUDE.md Expressions). Pure: returns a NEW draft, input untouched.

    Gate polarity (CLAUDE.md Gate polarity): only a Boolean may gate a loop, never an optional
    Select — an unticked Boolean fails CLOSED (the item stays trapped, visible and fixable), while
    a blank Select fails OPEN (the item silently escapes the rework it needed).

    Raises ValueError, draft entirely unmutated, when `goto_activity_id` or `field_id` is not in
    the draft, or the field's `Type` is not `"Boolean"`.
    """
    if goto_activity_id not in draft:
        raise ValueError(f"no Activity {goto_activity_id!r} in draft")
    if field_id not in draft:
        raise ValueError(f"no field {field_id!r} in draft")

    field_type = draft[field_id].get("Type")
    if field_type != "Boolean":
        raise ValueError(
            f"field {field_id!r} is Type {field_type!r}, not Boolean — gate polarity rule: never "
            f"gate a loop on an optional Select, only ever on a Boolean (CLAUDE.md Gate polarity)"
        )

    new: Draft = copy.deepcopy(draft)

    expr_id = _new_id("Expression", goto_activity_id, 0, field_id)
    root_id = _new_id("Node", goto_activity_id, 0, f"{field_id}:root")
    lhs_id = _new_id("Node", goto_activity_id, 0, f"{field_id}:lhs")
    rhs_id = _new_id("Node", goto_activity_id, 0, f"{field_id}:rhs")

    new[lhs_id] = {"Id": lhs_id, "Kind": "Node", "Type": "Field", "Field": field_id,
                   "DataType": "Boolean", "Node": root_id}
    new[rhs_id] = {"Id": rhs_id, "Kind": "Node", "Type": "Function", "Value": "false",
                   "DataType": "Boolean", "Category": "Boolean", "Node": root_id}
    new[root_id] = {"Id": root_id, "Kind": "Node", "Type": "Function", "Value": "=",
                    "Syntax": "Infix", "Expression": expr_id, "FieldRefCount": 1,
                    "Node::Node": [lhs_id, rhs_id], "DataType": "Boolean", "Category": "Boolean"}
    new[expr_id] = {"Id": expr_id, "Kind": "Expression", "ExpressionStr": f"{field_id} = false()",
                    "Activity": goto_activity_id, "Expression::Node": [root_id]}

    if expr_id not in (new[goto_activity_id].get("Activity::Expression") or []):
        new[goto_activity_id].setdefault("Activity::Expression", []).append(expr_id)
    if lhs_id not in (new[field_id].get("Field::Node") or []):
        new[field_id].setdefault("Field::Node", []).append(lhs_id)
    return new


def rewire_condition(
    draft: Draft,
    *,
    expression_id: str,
    new_field_id: str,
    options: list[str] | None = None,
    new_literal: str | None = None,
) -> Draft:
    """Repoint an existing branch or goto condition at a different field — the SIX edits, atomically.

    CLAUDE.md Expressions: "Rewiring a condition to point at a different field is six edits, not
    one": (1) the Field node's `Field` reference, (2) that node's `DataType`, (3) the literal node
    — value, and shape if the field's type-family changed, (4) the root's `Category`, (5) the
    `ExpressionStr` mirror, (6) moving the `Field::Node` back-reference off the old field onto the
    new one. All six happen together, or none do.

    The condition's OWNER (branch vs goto — see `expression_owner`) does not change; only the
    field under test does. Each owner keeps its own builder's rules:

    - "goto": always ends up testing the new field with the zero-arg `false()` literal, and
      REQUIRES the new field to be Boolean (same restriction as `build_goto_gate`). `new_literal`
      must be omitted — a goto gate is always tested against `false()`, there is no other captured
      shape, so a caller-supplied literal is refused rather than silently ignored.
    - "branch": always ends up with a Static literal, and requires the new field's type to be in
      `_BRANCH_FIELD_DATA_TYPE` (same restriction as `build_branch_condition`). When `new_literal`
      is omitted, the existing Static value is carried over unchanged — this raises if the
      existing literal is not itself a Static (e.g. it was a goto's `false()`), since there is
      nothing sensible to carry over across that shape change.
    - "property" (a SequenceNumber prefix, not a condition at all) is refused outright.

    Raises ValueError, draft entirely unmutated, on: unknown `expression_id` / `new_field_id`, a
    malformed condition AST, a Property-owned expression, an owner/field-type mismatch,
    `new_literal` given on a goto rewire, an omitted `new_literal` with no Static value to carry
    over, or (when both are given) a literal outside `options`.
    """
    if expression_id not in draft:
        raise ValueError(f"no Expression {expression_id!r} in draft")
    if new_field_id not in draft:
        raise ValueError(f"no field {new_field_id!r} in draft")

    expr = draft[expression_id]
    owner = expression_owner(expr)
    if owner == "property":
        raise ValueError(
            f"Expression {expression_id!r} is Property-owned (a value-generator prefix, not a "
            f"branch/goto condition) — rewire_condition only rewires ProcessDef or Activity conditions"
        )

    root_ids = expr.get("Expression::Node") or []
    if len(root_ids) != 1:
        raise ValueError(f"Expression {expression_id!r} has {len(root_ids)} root node(s), expected 1")
    root_id = root_ids[0]
    if root_id not in draft:
        raise ValueError(f"Expression {expression_id!r}'s root node {root_id!r} is missing")

    child_ids = draft[root_id].get("Node::Node") or []
    if len(child_ids) != 2:
        raise ValueError(f"condition root {root_id!r} has {len(child_ids)} child node(s), expected 2")
    field_child_id = next((c for c in child_ids if draft.get(c, {}).get("Type") == "Field"), None)
    if field_child_id is None:
        raise ValueError(f"condition root {root_id!r} has no Field-type child to rewire")
    literal_child_id = next(c for c in child_ids if c != field_child_id)
    literal_child_type = draft.get(literal_child_id, {}).get("Type")
    if literal_child_type not in ("Static", "Function"):
        # e.g. a second Field-type child (a field-vs-field comparison) — silently treating it as
        # "the literal" would overwrite a real field reference instead of refusing the rewire.
        raise ValueError(
            f"condition root {root_id!r}'s literal child {literal_child_id!r} has Type "
            f"{literal_child_type!r}, expected Static or Function"
        )

    old_field_id = draft[field_child_id].get("Field")
    new_field_type = draft[new_field_id].get("Type")

    literal_value: str | None
    if owner == "goto":
        if new_field_type != "Boolean":
            raise ValueError(
                f"field {new_field_id!r} is Type {new_field_type!r}, not Boolean — gate polarity "
                f"rule: a goto condition may only be rewired onto a Boolean field"
            )
        if new_literal is not None:
            raise ValueError(
                "a goto condition is always tested against false() — do not pass new_literal "
                "when rewiring a goto condition"
            )
        data_type = "Boolean"
        literal_value = "false"
        expr_str = f"{new_field_id} = false()"
    else:  # "branch"
        data_type = _BRANCH_FIELD_DATA_TYPE.get(new_field_type)
        if data_type is None:
            raise ValueError(
                f"field {new_field_id!r} has Type {new_field_type!r} — no captured wire DataType "
                f"for a branch-condition string comparison (captured: {sorted(_BRANCH_FIELD_DATA_TYPE)})"
            )
        if new_literal is None:
            old_literal = draft[literal_child_id]
            if old_literal.get("Type") != "Static":
                raise ValueError(
                    f"condition {expression_id!r}'s existing literal is not a Static value — pass "
                    f"new_literal explicitly, there is nothing sensible to carry over"
                )
            literal_value = old_literal.get("Value")
        else:
            literal_value = new_literal
        if options is not None and literal_value not in options:
            raise ValueError(f"literal {literal_value!r} is not one of the field's real options {options}")
        expr_str = f'{new_field_id} = "{literal_value}"'

    new: Draft = copy.deepcopy(draft)

    # 1 + 2: the Field node's own reference and DataType
    new[field_child_id]["Field"] = new_field_id
    new[field_child_id]["DataType"] = data_type

    # 3: the literal node — value, and shape when the field's type-family changed
    if owner == "goto":
        new[literal_child_id] = {"Id": literal_child_id, "Kind": "Node", "Type": "Function",
                                 "Value": "false", "DataType": "Boolean", "Category": "Boolean",
                                 "Node": root_id}
    else:
        new[literal_child_id] = {"Id": literal_child_id, "Kind": "Node", "Type": "Static",
                                 "Value": literal_value, "DataType": data_type, "Node": root_id}

    # 4: the root's Category, recomputed from the new operands
    new[root_id]["Category"] = data_type

    # 5: the ExpressionStr mirror
    new[expression_id]["ExpressionStr"] = expr_str

    # 6: the Field::Node back-ref moves off the old field onto the new one
    if old_field_id is not None and old_field_id in new and old_field_id != new_field_id:
        remaining = [n for n in (new[old_field_id].get("Field::Node") or []) if n != field_child_id]
        if remaining:
            new[old_field_id]["Field::Node"] = remaining
        else:
            new[old_field_id].pop("Field::Node", None)
    if field_child_id not in (new[new_field_id].get("Field::Node") or []):
        new[new_field_id].setdefault("Field::Node", []).append(field_child_id)

    return new
