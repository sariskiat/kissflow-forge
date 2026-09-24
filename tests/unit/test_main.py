"""The composition root -- `app.main:main`, which is what the container's
CMD actually runs.

Ported from the pre-Stage-E `tests/test_main.py` onto the
`create_server(lifespan)` shape (spec G12): `main()` now builds the server
through `create_server`, wrapping `app_lifespan` in an `asynccontextmanager`,
rather than calling a module-level `mcp.run()`. `create_server` and
`app_lifespan` are replaced in these tests so no real FastMCP instance or httpx
pool is built; the real one blocks forever serving traffic.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

import app.main as main_mod


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Intercept the one call main() makes, so the transport decision is observable."""
    seen: dict[str, Any] = {}
    fake_server = MagicMock()

    def _fake_run(*args: Any, **kwargs: Any) -> None:
        seen["args"], seen["kwargs"] = args, kwargs

    fake_server.run = _fake_run
    monkeypatch.setattr(main_mod, "create_server", lambda lifespan: fake_server)
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")
    monkeypatch.delenv("MCP_HTTP", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    return seen


def test_without_mcp_http_it_runs_stdio(captured: dict[str, Any]) -> None:
    """Local/process mode: no transport argument at all, which is fastmcp's
    stdio default."""
    main_mod.main()
    assert captured["args"] == ()
    assert captured["kwargs"] == {}, "stdio mode must pass no transport/host/port"


def test_mcp_http_selects_http_on_all_interfaces(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_HTTP", "1")
    main_mod.main()
    kw = captured["kwargs"]
    assert kw["transport"] == "http"
    assert kw["host"] == "0.0.0.0", (
        "must bind every interface — Cloud Run health-checks it"
    )
    assert kw["port"] == 8080, "the Dockerfile's ENV PORT default"


def test_mcp_http_installs_no_middleware(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auth left the repo with app.infrastructure.kissflow.auth (D1) -- SRE's
    gateway does Entra now, so main() wires no ASGI middleware at all,
    token-capturing or otherwise."""
    monkeypatch.setenv("MCP_HTTP", "1")
    main_mod.main()
    assert "middleware" not in captured["kwargs"]


def test_port_env_overrides_the_default(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cloud Run assigns the port at runtime; an image default that ignored it
    would never serve."""
    monkeypatch.setenv("MCP_HTTP", "1")
    monkeypatch.setenv("PORT", "9137")
    main_mod.main()
    assert captured["kwargs"]["port"] == 9137


def test_port_is_passed_as_an_int_not_a_string(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_HTTP", "1")
    monkeypatch.setenv("PORT", "9137")
    main_mod.main()
    assert isinstance(captured["kwargs"]["port"], int)


def test_missing_kf_dev_domain_stops_boot_and_names_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """load_settings() runs before create_server()/server.run(), so a missing
    key stops the process at boot -- not at the first tool call (spec G2)."""
    monkeypatch.delenv("KF_DEV_DOMAIN", raising=False)
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    with pytest.raises(RuntimeError, match="KF_DEV_DOMAIN"):
        main_mod.main()


@pytest.mark.asyncio
async def test_main_wires_the_lifespan_create_server_was_built_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifespan `create_server` receives wraps `app_lifespan` -- connecting
    through it actually drives `app_lifespan`'s context manager open and closed,
    yielding its context."""
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")
    monkeypatch.delenv("MCP_HTTP", raising=False)

    fake_server = MagicMock()
    fake_server.run = MagicMock()
    captured_lifespan: list[Any] = []

    def _fake_create_server(lifespan: Any) -> Any:
        captured_lifespan.append(lifespan)
        return fake_server

    fake_context = {"resources": "test"}

    @asynccontextmanager
    async def _fake_app_lifespan(server: Any, settings: Any) -> Any:
        del server, settings
        yield fake_context

    monkeypatch.setattr(main_mod, "create_server", _fake_create_server)
    monkeypatch.setattr(main_mod, "app_lifespan", _fake_app_lifespan)

    main_mod.main()

    lifespan = captured_lifespan[0]
    async with lifespan(MagicMock(spec=FastMCP)) as ctx:
        assert ctx == fake_context
