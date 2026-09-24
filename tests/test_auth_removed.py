"""Proves auth left the repo (refactor spec G3, D1).

SRE's Entra gateway sits in front of the public endpoint now, so this server
carries no auth provider and no OAuth module at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastmcp import FastMCP

import app.infrastructure.mcp.server as srv


@asynccontextmanager
async def _fake_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    del server
    yield {"resources": None, "settings": None}


def test_server_has_no_auth_provider() -> None:
    """The FastMCP server `create_server` builds carries no auth provider, and
    the module keeps no OAuth provider global at all -- not even one that
    resolves to `None`."""
    server = srv.create_server(_fake_lifespan)

    assert server.auth is None
    assert not hasattr(srv, "_oauth"), (
        "the OAuth provider global should be gone, not just None"
    )


def test_auth_module_is_gone() -> None:
    """`app.infrastructure.kissflow.auth` no longer exists -- the module was deleted."""
    with pytest.raises(ModuleNotFoundError):
        import app.infrastructure.kissflow.auth  # noqa: F401  # ty: ignore[unresolved-import]
