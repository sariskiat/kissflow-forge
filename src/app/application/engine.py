"""Offline planning. Apply/publish orchestration lands here later (GATED by §2 sign-off)."""

from __future__ import annotations

from typing import Any

from app.domain.graph import apply_changes, field_names
from app.domain.types import Diff, FieldSpec, FieldType

Draft = dict[str, Any]


def plan_change(draft: Draft, changes: list[FieldSpec]) -> Diff:
    """Dry-run: describe what apply WOULD do, without writing or calling Kissflow.

    Feasibility is PROVEN by computing the resulting graph offline (so preview == apply);
    the computed graph is discarded. Read-only w.r.t. the input; no network.
    Invalid types / unsupported edits raise (fail loud) just as apply does.
    """
    _ = apply_changes(draft, changes)  # validate + prove feasibility; discard result

    existing = field_names(draft)
    adds = tuple(s for s in changes if s.field_id is None and s.name not in existing)
    edits = tuple(s for s in changes if s.field_id is not None)
    skipped = tuple(s.name for s in changes if s.name in existing)
    lines = [
        f"+ add field '{s.name}' ({FieldType(s.type).value}, "
        f"{'required' if s.required else 'optional'})"
        for s in adds
    ]
    if skipped:
        lines.append(f"= skip {len(skipped)} existing: {', '.join(skipped)}")
    return Diff(
        adds=adds,
        edits=edits,
        skipped=skipped,
        human_readable="\n".join(lines) or "(no changes)",
    )
