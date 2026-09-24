"""`.env.example` parses safely with python-dotenv (P1 review finding 1).

python-dotenv keeps a trailing inline comment as the VALUE when the key itself is left
empty (`KEY=   # comment` -> the value is the literal string `"# comment"`), so a
verbatim copy of the old template handed `KF_DEV_ACCOUNT_ID` the string `"# required"`
and `MCP_HTTP` the string `"# optional; ..."` -- both truthy. `Settings`' "required key"
check passed with that junk account id, and `bool(os.getenv("MCP_HTTP"))` came out
`True`, so a server started from an unedited copy silently ran streamable-http on
0.0.0.0:8080 with no in-app auth (D1) instead of the intended stdio default. The fix is
structural: no comment ever shares a line with a key, so there is nothing left for the
parser to eat.
"""

from __future__ import annotations

import pathlib

from dotenv import dotenv_values

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
ENV_EXAMPLE = REPO_ROOT / ".env.example"

# The keys `load_settings()` (app.infrastructure.config.settings) treats as optional.
# PORT and HTTP_TIMEOUT_SECONDS are deliberately NOT in this list: they already ship a
# literal default that matches the code's own `os.getenv("X", "<default>")` fallback,
# and blanking them would trade this defect for a different one -- an env var that is
# PRESENT but empty is not "absent" to `os.getenv(key, default)`, so
# `int(os.getenv("PORT", "8080"))` would raise `ValueError` on a verbatim copy instead
# of falling back to 8080.
OPTIONAL_BLANK_KEYS = (
    "KF_APP",
    "KF_PROCESS_TEMPLATE",
    "MCP_HTTP",
    "KF_DEV_ACCESS_KEY_ID",
    "KF_DEV_ACCESS_KEY_SECRET",
)


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), f"expected a template at {ENV_EXAMPLE}"


def test_no_value_contains_a_comment_marker() -> None:
    """An inline `#` on the same line as a key is exactly the shape python-dotenv
    mis-parses when that key is left empty -- so no parsed value may contain one, full
    stop, whether or not the key happens to carry a value too."""
    values = dotenv_values(ENV_EXAMPLE)
    offenders = {k: v for k, v in values.items() if v and "#" in v}
    assert not offenders, f"an inline comment leaked into a value: {offenders}"


def test_every_optional_key_ships_empty() -> None:
    """An optional key ships blank, never a value that looks "filled in" and could be
    copied unreviewed straight into a running deployment."""
    values = dotenv_values(ENV_EXAMPLE)
    for key in OPTIONAL_BLANK_KEYS:
        assert values.get(key) == "", (
            f"{key} should ship empty in the template, got {values.get(key)!r}"
        )


def test_kf_dev_domain_placeholder_is_not_a_live_vendor_domain() -> None:
    """The example domain is an RFC 2606 reserved placeholder, never `kissflow.com` --
    copying the template verbatim must never aim real traffic at a real tenant."""
    values = dotenv_values(ENV_EXAMPLE)
    domain = values.get("KF_DEV_DOMAIN") or ""
    assert "dev-" in domain
    assert "kissflow.com" not in domain
    assert domain.endswith((".example.com", ".example.org", ".example.net", ".invalid"))
