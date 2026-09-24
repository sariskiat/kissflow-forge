"""The caller's own Kissflow access-key pair (refactor spec G4, D4).

HR2: the pair is never a tool argument, never logged, never stored by the server. Over
HTTP it comes off this call's own request headers -- `X-Access-Key-Id` /
`X-Access-Key-Secret`, the names Kissflow itself uses (`client.py`'s `KfConfig.headers`)
-- so the adapter forwards them unchanged rather than inventing a custom pair of names.
A connector that may only send pre-approved header names (Anthropic's custom connector
refuses unapproved custom names such as `x-access-key-id`) sends the same pair as the
approved `X-Api-Key` + `X-Api-Secret`, or as one standard header,
`Authorization: Bearer <key id>:<key secret>`. The approved pair keeps `Authorization`
free for a gateway's own sign-in token. In stdio mode it comes from `Settings`
(the local developer's own `.env`).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from app.infrastructure.config.settings import Settings

_KEY_ID_HEADER = "x-access-key-id"
_KEY_SECRET_HEADER = "x-access-key-secret"
_API_KEY_HEADER = "x-api-key"
_API_SECRET_HEADER = "x-api-secret"
_AUTHORIZATION_HEADER = "authorization"
_BEARER_PREFIX = "bearer "


def _pair_from_bearer(value: str | None) -> tuple[str | None, str | None]:
    """Split `Bearer <key id>:<key secret>` on the FIRST colon.

    A key id never holds a colon; a secret may, so only the first one splits.
    Anything else (another scheme, no colon, an empty half) yields `(None, None)`
    and the caller refuses the call by name.
    """
    if not value or value[: len(_BEARER_PREFIX)].lower() != _BEARER_PREFIX:
        return None, None
    key_id, sep, key_secret = value[len(_BEARER_PREFIX) :].strip().partition(":")
    if not sep:
        return None, None
    return key_id, key_secret


def _is_printable_ascii(value: str) -> bool:
    """True when every character of `value` is both ASCII and printable.

    A zero-width space or another non-ASCII character passes the plain
    emptiness check below -- `caller_keys` would then hand it to `sign()`,
    and `send_json` raises a raw, untranslated `UnicodeEncodeError` the
    first time httpx tries to encode it onto the wire as a header value
    (security-judge finding 6, round 2). `str.isprintable()` alone already
    refuses a zero-width space (Unicode category Cf, "Format", is one of the
    non-printable categories); `str.isascii()` additionally refuses a
    non-ASCII character that IS printable, such as an accented letter,
    which `isprintable()` alone would let through.

    Args:
        value: The candidate key id or key secret, already stripped.

    Returns:
        `True` when `value` is safe to place in an HTTP header.
    """
    return value.isascii() and value.isprintable()


@dataclass(frozen=True)
class KissflowKeyPair:
    """The caller's own Kissflow access-key pair.

    Attributes:
        key_id: The Kissflow access-key id.
        key_secret: The Kissflow access-key secret. Never shown by `repr()`/`str()`.
    """

    key_id: str
    key_secret: str

    def __repr__(self) -> str:
        return f"KissflowKeyPair(key_id={self.key_id!r}, key_secret='***')"

    def __str__(self) -> str:
        return self.__repr__()


def caller_keys(settings: Settings) -> KissflowKeyPair:
    """Resolve the caller's own Kissflow access-key pair for this call.

    Over HTTP (`settings.mcp_http`), the pair comes off this call's own request headers
    -- `X-Access-Key-Id` + `X-Access-Key-Secret`, else `X-Api-Key` + `X-Api-Secret`,
    else `Authorization: Bearer <id>:<secret>` -- never a shared credential, and never
    the process env; a call with no pair on it is refused by name. In stdio mode, the
    pair comes from `Settings`.

    Args:
        settings: The already-validated process `Settings`.

    Returns:
        The caller's `KissflowKeyPair`.

    Raises:
        ToolError: No pair is available for this call: a missing or empty header
            over HTTP, a missing key in `Settings` in stdio mode, or a key that
            is not printable ASCII (security-judge finding 6, round 2).
    """
    if settings.mcp_http:
        headers = get_http_headers(
            include={
                _KEY_ID_HEADER,
                _KEY_SECRET_HEADER,
                _API_KEY_HEADER,
                _API_SECRET_HEADER,
                _AUTHORIZATION_HEADER,
            }
        )
        # The first COMPLETE pair wins, taken whole (sources are never mixed): the
        # Kissflow names, then the approved connector names, then the Bearer form.
        # Values are stripped BEFORE the completeness check, so a whitespace-only
        # higher pair never hides a valid lower one.
        key_id = (headers.get(_KEY_ID_HEADER) or "").strip()
        key_secret = (headers.get(_KEY_SECRET_HEADER) or "").strip()
        if not (key_id and key_secret):
            key_id = (headers.get(_API_KEY_HEADER) or "").strip()
            key_secret = (headers.get(_API_SECRET_HEADER) or "").strip()
        if not (key_id and key_secret):
            key_id, key_secret = _pair_from_bearer(headers.get(_AUTHORIZATION_HEADER))
    else:
        key_id = settings.kf_dev_access_key_id
        key_secret = settings.kf_dev_access_key_secret
    # A whitespace-only header (" ") is truthy, so it must be stripped before the
    # emptiness check below, or it reaches Kissflow as a literal credential instead
    # of being refused (security-judge finding 6, Stage C hardening).
    key_id = (key_id or "").strip()
    key_secret = (key_secret or "").strip()
    if (
        not key_id
        or not key_secret
        or not _is_printable_ascii(key_id)
        or not _is_printable_ascii(key_secret)
    ):
        raise ToolError("no Kissflow key pair on this call")
    return KissflowKeyPair(key_id=key_id, key_secret=key_secret)
