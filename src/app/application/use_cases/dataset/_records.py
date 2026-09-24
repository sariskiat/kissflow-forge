"""Pure field-name resolution for `ForgeDatasetRecords`.

Ported from `app.infrastructure.kissflow.dataplane.field_name_index` /
`.resolve_value_keys` (pre-refactor). A dataform record's KEYS accept a field
NAME or a field id for create/update -- the raw route 404s FieldNotFound on a
name key -- so these two are copied here rather than imported from
`app.application.use_cases.item._walk` (a different family's private
module; CLAUDE.md > lesson 11 -- only `use_cases/flow/_write_order.py` is
shared across families).
"""

from __future__ import annotations

from typing import Any


def _root_model_ids(draft: dict[str, Any]) -> set[str]:
    """Model node ids that are the form's own root model, not a child table.

    A child-table Model carries a host `Column` back-reference (CLAUDE.md >
    Tables); the root model does not.

    Args:
        draft: The dataform's wire-format draft.

    Returns:
        Every root-model node id.
    """
    return {
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Model" and not v.get("Column")
    }


def field_name_index(draft: dict[str, Any]) -> dict[str, str]:
    """name -> field id, for every root-model Field in a dataform's draft graph.

    Scoped to root-model fields on purpose: a child-table field can share a
    display name with a root field, and a dataform record route only ever
    addresses root-model fields.

    Args:
        draft: The dataform's wire-format draft.

    Returns:
        Every root-model field's `Name` mapped to its id.
    """
    roots = _root_model_ids(draft)
    out: dict[str, str] = {}
    for key, node in draft.items():
        if not isinstance(node, dict) or node.get("Kind") != "Field":
            continue
        if node.get("Model") not in roots:
            continue
        name = node.get("Name")
        if isinstance(name, str) and name:
            fid = node.get("Id")
            out[name] = fid if isinstance(fid, str) and fid else key
    return out


def resolve_value_keys(
    values: dict[str, object],
    field_index: dict[str, str],
    passthrough: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Translate a record dict's KEYS (field name or field id) to field ids,
    leaving every VALUE untouched.

    A key already shaped like a field id (`Field_...` prefix) or matching a
    known live field id is kept as-is; any other key is looked up as a field
    NAME. Mixed names and ids in one dict are fine.

    Args:
        values: The record dict as the caller supplied it.
        field_index: `name -> id`, from `field_name_index`.
        passthrough: Extra keys allowed through verbatim without being
            treated as field names -- the dataform record route's synthetic
            system `"Name"` key, which is a column id, not a display name.

    Returns:
        `values` with every key resolved to a field id.

    Raises:
        ValueError: A key matches no field -- names the unresolved key and
            lists every available field name.
    """
    known_ids = set(field_index.values())
    resolved: dict[str, object] = {}
    for key, val in values.items():
        if key in passthrough or key.startswith("Field_") or key in known_ids:
            resolved[key] = val
        elif key in field_index:
            resolved[field_index[key]] = val
        else:
            available = ", ".join(sorted(field_index)) or "(none)"
            raise ValueError(
                f"fill key {key!r} matches no field on this flow — not a "
                f"field id, and no field is named {key!r}. Available field "
                f"names: {available}"
            )
    return resolved
