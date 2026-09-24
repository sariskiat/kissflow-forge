"""Private helpers for `ForgeAddGotoGate`.

Ported from `app.infrastructure.kissflow.client`'s `_parallel_branches` /
`_describe_owner` / `_resolve_activity_by_name` (refactor spec, Stage D group
`d3_flow_workflow`). Each one used to return `Err("verify", ...)`; here each
raises `ApplicationError(..., code=VERIFY_FAILED)` instead (spec G6's mapping
for `Err("verify")`), so a caller loses the write before it starts, the same
way it always has, just as an exception instead of a sentinel.
"""

from __future__ import annotations

from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError


def _parallel_branches(wire: dict[str, Any]) -> dict[str, str]:
    """The flow's single Parallel gateway's branches, as {branch NAME: branch
    ProcessDef id}.

    Requires EXACTLY ONE Parallel Activity on the draft -- fails loud rather
    than guessing which one a caller meant when there is more than one, and
    matches `FlowDraft.build_workflow`'s own ceiling of a single `parallel`
    gateway per flow. A branch name that is not unique across the gateway's
    own `ProcessDef::Expression` list is ALSO refused rather than silently
    keeping only the last match.

    Args:
        wire: The flow's draft node graph.

    Returns:
        Branch name -> branch ProcessDef id.

    Raises:
        ApplicationError: Not exactly one Parallel gateway, or two branches
            share a name (`code=VERIFY_FAILED`).
    """
    parallels = [
        v
        for v in wire.values()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("NodeType") == "Parallel"
    ]
    if len(parallels) != 1:
        raise ApplicationError(
            f"expected exactly one Parallel gateway on the flow, found "
            f"{len(parallels)}",
            code=VERIFY_FAILED,
        )
    names: list[str] = []
    out: dict[str, str] = {}
    for pd_id in parallels[0].get("Activity::ProcessDef") or []:
        pd = wire.get(pd_id)
        name = pd.get("Name") if isinstance(pd, dict) else None
        if not isinstance(name, str):
            continue
        names.append(name)
        out[name] = pd_id
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ApplicationError(
            f"ambiguous branch name(s) on the Parallel gateway: {dupes}",
            code=VERIFY_FAILED,
        )
    return out


def _describe_owner(wire: dict[str, Any], pd_id: str | None) -> str:
    """Human-readable label for a ProcessDef, for an ambiguity error message: its
    branch Name if it's a branch, "the root chain" if it's the root Sequence
    ProcessDef, or the raw id as a last resort."""
    pd = wire.get(pd_id) if isinstance(pd_id, str) else None
    if isinstance(pd, dict):
        name = pd.get("Name")
        if isinstance(name, str):
            return f"branch {name!r}"
        if pd.get("WorkflowType") == "Sequence":
            return "the root chain"
    return f"ProcessDef {pd_id!r}"


def _resolve_activity_by_name(
    wire: dict[str, Any],
    name: str,
    *,
    process_def_id: str | None = None,
) -> str:
    """Resolve an Activity by NAME, raising on ambiguity rather than silently taking
    the first match by dict iteration order.

    `process_def_id`, when given, scopes the search to ONE ProcessDef's own
    activities; omitted, the search spans the whole draft, and an ambiguity
    across branches -- or between a branch and the root chain -- is exactly
    the case `branch_name` exists to resolve. The error message names every
    candidate's owning branch (or "the root chain"), never just a bare count.

    Args:
        wire: The flow's draft node graph.
        name: The Activity name to resolve.
        process_def_id: Scope the search to this ProcessDef alone.

    Returns:
        The resolved Activity's node id.

    Raises:
        ApplicationError: No Activity named `name` resolves (in scope, when
            given), or more than one does (`code=VERIFY_FAILED`).
    """
    candidates = [
        k
        for k, v in wire.items()
        if isinstance(v, dict)
        and v.get("Kind") == "Activity"
        and v.get("Name") == name
        and (process_def_id is None or v.get("ProcessDef") == process_def_id)
    ]
    if not candidates:
        where = f" in {_describe_owner(wire, process_def_id)}" if process_def_id else ""
        raise ApplicationError(
            f"no workflow step named {name!r}{where}", code=VERIFY_FAILED
        )
    if len(candidates) > 1:
        owners = sorted(
            {
                _describe_owner(wire, wire.get(c, {}).get("ProcessDef"))
                for c in candidates
            }
        )
        raise ApplicationError(
            f"step name {name!r} is ambiguous — it exists in {len(candidates)} "
            f"places ({', '.join(owners)}); pass branch_name to disambiguate which "
            f"one you mean",
            code=VERIFY_FAILED,
        )
    return candidates[0]
