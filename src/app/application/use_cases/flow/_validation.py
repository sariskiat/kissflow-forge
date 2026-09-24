"""Pure read-back audit helpers for `ForgeAddFieldValidation`.

Copied from `app.infrastructure.kissflow.client`'s `_node_child_ids`,
`_condition_rule`, `_criteria_conditions`, `_field_live_rules`, `_field_map`,
`_audit_all_field_rules` and `_calc_missing` (pre-refactor), adapted to read
a `FlowDraft.to_wire()` dict instead of the old client's raw draft dict.
"""

from __future__ import annotations

from typing import Any

Draft = dict[str, Any]


def _node_child_ids(draft: Draft, node_id: str, key: str) -> list[str]:
    """The node ids under one relation key of one node.

    Args:
        draft: The flow's wire-format draft.
        node_id: The parent node's id.
        key: The relation key to read (for example `"Criteria::Condition"`).

    Returns:
        The child ids, or `[]` when the node is missing or the key is
        absent/malformed.
    """
    node = draft.get(node_id)
    if not isinstance(node, dict):
        return []
    items = node.get(key)
    return items if isinstance(items, list) else []


def _condition_rule(cond: Any) -> tuple[str, str] | None:
    """Read one Condition node as an `(operator, value)` rule.

    Args:
        cond: A candidate Condition node, or any other value.

    Returns:
        `(Operator, str(RHSValue))`, or `None` when `cond` is not a Condition
        node carrying a string `Operator`.
    """
    if isinstance(cond, dict) and isinstance(cond.get("Operator"), str):
        return (cond["Operator"], str(cond.get("RHSValue")))
    return None


def _criteria_conditions(read_back: Draft, cid: str) -> set[tuple[str, str]]:
    """Every `(operator, value)` rule live under one Criteria node.

    Args:
        read_back: The flow's wire-format draft (a read-back, for the audit).
        cid: The Criteria node's id.

    Returns:
        Every rule its `Criteria::Condition` children resolve to.
    """
    out: set[tuple[str, str]] = set()
    for condid in _node_child_ids(read_back, cid, "Criteria::Condition"):
        rule = _condition_rule(read_back.get(condid))
        if rule is not None:
            out.add(rule)
    return out


def _field_live_rules(
    read_back: Draft, field_node: dict[str, Any]
) -> set[tuple[str, str]]:
    """Every validation rule live on one Field node.

    Args:
        read_back: The flow's wire-format draft (a read-back, for the audit).
        field_node: The Field node to inspect.

    Returns:
        The union of every Criteria's rules the field's
        `FieldValidation::Criteria` list points at.
    """
    criteria_ids = field_node.get("FieldValidation::Criteria")
    if not isinstance(criteria_ids, list):
        return set()
    live: set[tuple[str, str]] = set()
    for cid in criteria_ids:
        live.update(_criteria_conditions(read_back, cid))
    return live


def _field_map(draft: Draft) -> dict[str, dict[str, Any]]:
    """Every Field node on the draft, keyed by its `Name`.

    Args:
        draft: The flow's wire-format draft.

    Returns:
        `{field name: field node}`.
    """
    out: dict[str, dict[str, Any]] = {}
    for v in draft.values():
        if isinstance(v, dict) and v.get("Kind") == "Field":
            out[v.get("Name")] = v
    return out


def _audit_all_field_rules(
    read_back: Draft,
    rules: dict[str, list[tuple[str, str]]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Flatten every requested rule and check which ones landed.

    Args:
        read_back: The flow's wire-format draft (a read-back, for the audit).
        rules: `{field name: [(operator, value), ...]}`, as requested.

    Returns:
        `(flat, verified)`: every requested rule in order, and the subset
        confirmed live on the read-back.
    """
    by_name = _field_map(read_back)
    flat: list[tuple[str, str]] = []
    verified: list[tuple[str, str]] = []
    for fname, fl_rules in rules.items():
        flat.extend(fl_rules)
        live = _field_live_rules(read_back, by_name.get(fname, {}))
        for rule in fl_rules:
            if rule in live:
                verified.append(rule)
    return flat, verified


def _calc_missing(
    flat: list[tuple[str, str]],
    verified: list[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    """The requested rules that did not verify.

    Args:
        flat: Every requested rule, in order.
        verified: The subset confirmed live.

    Returns:
        `flat` minus `verified`, in `flat`'s own order.
    """
    verified_set = set(verified)
    missing: list[tuple[str, str]] = []
    for r in flat:
        if r not in verified_set:
            missing.append(r)
    return tuple(missing)
