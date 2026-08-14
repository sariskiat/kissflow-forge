"""Framework-agnostic tool logic (dict in / dict out). Offline + compliant.

Kept separate from server.py so the logic is testable without the MCP framework.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .engine import plan_change
from .graph import progressive_matrix, section_layout
from .types import FieldSpec, FieldType, Visibility


def list_field_types() -> list[str]:
    """The closed catalog of valid field types — the guard against 'wrong type' errors."""
    return [t.value for t in FieldType]


def _to_spec(d: dict[str, Any]) -> FieldSpec:
    # `default_value` (#55, forge_apply_fields extension) is a convenience top-level key that
    # folds into `options["DefaultValue"]` — the SAME wire key `_TYPE_DEFAULTS` already writes for
    # Number, and the platform's own relative-date keyword ("Today") for Date. Absent when not
    # given, so every caller that never used it sees byte-identical FieldSpec.options to before.
    options = dict(d.get("options") or {})
    if d.get("default_value") is not None:
        options["DefaultValue"] = d["default_value"]
    return FieldSpec(
        name=d["name"],
        type=FieldType(d["type"]),  # raises on unknown type -> rejected
        required=bool(d.get("required", False)),
        referred_list=d.get("referred_list"),
        field_id=d.get("field_id"),
        options=options or None,  # opt-in per-type keys (AllowFormatting/CaptureOnly/…)
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
    # the REAL pair count the writer will emit: per matrix row, the section's member columns
    # minus the columns the writer skips (no-Permission columns and table hosts — #9, Tables).
    # Field-level overrides would add their own rows, but this preview takes no field_matrix,
    # so nothing is subtracted for them. Sharing section_layout with the writer is what keeps
    # this count truthful (it used to count every member column, silently over-reporting by
    # one column x every step whenever a section held a hidden or SequenceNumber column).
    layout = section_layout(draft)
    out["permission_nodes"] = sum(
        len([c for c in layout.members.get(layout.section_id_of_name.get(s, ""), ())
             if c not in layout.no_permission_columns and c not in layout.table_host_columns])
        * len(r)
        for s, r in matrix.items() if s in layout.section_id_of_name
    )
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
