"""Robot Framework keyword library for kissflow-forge's MCP server (Node G acceptance layer).

Talks to `kfforge.server` over the REAL Model Context Protocol, using fastmcp's Client (confirmed
via `chub search fastmcp` / `chub get fastmcp/package` before writing this file — see the DEV
report's transport-decision log for the full reasoning). Design choices, each deliberate:

  STDIO transport, not in-memory.
      fastmcp's docs list three Client shapes: `Client(FastMCP(...))` (in-memory, "best for
      tests"), `Client("script.py")` (STDIO subprocess), `Client("http://...")` (HTTP). In-memory
      needs the SAME Python process to hold both the Client and the FastMCP server object — not
      available here, since Robot Framework runs this library in ITS OWN interpreter, separate
      from wherever `kfforge.server.mcp` would need to live. STDIO is therefore the only fit for
      "a keyword library talks to the MCP server" from an external RF process — also the plan's
      own stated preference. Confirmed working end-to-end (list_tools, call_tool, keep_alive reuse
      across two separate `async with` blocks) via a standalone smoke test BEFORE this file was
      written (scratchpad/smoke_stdio_client.py, kept out of the repo).

  The exact `.mcp.json` invocation, not a hand-rolled one.
      `uv run --with fastmcp --no-project python -m kfforge.server` is the SAME command
      `.mcp.json` already uses for every normal Claude Code session in this repo — reusing it
      means zero new untested invocation surface. Built via `fastmcp.client.transports.
      StdioTransport` directly (not the higher-level `UvStdioTransport` convenience class, whose
      own `--directory` flag is semantically different from `--no-project` and was not worth
      cross-checking against uv's project-detection behavior when reusing the proven string is
      strictly safer).

  Explicit `env=` on the transport.
      fastmcp's docs warn STDIO subprocesses do not inherit the parent's environment
      automatically; reading `mcp.client.stdio.get_default_environment` directly confirmed WHY —
      when `env=None` it only forwards a small POSIX safelist (HOME/LOGNAME/PATH/SHELL/TERM/USER),
      deliberately excluding secrets. `load_env_file` parses THIS repo's own `.env` into this
      process's `os.environ`; `connect_to_forge_server` then forwards a full `os.environ` copy
      (PATH/HOME for `uv` itself, plus every KF_DEV_*/KF_APP) to the subprocess.

  ONE Client, built once, reused for the whole suite.
      `StdioTransport`'s own `keep_alive=True` default means the spawned server subprocess stays
      alive across many short-lived `async with client:` blocks — each keyword opens and closes
      one such block per call (RF keywords are synchronous; fastmcp's Client is async, so every
      keyword bridges with a single `asyncio.run(...)`), but the underlying `uv run ...` process is
      spawned exactly once, at Suite Setup, and reused by every keyword after that.

  A GENERIC `Call Forge Tool` keyword, not 18 near-duplicate per-tool wrappers.
      Every forge_*/kf_* tool already has a clear, self-documenting name and a JSON-schema'd
      signature on the SERVER side (kfforge/server.py); re-declaring each one's parameter list a
      second time here would be pure duplication with real drift risk (a signature change in
      server.py silently going stale here). The .robot suite instead calls
      `Call Forge Tool    <tool_name>    key=value    ...`, which is at least as readable as a
      "living behavior spec" — the tool name appearing verbatim in the test text IS the spec,
      audit-able without cross-referencing this file — and can never drift out of sync with the
      server's actual tool surface. Two small assertion helpers (`Result Should Not Error` /
      `Result Should Error`) are the only other custom keywords, because the same isError-checking
      pattern would otherwise repeat at every one of the suite's ~15 call sites.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

# tests/robot/ForgeKeywords.py -> parent (tests/robot) -> parent (tests) -> parent (worktree root)
WORKTREE_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_ENV_FILE = WORKTREE_ROOT / ".env"
MIN_FORGE_TOOLS = 18

# StdioTransport's `log_file` defaults to `sys.stderr` when omitted (mcp.client.stdio's own
# stdio_client(..., errlog=sys.stderr) default) -- subprocess.Popen then calls `.fileno()` on
# whatever that is. Robot Framework replaces sys.stderr with its own log-capturing stream during
# a test run, which has NO real OS file descriptor, so `.fileno()` raises AttributeError with
# exactly the message "'...' object has no attribute 'fileno'" (confirmed by reproducing it
# standalone before this fix — a bare FakeRFStream() swapped onto sys.stderr breaks the SAME way).
# A real file sidesteps this entirely; the MCP server subprocess's own stderr (mostly its startup
# banner and INFO logs) lands there instead of interleaving with Robot's own output.
_MCP_SERVER_STDERR_LOG = pathlib.Path(tempfile.gettempdir()) / "kfforge_forge_lifecycle_mcp_stderr.log"


class ForgeKeywords:
    """Robot Framework keyword library for the kissflow-forge MCP server."""

    ROBOT_LIBRARY_SCOPE = "TEST SUITE"

    def __init__(self) -> None:
        self._client: Client | None = None

    # ------------------------------------------------------------------ connection lifecycle

    def load_env_file(self, path: str | None = None) -> None:
        """Parse `KEY=VALUE` lines from `.env` (repo root by default) into THIS process's
        `os.environ`. Blank lines and `#` comments are skipped. A key already present in
        `os.environ` (e.g. exported by the calling shell) is left untouched — the same
        "already-exported wins" precedence `set -a; . ./.env; set +a` has.
        """
        env_path = pathlib.Path(path) if path else DEFAULT_ENV_FILE
        if not env_path.is_file():
            raise FileNotFoundError(f"no .env file at {env_path}")
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value

    def connect_to_forge_server(self) -> None:
        """Suite Setup: build the STDIO transport (the exact `.mcp.json` invocation) and open the
        fastmcp Client. Requires `KF_APP` to already be set (`Load Env File`, or the calling shell)
        — fails loud immediately rather than silently talking to a misconfigured server. Also does
        ONE real round trip (`list_tools`) right away, so a broken connection or a server missing
        tools fails at Suite Setup, not confusingly on the first real test step.
        """
        if not os.environ.get("KF_APP"):
            raise RuntimeError("KF_APP is not set — call Load Env File first (or source .env)")
        transport = StdioTransport(
            command="uv",
            args=["run", "--with", "fastmcp", "--no-project", "python", "-m", "kfforge.server"],
            cwd=str(WORKTREE_ROOT),
            env=dict(os.environ),
            log_file=_MCP_SERVER_STDERR_LOG,
        )
        self._client = Client(transport)
        names = asyncio.run(self._list_tool_names())
        forge_count = sum(1 for n in names if n.startswith("forge_"))
        if forge_count < MIN_FORGE_TOOLS:
            raise RuntimeError(
                f"expected >= {MIN_FORGE_TOOLS} forge_* tools, server exposes {forge_count}: "
                f"{sorted(names)}"
            )

    def disconnect_from_forge_server(self) -> None:
        """Suite Teardown (part 1 — call LAST, after artifact cleanup): best-effort close. Any
        error here is logged, never raised — a teardown failure must never mask an earlier test
        failure or hide whether artifact cleanup itself succeeded.
        """
        if self._client is None:
            return
        try:
            asyncio.run(self._client.close())
        except Exception as exc:  # noqa: BLE001 — teardown: log, never raise over a real failure
            print(f"*WARN* ForgeKeywords: error closing the MCP client: {exc}")
        self._client = None

    async def _list_tool_names(self) -> list[str]:
        assert self._client is not None
        async with self._client:
            tools = await self._client.list_tools()
        return [t.name for t in tools]

    # ------------------------------------------------------------------ generic tool call

    def call_forge_tool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """Call ANY forge_*/kf_* tool by name (see kfforge/server.py for the full surface and each
        tool's exact parameter names/types), return its result dict. `${result}=    Call Forge
        Tool    forge_create_process    name=Sample Intake Process` in a .robot file.
        """
        if self._client is None:
            raise RuntimeError("not connected — call Connect To Forge Server first")
        return asyncio.run(self._call(tool_name, kwargs))

    async def _call(self, tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        assert self._client is not None
        async with self._client:
            result = await self._client.call_tool(tool_name, kwargs)
        data = result.data
        return data if isinstance(data, dict) else {"raw": data, "isError": False}

    # ------------------------------------------------------------------ field-id resolution

    def resolve_field_ids(self, flow_id: str, kind: str = "process") -> dict[str, str]:
        """Fetch the flow's draft (`kf_get_flow_schema`) and return {field NAME: field ID} for
        every Field node on it.

        forge_simulate_case's `values` payload MUST be keyed by field ID, never by the
        human-readable name — CLAUDE.md Item data plane's own route table says so explicitly
        (`fill PUT .../admin/{flow}/{iid} -> {field_id: value, ...}`), and the live server
        confirms it: PUTting a values dict keyed by name fails with `KISSFLOW_ERROR_01003
        FieldNotFound` ("The field <name> does not exist in the flow <model>"). This keyword is
        the one place that graph-parsing logic lives, so the .robot file never has to walk a raw
        draft dict itself.
        """
        draft = self.call_forge_tool("kf_get_flow_schema", flow_kind=kind, flow_id=flow_id)
        if draft.get("isError"):
            raise RuntimeError(f"could not fetch draft to resolve field ids: {draft}")
        out: dict[str, str] = {}
        for node_id, node in draft.items():
            if isinstance(node, dict) and node.get("Kind") == "Field" and node.get("Name"):
                out[node["Name"]] = node_id
        return out

    def resolve_assigned_role_ids(self, flow_id: str, kind: str = "process") -> list[str]:
        """Fetch the flow's draft and return the `Value` (AppRole id) of every `Resource` node
        with `ValueType == "AppRole"` — a REAL read-back of who a workflow step is actually
        assigned to, in `ProcessDef::Activity` order.

        `forge_build_workflow`'s own `assigned` field is an ECHO of the INPUT `steps` list
        (kfforge/client.py `apply_workflow`: `assigned = tuple(name for name, role in steps if
        role)`) — it can never be empty or wrong as long as the CALLER passed a role, so asserting
        on it proves nothing about what actually landed. This keyword reads the live graph
        instead, the same way `resolve_field_ids` does for fields.
        """
        draft = self.call_forge_tool("kf_get_flow_schema", flow_kind=kind, flow_id=flow_id)
        if draft.get("isError"):
            raise RuntimeError(f"could not fetch draft to resolve assignee resources: {draft}")
        return [
            node["Value"] for node in draft.values()
            if isinstance(node, dict) and node.get("Kind") == "Resource"
            and node.get("ValueType") == "AppRole" and isinstance(node.get("Value"), str)
        ]

    # ------------------------------------------------------------------ direct (non-MCP) reads

    def get_item_status(self, flow_id: str, iid: str) -> str:
        """Direct (non-MCP) read of a runtime item's OWN `_status` field, via
        `kfforge.dataplane.LiveDataPlane`. Not exposed as an MCP tool — `forge_simulate_case`'s
        own result has no status field (its WalkReport only tracks which step NAMES advanced/
        rejected/failed, never the item's final runtime status) — so this keyword reads it
        directly through the SAME kfforge package the MCP server itself wraps, reusing its proven
        client/config rather than re-implementing the HTTP call here. Used by
        forge_lifecycle.robot's final step to assert the walked item actually reached Completed,
        not just that every individual submit call returned 200 (CLAUDE.md > THE RULE: a 200
        proves nothing on its own).

        `kfforge.client`/`kfforge.dataplane` pull in ZERO third-party packages (plain stdlib +
        internal modules only) but ARE a local, uninstalled package — Robot Framework's own
        interpreter has no reason to already have WORKTREE_ROOT on sys.path. Imported HERE,
        function-local, rather than at module level: a module-level import needs `sys.path`
        mutated first, which E402-flags the import — a local import sidesteps that cleanly, with
        no `noqa` needed under any ruleset.
        """
        if str(WORKTREE_ROOT) not in sys.path:
            sys.path.insert(0, str(WORKTREE_ROOT))
        from kfforge.client import Err, KfClient, KfConfig
        from kfforge.dataplane import LiveDataPlane

        cfg = KfConfig.from_env()
        if isinstance(cfg, Err):
            raise TypeError(f"KfConfig.from_env failed: {cfg.message}")
        detail = LiveDataPlane(KfClient(cfg)).get_detail(flow_id, iid)
        if isinstance(detail, Err):
            raise TypeError(f"get_detail({flow_id!r}, {iid!r}) failed: {detail.message}")
        status = detail.get("_status")
        if not isinstance(status, str):
            raise TypeError(f"detail had no string _status field: {detail!r}")
        return status

    def get_current_step(self, flow_id: str, iid: str) -> str:
        """Direct (non-MCP) read of a runtime item's OWN `_current_step` field — the SAME pattern
        as `get_item_status`, reading a different key. `forge_simulate_case`'s own WalkReport is an
        ECHO of the planned step NAMES (dataplane.walk() appends `plan.name` on success, never
        reads it back from the item — same caveat `resolve_assigned_role_ids`'s docstring already
        flags for a different field), so it can never prove WHICH branch an item actually landed
        on after crossing a conditional Parallel — only a live read of the item's own
        `_current_step` can. Used by forge_branching.robot (Node M, conditional routing) to prove
        two items with different values of the deciding field land on genuinely DIFFERENT steps —
        the real proof; a branch that never fires looks identical to one that works until you read
        this (CLAUDE.md > THE RULE).
        """
        if str(WORKTREE_ROOT) not in sys.path:
            sys.path.insert(0, str(WORKTREE_ROOT))
        from kfforge.client import Err, KfClient, KfConfig
        from kfforge.dataplane import LiveDataPlane

        cfg = KfConfig.from_env()
        if isinstance(cfg, Err):
            raise TypeError(f"KfConfig.from_env failed: {cfg.message}")
        detail = LiveDataPlane(KfClient(cfg)).get_detail(flow_id, iid)
        if isinstance(detail, Err):
            raise TypeError(f"get_detail({flow_id!r}, {iid!r}) failed: {detail.message}")
        step = detail.get("_current_step")
        if not isinstance(step, str):
            raise TypeError(f"detail had no string _current_step field: {detail!r}")
        return step

    def get_item_detail(self, flow_id: str, iid: str) -> dict[str, Any]:
        """Direct (non-MCP) read of a runtime item's FULL admin detail dict — the general-purpose
        escape hatch `get_item_status`/`get_current_step` intentionally are not: both are STRICT
        (raise if the field they want is missing or not a string), which is exactly right for
        proving a real bug on the CORE divergence proof (test 10 — a None `_current_step` there
        would be a genuine regression), but wrong for a test that needs to observe a value that is
        LEGITIMATELY absent. Node M review (2026-08-07): a deciding-field value matching no branch
        condition leaves an item with NO `_current_step` at all (it skipped the whole Parallel and
        completed) — `get_current_step` would raise on that by design, so the no-match test in
        forge_branching.robot reads the raw detail here instead and asserts on it directly
        (`${detail}[_current_step]` / `${detail}[_status]` via Robot's own dict-item syntax).
        """
        if str(WORKTREE_ROOT) not in sys.path:
            sys.path.insert(0, str(WORKTREE_ROOT))
        from kfforge.client import Err, KfClient, KfConfig
        from kfforge.dataplane import LiveDataPlane

        cfg = KfConfig.from_env()
        if isinstance(cfg, Err):
            raise TypeError(f"KfConfig.from_env failed: {cfg.message}")
        detail = LiveDataPlane(KfClient(cfg)).get_detail(flow_id, iid)
        if isinstance(detail, Err):
            raise TypeError(f"get_detail({flow_id!r}, {iid!r}) failed: {detail.message}")
        return detail

    # ------------------------------------------------------------------ assertion helpers

    def result_should_not_error(self, result: dict[str, Any], context: str = "") -> None:
        """Fail loud with the FULL result dict on isError — never just "something failed"."""
        if result.get("isError"):
            raise AssertionError(f"{context}: tool call reported isError=True: {result}")

    def result_should_error(self, result: dict[str, Any], context: str = "") -> None:
        """The inverse — for the documented-limitation branches this suite must assert
        EXPLICITLY (e.g. a submit 403 on missing AppRole membership), never silently skip."""
        if not result.get("isError"):
            raise AssertionError(f"{context}: expected isError=True, got: {result}")
