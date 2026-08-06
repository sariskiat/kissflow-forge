"""Kissflow Builder MCP server.

Write/publish are LIVE as of the §2 compliance sign-off (Kissflow AUP §1.10, 2026-08-03) and are
DEV-ONLY by construction: kfforge.client reads only KF_DEV_* and refuses any domain without "dev-".
Every write is read-verify-write with a post-write read-back audit. See PLAN.md / FINDINGS.md.
"""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from . import tools
from .client import (
    Err,
    KfClient,
    KfConfig,
    apply_fields,
    apply_step_permissions,
    create_process,
)
from .graph import progressive_matrix
from .tools import _to_spec

mcp = FastMCP("kissflow-forge")


def _client() -> KfClient | Err:
    cfg = KfConfig.from_env()
    return cfg if isinstance(cfg, Err) else KfClient(cfg)


@mcp.tool()
def kf_list_field_types() -> list[str]:
    """List valid Kissflow field types (closed enum; prevents wrong-type errors)."""
    return tools.list_field_types()


@mcp.tool()
def kf_plan_field_change(draft: dict[str, Any], changes: list[dict[str, Any]]) -> dict[str, Any]:
    """DRY-RUN: preview adding fields to a flow's draft graph. Offline; writes nothing."""
    return tools.plan_field_change(draft, changes)


@mcp.tool()
def kf_get_flow_schema(flow_kind: str, flow_id: str) -> dict[str, Any]:
    """Read a flow's DRAFT graph from the dev tenant. Read-only."""
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    got = c.get_draft(flow_kind, flow_id)  # type: ignore[arg-type]
    return got.as_tool_result() if isinstance(got, Err) else got


@mcp.tool()
def kf_apply_field_change(
    flow_kind: str,
    flow_id: str,
    changes: list[dict[str, Any]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only): add fields to a flow, verify by read-back, optionally publish.

    Idempotent — a field whose name already exists is skipped, never duplicated. Aborts with a
    conflict if the draft changed since it was read. Show kf_plan_field_change to a human first.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    specs = [_to_spec(ch) for ch in changes]
    report = apply_fields(c, flow_kind, flow_id, specs, publish=publish)  # type: ignore[arg-type]
    return report.as_tool_result()


@mcp.tool()
def kf_create_process(
    name: str,
    steps: list[str],
    fields: list[dict[str, Any]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE (dev only): create a NEW process from zero — workflow steps + fields — and verify it.

    `steps` are the UserTask names in order; Start and Completed are added automatically. A failed
    run cleans up after itself and leaves no half-built process behind.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    specs = [_to_spec(f) for f in fields]
    report = create_process(c, name, tuple(steps), specs, publish=publish)
    return report.as_tool_result()


@mcp.tool()
def kf_plan_step_visibility(draft: dict[str, Any], owners: dict[str, list[str]]) -> dict[str, Any]:
    """DRY-RUN: preview per-step section visibility. `owners` maps a section NAME to the step names
    that own it. Offline; writes nothing. Show this to a human before kf_set_step_visibility."""
    return tools.plan_step_visibility(draft, owners)


@mcp.tool()
def kf_set_step_visibility(
    flow_id: str,
    owners: dict[str, list[str]],
    publish: bool = False,
) -> dict[str, Any]:
    """LIVE write (dev only): rebuild a process's per-step section visibility.

    A section is Editable at the steps that own it, Hidden before them, ReadOnly after. Kissflow has
    no section-level permission, so this writes one Permission node per (field column x step).
    DESTRUCTIVE: every existing Permission on the flow is replaced. Snapshot the draft first.
    """
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    draft = c.get_draft("process", flow_id)
    if isinstance(draft, Err):
        return draft.as_tool_result()
    try:
        matrix = progressive_matrix(draft, owners)
    except ValueError as e:
        return Err("verify", str(e)).as_tool_result()
    return apply_step_permissions(c, flow_id, matrix, publish=publish).as_tool_result()


@mcp.tool()
def kf_publish(flow_kind: str, flow_id: str) -> dict[str, Any]:
    """LIVE publish (dev only): compile the flow's draft graph to its live version."""
    c = _client()
    if isinstance(c, Err):
        return c.as_tool_result()
    got = c.publish(flow_kind, flow_id)  # type: ignore[arg-type]
    return got.as_tool_result() if isinstance(got, Err) else {"published": True, "flow_id": flow_id}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
