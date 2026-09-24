"""Classifying an Expression node's owner — the one context-free piece of the
Kissflow branch-condition / goto-gate AST.

Moved verbatim from the former offline domain expression module (G9b). The
rest of that module's public surface takes a whole node-graph and became
`FlowDraft` methods
(`app.domain.entities.flow_draft`); this function takes a single node dict, so
it stays a plain value-object-level helper with no entity to hang off.

An Expression's owner key is one of three, each meaning something different
(CLAUDE.md Expressions): `ProcessDef` = a branch condition, `Activity` = a
GotoTask loop condition, `Property` = a value-generator prefix (e.g. a
SequenceNumber scheme). `expression_owner` is the one place that
classification is made; every mutating operation on a condition branches off
it.
"""

from __future__ import annotations

from typing import Any


def expression_owner(node: dict[str, Any]) -> str:
    """Classify an Expression node by its owner key.

    Args:
        node: One `Expression`-kind node from a flow's node graph.

    Returns:
        `"branch"` when the node is `ProcessDef`-owned, `"goto"` when it is
        `Activity`-owned, or `"property"` when it is `Property`-owned.

    Raises:
        ValueError: The node carries zero or more than one of
            `ProcessDef`/`Activity`/`Property` (CLAUDE.md Expressions: "Always
            branch on which key is present before treating an Expression as
            routing logic") — a malformed or ambiguous node is never silently
            misclassified.
    """
    present = [
        name
        for key, name in (
            ("ProcessDef", "branch"),
            ("Activity", "goto"),
            ("Property", "property"),
        )
        if key in node
    ]
    if len(present) != 1:
        raise ValueError(
            f"Expression {node.get('Id', node)!r} has {len(present)} owner key(s) "
            f"among ProcessDef/Activity/Property, expected exactly 1"
        )
    return present[0]
