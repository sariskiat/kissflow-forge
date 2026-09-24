"""P0 acceptance: blindness, severed umbilical, explicit app, server boots."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent
SKIP_DIRS = {".git", "__pycache__", ".venv", ".ruff_cache", "node_modules"}
TEXT_EXT = {".py", ".json", ".md", ".robot", ".toml", ".txt", ".yml", ".yaml", ".cfg"}
# Case-insensitive "cli"+"nic" and "ai"+"case" subsume the old underscore/concatenated
# tokens AND close the dash/space/possessive + app-abbreviation gaps the case-sensitive
# ones missed -- a green scan now really means blind. Tokens built by concatenation so
# this file's own source stays grep-clean.
FORBIDDEN = re.compile(
    "|".join(["cli" + "nic", "ai" + "case", "cP" + "5", "คลิ" + "นิก"]), re.IGNORECASE
)


def _repo_text_files():
    for p in ROOT.rglob("*"):
        if any(part in SKIP_DIRS or part.startswith(".env") for part in p.parts):
            continue
        if p.is_file() and p.suffix in TEXT_EXT and p.name != "test_p0_scaffold.py":
            yield p


def test_blindness_no_real_app_tokens():
    hits = [
        str(p)
        for p in _repo_text_files()
        if FORBIDDEN.search(p.read_text(errors="ignore"))
    ]
    assert hits == [], f"real-app knowledge leaked into: {hits}"


def test_no_kfmcp_references():
    hits = [
        str(p)
        for p in _repo_text_files()
        if p.suffix == ".py" and ("kf" + "mcp") in p.read_text(errors="ignore")
    ]
    assert hits == [], f"umbilical to old repo not severed: {hits}"


def test_client_requires_explicit_app(monkeypatch):
    """App is no longer required at config load — it can be chosen per call (app_id) or via
    the `KF_APP` env default. But a use case that needs an app still refuses loud when none
    resolves ("The app id", `brief_stage_d_common.md`) -- the guard moved from the old
    `server._client()` chokepoint to `Settings.resolve_app_id` plus each family's own
    `require_app_id` helper, proven per-tool by every `tests/unit/application/use_cases/*/
    test__app_id.py`/`test_forge_*.py` "no app selected" case; this test pins the config-level
    half of that rule."""
    from app.infrastructure.config.settings import load_settings

    monkeypatch.setenv("KF_DEV_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "s")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "a")
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-example.test")
    monkeypatch.delenv("KF_APP", raising=False)
    monkeypatch.delenv("MCP_HTTP", raising=False)

    # config load now succeeds with no app configured at all (no boot-time lock)
    settings = load_settings()
    assert settings.kf_app is None
    # with no per-call override and no KF_APP default, resolution is empty -- the empty
    # string every family's own require_app_id helper refuses on
    assert settings.resolve_app_id(None) == ""
    # a per-call override flows through regardless of the configured default
    assert settings.resolve_app_id("App_X") == "App_X"


def test_image_declares_forwarded_allow_ips():
    """The shipped image must carry FORWARDED_ALLOW_IPS=*, or the deployed endpoint 307s Claude
    Desktop to an http:// location and the connector refuses it. tests/test_proxy_headers.py
    proves the mechanism; this assertion proves it is switched on in the artefact that ships, so
    the two cannot drift apart. A run-time value still overrides an image default."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert re.search(r"^ENV\b.*\bFORWARDED_ALLOW_IPS=\*", dockerfile, re.MULTILINE), (
        "Dockerfile ENV line must declare FORWARDED_ALLOW_IPS=*"
    )


def test_server_exposes_original_8_tools():
    import asyncio
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from typing import Any

    from fastmcp import Client, FastMCP

    from app.infrastructure.mcp.server import create_server

    @asynccontextmanager
    async def _fake_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": None, "settings": None}

    async def _tool_names() -> set[str]:
        async with Client(create_server(_fake_lifespan)) as client:
            return {t.name for t in await client.list_tools()}

    expected = {
        "kf_list_field_types",
        "kf_plan_field_change",
        "kf_get_flow_schema",
        "kf_apply_field_change",
        "kf_create_process",
        "kf_plan_step_visibility",
        "kf_set_step_visibility",
        "kf_publish",
    }
    found = asyncio.run(_tool_names())
    missing = expected - found
    assert not missing, f"tools missing from the server's tool surface: {missing}"
