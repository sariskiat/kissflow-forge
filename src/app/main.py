"""Composition root: the one place the process is assembled and started.

The MCP adapter (`app.infrastructure.mcp.server`) owns the tool surface and nothing else;
choosing a transport and binding a port is a deployment decision, so it lives here. Entry
points: `mcp-server` (see [project.scripts]) and `python -m app.main`.
"""

from __future__ import annotations

import os

from starlette.middleware import Middleware as ASGIMiddleware

from app.infrastructure.kissflow.auth import CaptureTokenBody
from app.infrastructure.mcp.server import mcp


def main() -> None:
    if os.environ.get("MCP_HTTP"):
        # auth_provider_from_env() has already failed closed during server-module import if any
        # HTTP auth setting is missing. CaptureTokenBody makes the client secret available to
        # static lookup; it is harmless on every non-token path.
        mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8080")),
            middleware=[ASGIMiddleware(CaptureTokenBody)],
        )
    else:
        mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
