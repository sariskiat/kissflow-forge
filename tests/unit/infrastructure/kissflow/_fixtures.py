"""Shared config fixtures for the adapter test suites (`test_flow.py`, `test_app.py`,
...).

One fixed domain/account/key pair, used to build the `Settings`/adapter, so every
adapter test file builds its fixtures the same way. Not itself an adapter or a port
fake -- a private test helper living entirely under `tests/`, so the mirror rule
(`tests_mirror_src`) does not apply to it.

Stage E deleted `app.infrastructure.kissflow.client` (the whole point of the switch):
the `old_client()` builder this module used to export, for the differential tests'
live OLD-client half, is gone with it. `_differential.py`'s `assert_differential` now
reads the OLD half from the committed `tests/fixtures/recorded/<family>/<method>.json`
fixture instead of calling a live OLD client.
"""

from __future__ import annotations

import httpx

from app.infrastructure.config.settings import Settings

DOMAIN = "dev-acme.kissflow.com"
ACCOUNT = "ACC1"
KEY_ID = "key-1"
KEY_SECRET = "secret-1"  # gitleaks:allow
BASE_URL = f"https://{DOMAIN}"


def settings() -> Settings:
    """Build the `Settings` the NEW adapters read (account id, stdio key pair).

    Returns:
        A `Settings` targeting `DOMAIN`/`ACCOUNT` with `KEY_ID`/`KEY_SECRET`.
    """
    return Settings(
        kf_dev_domain=DOMAIN,
        kf_dev_account_id=ACCOUNT,
        kf_app=None,
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id=KEY_ID,
        kf_dev_access_key_secret=KEY_SECRET,
        http_timeout_seconds=10.0,
    )


def assert_invariant(
    request_host: str, request_scheme: str, headers: httpx.Headers
) -> None:
    """Assert one outbound request against the G8 invariant.

    Args:
        request_host: `request.url.host`.
        request_scheme: `request.url.scheme`.
        headers: `request.headers` (case-insensitive).

    Raises:
        AssertionError: The request does not target `DOMAIN` over `https`,
            or does not carry both signed headers.
    """
    assert request_host == DOMAIN
    assert request_scheme == "https"
    assert headers["x-access-key-id"] == KEY_ID
    assert headers["x-access-key-secret"] == KEY_SECRET
