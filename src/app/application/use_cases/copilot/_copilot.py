"""The app-scoped flow inventory, for `ForgeCopilotCheck`.

Ported from `app.infrastructure.kissflow.client._flow_id_inventory`
(pre-refactor): the same app-scoped inventory `forge_sweep`'s "flows" bucket
reads, factored out so `forge_copilot_check` can diff against it without
duplicating the leakage-safe scoping.
"""

from __future__ import annotations

from app.application.exceptions import RepositoryError
from app.application.interfaces.flow import FlowRepository
from app.domain.value_objects.kinds import AnyFlowKind

#: Every flow kind this engine can create. Copied from
#: `app.infrastructure.kissflow.client._SWEEP_FLOW_KINDS` rather than
#: imported: that name is private to the flow family's own module, and
#: CLAUDE.md > lesson 11 only allows importing another family's private
#: helper for `use_cases/flow/_write_order.py`.
_SWEEP_FLOW_KINDS: tuple[AnyFlowKind, ...] = (
    "process",
    "form",
    "case",
    "list",
    "dataset",
)


async def flow_id_inventory(
    flow: FlowRepository, app_id: str
) -> dict[AnyFlowKind, list[str]]:
    """Every flow id in the application, across every kind this engine can
    create.

    Args:
        flow: The flow/process/form/case/list family port.
        app_id: The application to inventory.

    Returns:
        `{kind: [flow id, ...]}`, one entry per kind in
        `_SWEEP_FLOW_KINDS`, an app with none returning `[]` for that kind.

    Raises:
        RepositoryError: A `list_flows` call failed.
    """
    out: dict[AnyFlowKind, list[str]] = {}
    for kind in _SWEEP_FLOW_KINDS:
        got = await flow.list_flows(app_id, kind)
        out[kind] = [
            f["_id"]
            for f in got
            if isinstance(f, dict) and isinstance(f.get("_id"), str)
        ]
    return out


async def node_count(
    flow: FlowRepository, app_id: str, kind: AnyFlowKind, flow_id: str
) -> int:
    """A cheap top-level node COUNT for one flow's draft, never a semantic diff.

    A per-flow draft-read failure is not fatal to the caller's own inventory
    diff (mirrors `apply_copilot_check`'s own `-1 = read failed` sentinel,
    pre-refactor): only this one flow's count is affected.

    Args:
        flow: The flow/process/form/case/list family port.
        app_id: The application the flow belongs to.
        kind: The flow kind.
        flow_id: The flow's id.

    Returns:
        The draft's top-level node count, or `-1` when the read failed.
    """
    try:
        draft = await flow.get_draft(app_id, kind, flow_id)
    except RepositoryError:
        return -1
    return len(draft.to_wire())
