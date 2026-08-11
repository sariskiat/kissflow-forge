"""Direct (non-MCP) reads against the live Kissflow dev tenant, shared by the `live`-marked suites.

Mirrors the old tests/robot/ForgeKeywords.py "direct (non-MCP) reads" section — the same few facts
(`_current_step`, `_status`, the full item detail, live field/assignee ids) that forge_simulate_case's
own WalkReport never carries, because it echoes the PLANNED step names and never reads them back
(CLAUDE.md > THE RULE: an echo of the plan proves nothing about what actually landed).

Called in-process (no MCP/STDIO transport) — `kfforge.server`'s tool functions are plain Python
functions once imported (proven by tests/test_p2_server.py: `getattr(srv, name)(**kwargs)`), so a
live acceptance test can call them directly instead of going through the wire protocol a real MCP
client would use. The wire protocol itself (schema-building, JSON-RPC framing) already has its own
offline coverage in test_p2_server.py; these tests exist to prove the tenant-facing behavior, which
direct calls exercise identically.
"""
from __future__ import annotations

import os
import pathlib
from typing import Any

import kfforge.server as srv
from kfforge.client import Err, KfClient, KfConfig
from kfforge.dataplane import LiveDataPlane

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / ".env"


def load_env_file(path: str | pathlib.Path | None = None) -> None:
    """Parse `KEY=VALUE` lines from `.env` (repo root by default) into this process's `os.environ`.
    An already-set key is left untouched — same "already-exported wins" precedence as
    `set -a; . ./.env; set +a`.
    """
    env_path = pathlib.Path(path) if path else DEFAULT_ENV_FILE
    if not env_path.is_file():
        raise FileNotFoundError(f"no .env file at {env_path}")
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _live_data_plane() -> LiveDataPlane:
    cfg = KfConfig.from_env()
    if isinstance(cfg, Err):
        raise RuntimeError(f"KfConfig.from_env failed: {cfg.message}")
    return LiveDataPlane(KfClient(cfg))


def resolve_field_ids(flow_id: str, kind: str = "process") -> dict[str, str]:
    """{field NAME: field ID} for every Field node on the flow's LIVE draft. forge_simulate_case's
    `values` payload must be keyed by field ID, never name (CLAUDE.md > Item data plane)."""
    draft = srv.kf_get_flow_schema(flow_kind=kind, flow_id=flow_id)
    if draft.get("isError"):
        raise RuntimeError(f"could not fetch draft to resolve field ids: {draft}")
    return {
        node["Name"]: node_id for node_id, node in draft.items()
        if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Name")
    }


def resolve_assigned_role_ids(flow_id: str, kind: str = "process") -> list[str]:
    """Live read-back of every step's real AppRole assignee (Resource nodes), in
    ProcessDef::Activity order — forge_build_workflow's own `assigned` is an echo of the input,
    never proof of what actually landed (CLAUDE.md > Members first)."""
    draft = srv.kf_get_flow_schema(flow_kind=kind, flow_id=flow_id)
    if draft.get("isError"):
        raise RuntimeError(f"could not fetch draft to resolve assignee resources: {draft}")
    return [
        node["Value"] for node in draft.values()
        if isinstance(node, dict) and node.get("Kind") == "Resource"
        and node.get("ValueType") == "AppRole" and isinstance(node.get("Value"), str)
    ]


def get_item_status(flow_id: str, iid: str) -> str:
    """STRICT: raises if `_status` is missing — right for proving a real regression."""
    detail = _live_data_plane().get_detail(flow_id, iid)
    if isinstance(detail, Err):
        raise RuntimeError(f"get_detail({flow_id!r}, {iid!r}) failed: {detail.message}")
    status = detail.get("_status")
    if not isinstance(status, str):
        raise TypeError(f"detail had no string _status field: {detail!r}")
    return status


def get_current_step(flow_id: str, iid: str) -> str:
    """STRICT: raises if `_current_step` is missing. Wrong choice for a case where the field is
    LEGITIMATELY absent — use get_item_detail for that (see the fail-open negative-control test)."""
    detail = _live_data_plane().get_detail(flow_id, iid)
    if isinstance(detail, Err):
        raise RuntimeError(f"get_detail({flow_id!r}, {iid!r}) failed: {detail.message}")
    step = detail.get("_current_step")
    if not isinstance(step, str):
        raise TypeError(f"detail had no string _current_step field: {detail!r}")
    return step


def get_item_detail(flow_id: str, iid: str) -> dict[str, Any]:
    """General-purpose escape hatch: never raises on a missing key, unlike get_current_step/
    get_item_status. An item that skips a whole conditional Parallel has NO `_current_step` key at
    all (CLAUDE.md > Conditional routing's fail-open warning) — that's a legitimate value to
    observe, not a bug to hide behind a raise."""
    detail = _live_data_plane().get_detail(flow_id, iid)
    if isinstance(detail, Err):
        raise RuntimeError(f"get_detail({flow_id!r}, {iid!r}) failed: {detail.message}")
    return detail
