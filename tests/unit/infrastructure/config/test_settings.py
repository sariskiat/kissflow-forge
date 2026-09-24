"""Settings is the one reader of the environment (refactor spec G2).

A missing required key stops the process at boot and names the key; a non-dev domain is
refused by construction (HR1).
"""

from __future__ import annotations

import pytest

from app.infrastructure.config.settings import Settings, load_settings


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")


def test_load_settings_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("KF_APP", "app-1")
    monkeypatch.setenv("KF_PROCESS_TEMPLATE", "tmpl-1")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("MCP_HTTP", "1")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_ID", "key-1")
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "secret-1")  # gitleaks:allow
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "5.5")

    settings = load_settings()

    assert settings.kf_dev_domain == "dev-kissflow.example.com"
    assert settings.kf_dev_account_id == "acct-1"
    assert settings.kf_app == "app-1"
    assert settings.kf_process_template == "tmpl-1"
    assert settings.port == 9000
    assert settings.mcp_http is True
    assert settings.kf_dev_access_key_id == "key-1"
    assert settings.kf_dev_access_key_secret == "secret-1"
    assert settings.http_timeout_seconds == 5.5


def test_load_settings_calls_load_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """`load_settings()` itself calls `load_dotenv()`, as the clone's does."""
    calls: list[None] = []
    monkeypatch.setattr(
        "app.infrastructure.config.settings.load_dotenv", lambda: calls.append(None)
    )
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    load_settings()

    assert calls == [None]


def test_missing_kf_dev_domain_names_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.delenv("KF_DEV_DOMAIN", raising=False)
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    with pytest.raises(RuntimeError, match="KF_DEV_DOMAIN"):
        load_settings()


def test_missing_kf_dev_account_id_names_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-kissflow.example.com")
    monkeypatch.delenv("KF_DEV_ACCOUNT_ID", raising=False)

    with pytest.raises(RuntimeError, match="KF_DEV_ACCOUNT_ID"):
        load_settings()


def test_non_dev_domain_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", "kissflow.example.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    with pytest.raises(RuntimeError, match="refusing non-dev domain"):
        load_settings()


# ======================================================================
# HR1 hostname shape (P1 review finding 2): `"dev-" in domain` on the whole
# string let a path, a comment, or userinfo smuggle "dev-" past the guard
# while the host the client actually connects to was something else
# entirely -- `acme.kissflow.com/dev-` is a non-dev host with a "dev-" path
# segment, not a dev host. `KF_DEV_DOMAIN` must be a bare hostname first;
# only THEN is it checked for "dev-".
# ======================================================================


@pytest.mark.parametrize(
    "domain",
    [
        "acme.kissflow.com/dev-",  # a path segment, not the host
        "acme.kissflow.com#dev-",  # a fragment, not the host
        "acme.kissflow.com # dev-",  # a trailing comment, not the host
        "dev-acme.kissflow .com",  # whitespace inside the value
        " dev-acme.kissflow.com",  # leading whitespace
        "dev-acme.kissflow.com ",  # trailing whitespace
        "dev-acme@kissflow.com",  # userinfo separator
        "https://dev-acme.kissflow.com",  # a scheme
        "dev-acme.kissflow.com:8080",  # a port
        "dev-acme.kissflow.com?x=dev-",  # a query string
    ],
    ids=[
        "path-segment",
        "fragment",
        "trailing-comment",
        "internal-whitespace",
        "leading-whitespace",
        "trailing-whitespace",
        "userinfo",
        "scheme",
        "port",
        "query-string",
    ],
)
def test_kf_dev_domain_rejects_anything_but_a_bare_hostname(
    monkeypatch: pytest.MonkeyPatch, domain: str
) -> None:
    """Each of these shapes contains the substring "dev-" somewhere, so the old
    whole-string `in` check let every one of them through -- the key pair would
    then have travelled to whatever host `urllib` actually resolved from it."""
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", domain)
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    with pytest.raises(RuntimeError):
        load_settings()


def test_kf_dev_domain_accepts_a_bare_dev_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required(monkeypatch)

    settings = load_settings()

    assert settings.kf_dev_domain == "dev-kissflow.example.com"


# ======================================================================
# Security-judge finding 1 (Stage C hardening): "dev-" in domain is a whole-
# string substring test, so a FIRST label that merely CONTAINS "dev-"
# anywhere -- not just one that starts with it -- passed. A host like
# "notdev-really.attacker.example" has "dev-" as a substring of its first
# label ("notdev-really") without being a dev tenant at all, and
# "x.dev-y.example.com" has "dev-" only in a LATER label while the actual
# host (first label "x") is not a dev host. The real tenant shape is
# "dev-<name>.<rest>", so the rule must require the FIRST label itself to
# START WITH "dev-".
# ======================================================================


def test_kf_dev_domain_accepts_the_real_tenant_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-acme.kissflow.com")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    settings = load_settings()

    assert settings.kf_dev_domain == "dev-acme.kissflow.com"


@pytest.mark.parametrize(
    "domain",
    [
        "notdev-really.attacker.example",  # "dev-" is a substring, not a prefix
        "x.dev-y.example.com",  # "dev-" is in a later label, not the first
        "prod.example.com",  # no "dev-" anywhere
    ],
    ids=["substring-not-prefix", "dev-in-later-label", "no-dev-at-all"],
)
def test_kf_dev_domain_rejects_a_first_label_not_starting_with_dev(
    monkeypatch: pytest.MonkeyPatch, domain: str
) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", domain)
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    with pytest.raises(RuntimeError, match="refusing non-dev domain"):
        load_settings()


# ======================================================================
# Security-judge finding 5 (round 2): `$` in a non-`MULTILINE` regex matches
# immediately before a trailing "\n" as well as at the true end of the
# string, so `_HOSTNAME_RE.match("dev-x.kissflow.com\n")` reported success --
# a newline-terminated domain would have loaded and travelled to whatever
# host that trailing byte actually resolved to. Source: the `KF_DEV_DOMAIN`
# environment value. Sink: `Settings.kf_dev_domain`, later built into every
# adapter's `base_url`. Guard: `_HOSTNAME_RE.fullmatch`, which requires the
# ENTIRE string -- trailing newline included -- to satisfy the pattern.
# ======================================================================


def test_kf_dev_domain_rejects_a_trailing_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.infrastructure.config.settings.load_dotenv", lambda: None)
    monkeypatch.setenv("KF_DEV_DOMAIN", "dev-acme.kissflow.com\n")
    monkeypatch.setenv("KF_DEV_ACCOUNT_ID", "acct-1")

    with pytest.raises(RuntimeError, match="not a bare hostname"):
        load_settings()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.delenv("KF_APP", raising=False)
    monkeypatch.delenv("KF_PROCESS_TEMPLATE", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("MCP_HTTP", raising=False)
    monkeypatch.delenv("KF_DEV_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("KF_DEV_ACCESS_KEY_SECRET", raising=False)
    monkeypatch.delenv("HTTP_TIMEOUT_SECONDS", raising=False)

    settings = load_settings()

    assert settings.kf_app is None
    assert settings.kf_process_template is None
    assert settings.port == 8080
    assert settings.mcp_http is False
    assert settings.kf_dev_access_key_id is None
    assert settings.kf_dev_access_key_secret is None
    assert settings.http_timeout_seconds == 10.0


def test_mcp_http_true_when_value_is_non_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("MCP_HTTP", "anything")

    assert load_settings().mcp_http is True


def test_settings_is_frozen() -> None:
    settings = Settings(
        kf_dev_domain="dev-kissflow.example.com",
        kf_dev_account_id="acct-1",
        kf_app=None,
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id=None,
        kf_dev_access_key_secret=None,
        http_timeout_seconds=10.0,
    )
    with pytest.raises(AttributeError):
        settings.kf_dev_domain = "changed"  # ty: ignore[invalid-assignment]


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "acct-1",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": None,
        "kf_dev_access_key_secret": None,
        "http_timeout_seconds": 10.0,
    }
    base.update(overrides)
    return Settings(**base)


def test_resolve_app_id_prefers_the_override() -> None:
    settings = _settings(kf_app="App1")
    assert settings.resolve_app_id("App2") == "App2"


def test_resolve_app_id_falls_back_to_kf_app() -> None:
    settings = _settings(kf_app="App1")
    assert settings.resolve_app_id(None) == "App1"


def test_resolve_app_id_falls_back_to_empty_string() -> None:
    settings = _settings(kf_app=None)
    assert settings.resolve_app_id(None) == ""


def test_repr_never_shows_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    # gitleaks:allow
    monkeypatch.setenv("KF_DEV_ACCESS_KEY_SECRET", "super-secret-value")

    settings = load_settings()

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)


def _settings_with_default_app(default_app: str | None) -> Settings:
    return Settings(
        kf_dev_domain="dev-kissflow.example.com",
        kf_dev_account_id="acct-1",
        kf_app=default_app,
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id=None,
        kf_dev_access_key_secret=None,
        http_timeout_seconds=10.0,
    )


def test_resolve_app_id_treats_an_empty_string_as_not_given() -> None:
    settings = _settings_with_default_app("default-app")
    assert settings.resolve_app_id("") == "default-app"


def test_resolve_process_template_path_reads_the_settings_field() -> None:
    settings = _settings(kf_app=None, kf_process_template="shapes/tenant_template.json")
    assert settings.resolve_process_template_path() == "shapes/tenant_template.json"


def test_resolve_process_template_path_is_none_when_unset() -> None:
    assert _settings(kf_app=None).resolve_process_template_path() is None
