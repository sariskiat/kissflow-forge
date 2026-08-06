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
