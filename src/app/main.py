"""Composition root: the one place the process is assembled and started.

The MCP adapter (`app.infrastructure.mcp.server`) owns the tool surface and nothing else;
choosing a transport and binding a port is a deployment decision, so it lives here. Entry
points: `mcp-server` (see [project.scripts]) and `python -m app.main`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP

from app.infrastructure.config.settings import load_settings
from app.infrastructure.mcp.lifespan import app_lifespan
from app.infrastructure.mcp.server import create_server


def main() -> None:
    """Assemble and run the server.

    `load_settings()` runs first and unconditionally, so a missing or
    invalid env var stops the process at boot, naming it -- not at the
    first tool call (spec G2). The lifespan wraps `app_lifespan` in an
    `asynccontextmanager`, the shape `create_server` (and FastMCP itself)
    expects. Transport is the one deployment decision: `settings.mcp_http`
    selects streamable HTTP on every interface (Cloud Run); otherwise the
    process serves stdio, for local work and the live suites.
    """
    settings = load_settings()

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> Any:
        async with app_lifespan(server, settings) as context:
            yield context

    server = create_server(lifespan)
    if settings.mcp_http:
        server.run(transport="http", host="0.0.0.0", port=settings.port)
    else:
        server.run()


if __name__ == "__main__":  # pragma: no cover
    main()
