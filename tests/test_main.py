"""The composition root — `app.main:main`, which is what the container's CMD actually runs.

Nothing covered this before: the module sat at 0%, while the Dockerfile depends on exactly one
of its behaviours (MCP_HTTP flipping stdio to streamable-http, and PORT being honoured so Cloud
Run can override it). A silent change here breaks the deployed server and no test would notice.

`mcp.run` is replaced rather than called: the real one blocks forever serving traffic.
"""

from typing import Any

import pytest

import app.main as main_mod
from app.infrastructure.kissflow.auth import CaptureTokenBody


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Intercept the one call main() makes, so the transport decision is observable."""
    seen: dict[str, Any] = {}

    def _fake_run(*args: Any, **kwargs: Any) -> None:
        seen["args"], seen["kwargs"] = args, kwargs

    monkeypatch.setattr(main_mod.mcp, "run", _fake_run)
    monkeypatch.delenv("MCP_HTTP", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    return seen


def test_without_mcp_http_it_runs_stdio(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local/process mode: no transport argument at all, which is fastmcp's stdio default."""
    main_mod.main()
    assert captured["args"] == ()
    assert captured["kwargs"] == {}, "stdio mode must pass no transport/host/port"


def test_mcp_http_selects_streamable_http_on_all_interfaces(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_HTTP", "1")
    main_mod.main()
    kw = captured["kwargs"]
    assert kw["transport"] == "streamable-http"
    assert kw["host"] == "0.0.0.0", "must bind every interface — Cloud Run health-checks it"
    assert kw["port"] == 8080, "the Dockerfile's ENV PORT default"


def test_mcp_http_installs_the_token_capturing_middleware(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """CaptureTokenBody is what makes the per-user Kissflow client secret reachable from static
    lookup on the /token path; without it HTTP auth cannot complete."""
    monkeypatch.setenv("MCP_HTTP", "1")
    main_mod.main()
    middleware = captured["kwargs"]["middleware"]
    assert len(middleware) == 1
    assert middleware[0].cls is CaptureTokenBody


def test_port_env_overrides_the_default(
    captured: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cloud Run assigns the port at runtime; an image default that ignored it would never serve."""
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
