"""Behaviour proof for the connector outage: does the app believe the proxy's X-Forwarded-Proto?

Claude Desktop refuses the deployed endpoint because a GET on the trailing-slash /mcp/ answers
307 with an `http://` location -- a scheme downgrade. The proxy handling that decides that scheme
lives in uvicorn's ProxyHeadersMiddleware, which wraps the ASGI app at serve time; it is NOT part
of the fastmcp app, so driving `mcp.http_app()` on its own exercises none of it. These tests
compose the middleware over the real MCP HTTP surface and drive it with an explicitly chosen
client address, which makes the untrusted-peer case reachable with no Docker, cluster, or network.

uvicorn only honours X-Forwarded-Proto from peers listed in `forwarded_allow_ips`, which defaults
to `127.0.0.1` alone and is read from the FORWARDED_ALLOW_IPS environment variable. The Istio
sidecar delivers from 127.0.0.6, so the default distrusts it and uvicorn concludes the request
arrived over plain HTTP. The Dockerfile now ships FORWARDED_ALLOW_IPS=* (asserted in
tests/test_p0_scaffold.py, so the artefact and this behaviour cannot drift apart).

The loopback case below is kept deliberately: it explains why the earlier ngrok comparison masked
the bug. A tunnel delivers from 127.0.0.1, which is trusted even under the default, so the
tunnelled deployment answered `https://` while the meshed one did not -- the app looked fine and
the difference looked like a mesh problem rather than a trust-list problem.
"""

from __future__ import annotations

import asyncio

import httpx
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app.infrastructure.mcp.server as srv

MESH_PEER = "172.17.0.1"  # stands in for the Istio sidecar's 127.0.0.6: any non-loopback peer
LOOPBACK_PEER = "127.0.0.1"


def _redirect(trusted_hosts: str, peer: str) -> tuple[int, str | None]:
    """GET the trailing-slash /mcp/ through ProxyHeadersMiddleware from `peer`; return (status, location)."""
    # Both stubs describe the ASGI callable structurally and neither starlette's app nor this
    # middleware matches that spelling exactly. Runtime is fine — these very tests drive real
    # requests through both — so the mismatch is in the stubs, not the wiring.
    app = ProxyHeadersMiddleware(srv.mcp.http_app(), trusted_hosts=trusted_hosts)  # ty: ignore[invalid-argument-type]
    transport = httpx.ASGITransport(app=app, client=(peer, 12345))  # ty: ignore[invalid-argument-type]

    async def _go() -> tuple[int, str | None]:
        async with httpx.AsyncClient(transport=transport, base_url="http://kf.example") as client:
            resp = await client.get(
                "/mcp/",
                headers={
                    "host": "kf.example",
                    "x-forwarded-proto": "https",
                    "x-forwarded-for": peer,
                },
            )
        return resp.status_code, resp.headers.get("location")

    return asyncio.run(_go())


def test_untrusted_peer_downgrades_the_scheme_the_production_outage():
    """Default trust list + a mesh-delivered request: the proxy is disbelieved, location is http."""
    assert _redirect("127.0.0.1", MESH_PEER) == (307, "http://kf.example/mcp")


def test_wildcard_trust_keeps_the_scheme_the_fix():
    """FORWARDED_ALLOW_IPS=* : the same mesh-delivered request now redirects to https."""
    assert _redirect("*", MESH_PEER) == (307, "https://kf.example/mcp")


def test_loopback_peer_is_trusted_even_by_default_why_the_tunnel_masked_it():
    """A tunnel (ngrok) delivers from loopback, which the default list already trusts -- so the
    tunnelled endpoint answered https and the bug stayed invisible in that comparison."""
    assert _redirect("127.0.0.1", LOOPBACK_PEER) == (307, "https://kf.example/mcp")
