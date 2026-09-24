"""Private helpers for `ForgeBuildWorkflow`.

Ported from `app.infrastructure.kissflow.client`'s `_sequence_step_stamps` and
the damage-audit half of `apply_workflow` (refactor spec, Stage D group
`d3_flow_workflow`). See `_permissions.py`'s module docstring for why these
take a wire `dict` rather than a `FlowDraft` -- the same reasoning applies
here.
"""

from __future__ import annotations

from typing import Any


def _sequence_step_stamps(wire: dict[str, Any]) -> dict[str, str | None]:
    """SequenceNumber field NAME -> the NAME of the activity its `Step` stamp points
    at.

    `None` means the stamp is DANGLING (the activity id it holds is not a node
    in this draft) -- a `build_workflow` rebuild silently repoints a stranded
    stamp at StartEvent rather than leaving it dangling (a dangling stamp is a
    deterministic publish failure). Reported by NAME, not by id, because a
    workflow rebuild changes every activity id.
    """
    act_names = {
        k: v.get("Name")
        for k, v in wire.items()
        if isinstance(v, dict) and v.get("Kind") == "Activity"
    }
    out: dict[str, str | None] = {}
    for node in wire.values():
        if not (
            isinstance(node, dict)
            and node.get("Kind") == "Field"
            and node.get("Type") == "SequenceNumber"
        ):
            continue
        for pid in node.get("Field::Property") or []:
            prop = wire.get(pid) or {}
            if prop.get("Name") == "Step":
                out[node.get("Name", "")] = act_names.get(prop.get("Value"))
    return out
