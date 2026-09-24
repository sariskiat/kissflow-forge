"""Private helpers for `ForgeSetBranchConditions`.

Ported from `app.infrastructure.kissflow.client`'s `_literals_for_field` /
`_uncovered_options` (refactor spec, Stage D group `d3_flow_workflow`).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _literals_for_field(wire: dict[str, Any], pd_id: str, field_id: str) -> set[str]:
    """Every literal a branch ProcessDef's OWN condition(s) compare `field_id`
    against -- normally 0 or 1, but read as a set defensively. Filters to
    conditions ON `field_id` specifically -- a branch conditioned on some other
    field is not part of this field's coverage picture at all."""
    out: set[str] = set()
    pd = wire.get(pd_id) or {}
    for eid in pd.get("ProcessDef::Expression") or []:
        e = wire.get(eid) or {}
        for root_id in e.get("Expression::Node") or []:
            children = [
                wire.get(c) or {}
                for c in (wire.get(root_id) or {}).get("Node::Node") or []
            ]
            if not any(
                c.get("Type") == "Field" and c.get("Field") == field_id
                for c in children
            ):
                continue
            for c in children:
                if c.get("Type") == "Static" and isinstance(c.get("Value"), str):
                    out.add(c["Value"])
    return out


def _uncovered_options(
    wire: dict[str, Any],
    branch_pd_ids: Iterable[str],
    field_id: str,
    options: list[str] | None,
) -> tuple[str, ...]:
    """Real Select options that NO branch among `branch_pd_ids` currently conditions
    on `field_id`. `options=None` (a non-Select or list-less deciding field) has no
    enumerable option universe to check against, so this returns `()`, meaning
    "nothing checked," not "fully covered."""
    if options is None:
        return ()
    covered: set[str] = set()
    for pd_id in branch_pd_ids:
        covered |= _literals_for_field(wire, pd_id, field_id)
    return tuple(o for o in options if o not in covered)
