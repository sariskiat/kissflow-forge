"""Pure read-back audit helpers for `ForgeAddTable`.

Copied from `app.infrastructure.kissflow.client`'s `_is_table_host`,
`_find_table_host`, `_table_model_node`, `_table_child_field_names`,
`_table_live_columns` and `_audit_table_columns` (pre-refactor), adapted to
read a `FlowDraft.to_wire()` dict instead of the old client's raw draft dict
-- the shape is identical, only the source of the dict changed (CLAUDE.md >
lesson 3: never read an entity's `.nodes` from outside the domain; `to_wire()`
gives a safe copy instead).
"""

from __future__ import annotations

from typing import Any

Draft = dict[str, Any]


def _is_table_host(node: Any, name: str) -> bool:
    """True when `node` is the Column hosting a child table named `name`.

    Args:
        node: A candidate node from the draft, or any other value.
        name: The table name to match.

    Returns:
        Whether `node` is a `Type: "Model"` Column with that `Name`.
    """
    if not isinstance(node, dict):
        return False
    return node.get("Type") == "Model" and node.get("Name") == name


def _find_table_host(draft: Draft, name: str) -> dict[str, Any] | None:
    """Find the host Column for a child table named `name`.

    Args:
        draft: The flow's wire-format draft.
        name: The table name to find.

    Returns:
        The host Column node, or `None` when no table of that name exists.
    """
    for node in draft.values():
        if _is_table_host(node, name):
            return node
    return None


def _table_model_node(draft: Draft, host_col: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a table host Column's nested Model node.

    Args:
        draft: The flow's wire-format draft.
        host_col: The host Column node, as `_find_table_host` returns it.

    Returns:
        The nested Model node, or `None` when the host carries no
        `Column::Model` reference (or the reference does not resolve).
    """
    table_ids = host_col.get("Column::Model", [])
    if not table_ids:
        return None
    node = draft.get(table_ids[0])
    if isinstance(node, dict):
        return node
    return None


def _table_child_field_names(draft: Draft, table_node: dict[str, Any]) -> set[str]:
    """The names of every child Field the table's Model actually carries.

    Args:
        draft: The flow's wire-format draft.
        table_node: The table's nested Model node.

    Returns:
        Every child field's `Name`, skipping a malformed or unresolved
        `Model::Field` entry rather than raising.
    """
    field_ids = table_node.get("Model::Field", [])
    names: set[str] = set()
    for fid in field_ids:
        field = draft.get(fid)
        if isinstance(field, dict):
            name = field.get("Name")
            if name is not None:
                names.add(name)
    return names


def _table_live_columns(draft: Draft, name: str) -> set[str]:
    """The live child column names of the table named `name`.

    Args:
        draft: The flow's wire-format draft (a read-back, for the audit).
        name: The table name to inspect.

    Returns:
        The live child column names, or the empty set when the table, its
        Model node, or both are missing or malformed.
    """
    host = _find_table_host(draft, name)
    if host is None:
        return set()
    table_node = _table_model_node(draft, host)
    if table_node is None:
        return set()
    return _table_child_field_names(draft, table_node)


def _audit_table_columns(
    wanted: tuple[str, ...],
    live: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition the wanted column names into verified and missing.

    Args:
        wanted: Every column name the caller asked to add, in order.
        live: The column names actually present on the read-back.

    Returns:
        `(verified, missing)`, a complete partition of `wanted` -- every
        name lands in exactly one bucket (the output-invariant audit).
    """
    verified: list[str] = []
    missing: list[str] = []
    for col in wanted:
        if col in live:
            verified.append(col)
        else:
            missing.append(col)
    return tuple(verified), tuple(missing)
