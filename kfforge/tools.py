"""Framework-agnostic tool logic (dict in / dict out). Offline + compliant.

Kept separate from server.py so the logic is testable without the MCP framework.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .engine import plan_change
from .graph import _section_members, progressive_matrix
from .types import FieldSpec, FieldType, Visibility


def list_field_types() -> list[str]:
    """The closed catalog of valid field types — the guard against 'wrong type' errors."""
    return [t.value for t in FieldType]


def _to_spec(d: dict[str, Any]) -> FieldSpec:
    return FieldSpec(
        name=d["name"],
        type=FieldType(d["type"]),  # raises on unknown type -> rejected
        required=bool(d.get("required", False)),
        referred_list=d.get("referred_list"),
        field_id=d.get("field_id"),
    )


def plan_step_visibility(draft: dict[str, Any], owners: dict[str, list[str]]) -> dict[str, Any]:
    """DRY-RUN preview (offline): which section is Editable/ReadOnly/Hidden at which step.

    Returns a per-section tally plus the step name each section is editable at, which is the part a
    human can actually check by eye. Writes nothing, makes no network call.
    """
    matrix = progressive_matrix(draft, owners)
    acts = {k: v.get("Name", k) for k, v in draft.items()
            if isinstance(v, dict) and v.get("Kind") == "Activity"}
    out: dict[str, Any] = {"sections": {}, "permission_nodes": 0}
    for section, row in matrix.items():
        tally = Counter(v.value for v in row.values())
        out["sections"][section] = {
            "editable_at": sorted(acts.get(a, a) for a, v in row.items() if v is Visibility.EDITABLE),
            **{k.lower(): c for k, c in tally.items()},
        }
    members = _section_members(draft)
    by_name = {v["Name"]: k for k, v in draft.items()
               if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Section"}
    out["permission_nodes"] = sum(len(members.get(by_name[s], [])) * len(r)
                                  for s, r in matrix.items() if s in by_name)
    return out


def plan_field_change(draft: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """DRY-RUN preview (offline): what adding these fields would do. Writes nothing."""
    diff = plan_change(draft, [_to_spec(c) for c in changes])
    return {
        "adds": [
            {"name": s.name, "type": FieldType(s.type).value, "required": s.required}
            for s in diff.adds
        ],
        "edits": [{"name": s.name} for s in diff.edits],
        "skipped": list(diff.skipped),
        "human_readable": diff.human_readable,
    }
