"""Shared async HTTP transport for every Kissflow builder-API adapter.

Invariant. For every outbound request `r` of every adapter: `r.url.host ==
settings.kf_dev_domain`, `r.url.scheme == "https"`, `r.headers["X-Access-Key-Id"]
== pair.key_id` and `r.headers["X-Access-Key-Secret"] == pair.key_secret`, where
`pair = caller_keys(settings)` at the time of the request. An adapter never
stores a pair -- it calls `sign()` fresh for every request. No request ever
leaves that host: every request here is sent with `follow_redirects=False`
(httpx's own default; restated explicitly here, and on the pool the lifespan
opens, G5) so a 3xx response is never auto-followed. The old `urllib` transport
this replaces (`KfClient._req`) DID follow redirects and replayed every header
onto the new request -- a 3xx off `KF_DEV_DOMAIN` would have resent
`X-Access-Key-Secret` to a different origin, or silently downgraded `https` to
`http`. A redirect response is therefore treated as just another non-200
status: it raises the same as any other failure, and this module never sends
a second request to follow it.

The invariant above used to be enforced only by the test suite (security-judge
finding 2, Stage C hardening): `send_json` now checks `expected_host`, the
`https` scheme, and (security-judge finding 3, round 2) that the origin
carries no explicit port and no userinfo, before the request goes out, and
raises `error_cls` with no request made when any of those does not hold.
`https://dev-x.kissflow.com:8443/a` and `https://u:p@dev-x.kissflow.com/a`
both name `dev-x.kissflow.com` as `.hostname`, so the host-only check let
both through even though neither is the bare tenant origin every adapter's
`base_url` actually builds. `expected_host` is passed in by the adapter,
resolved from `settings.base_url` -- independent of whatever `base_url`
string the adapter itself happens to have been built with, so a
misconfigured or attacker-controlled `base_url` cannot pass the check just
because the request URL it built agrees with itself.

Mirrors `KfClient._req`/`_json` (`client.py:252-277` pre-refactor) exactly:
only status 200 is success; any other status raises; a 200 with a body that
is not JSON raises; a transport failure raises. The caller passes the error
class, so the builder families (flow, app, page, dataset) raise
`RepositoryError` and the item and copilot families raise
`ExternalServiceError` -- both are `ApplicationError` subclasses, so either
works with the functions below. The one deliberate addition over the old
message text: the HTTP status is embedded in the message, since
`ApplicationError` (unlike the old `Err`) carries no separate `.status` field
-- losing that information on every failure would be a regression, and it is
also how the redirect-safety test proves a 3xx never falls through silently.
Every message built here is also scrubbed of the scheme, the host and the
account id (security-judge finding 5, Stage C hardening): it reaches an MCP
client through `ToolError`, a path `mask_error_details` does not cover, so
only the method, the de-identified route and (for a non-200 response) the
first 300 characters of the upstream body survive into it.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.application.exceptions import REFUSED, ApplicationError
from app.domain.entities.flow_draft import FlowDraft
from app.domain.entities.navigation import Navigation
from app.domain.entities.page_draft import PageDraft
from app.infrastructure.kissflow.credentials import KissflowKeyPair

#: HTTP 409, or 400 carrying this Kissflow error code, means the write lost a
#: race -- the conflict rule (`client.py`'s `delete_flow`/`delete_application`
#: docstrings; `Err("conflict", ...)` at `_read_verify_write`, generalised
#: here to every write, not just the draft guard).
_CONFLICT_ERROR_CODE = "KISSFLOW_ERROR_04602"

#: The redaction marker `_safe_route` substitutes for the dev-tenant account id.
_ACCOUNT_PLACEHOLDER = "<account>"


#: The three path-segment values that collapse an intended resource into a
#: different one once httpx removes dot segments per RFC 3986 5.2.4, or that
#: leave an empty segment where an id was expected. `urllib.parse.quote`
#: treats `.` as always-safe no matter what `safe=` is passed, so none of
#: these three values are touched by encoding -- they must be refused before
#: it runs (security-judge finding 1, round 2).
_UNSAFE_PATH_SEGMENTS = frozenset({"", ".", ".."})


def quote_path_segment(value: str, error_cls: type[ApplicationError]) -> str:
    """Percent-encode one caller-supplied URL path segment.

    Refuses `""`, `"."` and `".."` outright, before any encoding runs
    (security-judge finding 1, round 2). `urllib.parse.quote` treats `.` as
    always-safe regardless of `safe=""`, so those three values used to reach
    the wire byte for byte, and httpx removes dot segments from the outbound
    path before it sends (RFC 3986 5.2.4): an id of exactly `".."` does not
    name a resource -- it deletes the LAST segment already in the path and
    then vanishes itself, so `.../application/APP/page/..` was sent as
    `.../application/APP`, the whole-application resource, not the page one.
    `delete_page("APP", "..")` sent the delete-application request;
    `publish_page("APP", "..")` published the whole app; `put_page_draft`
    both read and wrote the application's own navigation draft, its version
    guard passing only because the read landed on that same wrong resource.
    An empty segment (`""`) collapses the path the same way, leaving a bare
    trailing `/` where the id belonged.

    Every remaining character outside the unreserved set is still escaped
    (`safe=""`), so a caller-supplied id can never terminate the path early
    with `?`, or add a query parameter with `&` (security-judge finding 7,
    Stage C hardening). An ordinary Kissflow id -- letters, digits, `-`,
    `_` -- encodes to itself, so this is a no-op for every id the recorded
    differential fixtures cover.

    Args:
        value: The caller-supplied id to place in a URL path segment.
        error_cls: The calling family's error class -- `RepositoryError` for
            the builder-API families, `ExternalServiceError` for item and
            copilot.

    Returns:
        `value`, percent-encoded with no character treated as safe.

    Raises:
        error_cls: `value` is `""`, `"."` or `".."` (`code=REFUSED`), with
            the refused value named in the message.
    """
    if value in _UNSAFE_PATH_SEGMENTS:
        raise error_cls(f"refused unsafe path segment: {value!r}", code=REFUSED)
    return urllib.parse.quote(value, safe="")


def build_query(params: dict[str, str]) -> str:
    """Build a `?`-prefixed query string from caller-supplied values.

    Every value is run through `urllib.parse.urlencode` (security-judge
    finding 2, round 2), so a caller-supplied value that itself contains `&`
    or `#` can never terminate the query early or overwrite a parameter that
    was meant to follow it. The old f-string-built query for
    `update_dataset_record(app_id="APP&_id=VICTIM#", ..., record_id="MINE")`
    read `?_application_id=APP&_id=VICTIM#&_id=MINE` -- a URL parser treats
    everything from `#` on as the fragment, so the real `_id=MINE` never
    reached the query string, and Kissflow wrote `VICTIM`'s record instead of
    `MINE`'s. `quote_via=urllib.parse.quote` matches `quote_path_segment`'s
    own escaping (`safe=""`), so this produces byte-for-byte the same query
    string as the old, unencoded f-strings for every ordinary Kissflow id --
    the recorded differential fixtures still match.

    Args:
        params: The query parameters, supplied in the exact name and order
            every route already sends them on the wire.

    Returns:
        `"?" + urlencode(params)`, or `""` when `params` is empty.
    """
    if not params:
        return ""
    return "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def sign(pair: KissflowKeyPair) -> dict[str, str]:
    """Build the four headers Kissflow itself requires on every request.

    The same four keys `KfConfig.headers` sent (`client.py:201-209`
    pre-refactor): the caller's own key pair, plus the two content headers.

    Args:
        pair: The caller's Kissflow access-key pair for this request,
            resolved fresh by `caller_keys(settings)`.

    Returns:
        The headers to send on this one request. Never stored.
    """
    return {
        "X-Access-Key-Id": pair.key_id,
        "X-Access-Key-Secret": pair.key_secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _is_conflict_response(status: int, body: str) -> bool:
    """True when a non-200 response is the conflict case, not a plain failure."""
    return status == 409 or (status == 400 and _CONFLICT_ERROR_CODE in body)


def _safe_route(url: str, account_id: str) -> str:
    """The part of `url` safe to surface in a message an MCP client can see.

    Drops the scheme and the host -- an outbound message never needs to name
    the tenant host -- and scrubs every occurrence of `account_id` from what
    remains, so a de-identified route is all that is left (security-judge
    finding 5, Stage C hardening).

    Args:
        url: The full request URL a call was, or would have been, sent to.
        account_id: The dev-tenant account id to scrub.

    Returns:
        `url`'s path and query string, with `account_id` replaced by
        `"<account>"` wherever it occurs.
    """
    parsed = urllib.parse.urlsplit(url)
    route = parsed.path if parsed.path else "/"
    if parsed.query:
        route = f"{route}?{parsed.query}"
    if account_id:
        route = route.replace(account_id, _ACCOUNT_PLACEHOLDER)
    return route


async def send_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    error_cls: type[ApplicationError],
    *,
    expected_host: str,
    account_id: str,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    """Send one request and return its parsed JSON body.

    Args:
        client: The shared pool the lifespan opened.
        method: The HTTP verb.
        url: The full request URL, already built from `base_url`.
        error_cls: `RepositoryError` for the builder-API families,
            `ExternalServiceError` for item and copilot.
        expected_host: The only host a request may target -- the host of
            `settings.base_url`, passed in by the adapter (security-judge
            finding 2, Stage C hardening).
        account_id: The dev-tenant account id, scrubbed from any message
            this call raises (see `_safe_route`).
        json_body: The JSON-serialisable request body, or `None` for a
            bodyless request.
        headers: The headers to send, normally `sign(pair)`.

    Returns:
        The parsed JSON response body.

    Raises:
        error_cls: `url` does not target a bare `https://expected_host`
            origin -- a different host, a non-`https` scheme, an explicit
            port, or userinfo (`user:pass@host`) all refuse, with no request
            sent (security-judge finding 3, round 2); the request transport
            failed, including a malformed `url` (`httpx.InvalidURL`, which
            is not an `httpx.HTTPError` subclass); the response status was
            not 200 (`code="CONFLICT"` for a 409, or a 400 carrying
            `KISSFLOW_ERROR_04602`); or the response was a 200 with a body
            that is not valid JSON.
    """
    parsed_url = urllib.parse.urlsplit(url)
    try:
        has_port = parsed_url.port is not None
    except ValueError:
        # A port that does not even parse as an integer is not "no port"
        # either -- refuse rather than let a raw ValueError escape.
        has_port = True
    off_tenant = (
        parsed_url.scheme != "https"
        or parsed_url.hostname != expected_host
        or has_port
        or parsed_url.username is not None
        or parsed_url.password is not None
    )
    if off_tenant:
        raise error_cls(
            f"{method} refused: request did not target the configured "
            "tenant host over https"
        )

    try:
        response = await client.request(
            method,
            url,
            json=json_body,
            headers=headers,
            follow_redirects=False,
        )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # `str(exc)` can carry the tenant host -- a TLS hostname-mismatch
        # message names it, for one (security-judge finding 4, round 2).
        # Only the exception's class name survives into the message an MCP
        # client can see.
        raise error_cls(f"transport error: {type(exc).__name__}") from exc

    body = response.text
    route = _safe_route(url, account_id)
    if response.status_code != 200:
        message = f"{method} {route} -> {response.status_code} {body[:300]}"
        if _is_conflict_response(response.status_code, body):
            raise error_cls(message, code="CONFLICT")
        raise error_cls(message)

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise error_cls(f"{method} {route} -> non-JSON body {body[:200]!r}") from None


#: The only three entities `put_draft`/`put_page_draft`/`put_app_draft` write. A
#: `Protocol` would do the same structural job, but `scripts/arch_scan.py`'s
#: `adapter_methods_without_port` flags every public method of every class
#: `infrastructure/` defines that has no port base -- a concrete union has no
#: class of its own to flag.
_Draft = FlowDraft | PageDraft | Navigation


async def read_verify_write[T: _Draft](
    *,
    read: Callable[[], Awaitable[T]],
    write: Callable[[], Awaitable[T]],
    expect_version: str | None,
    error_cls: type[ApplicationError],
) -> T:
    """The read-verify-write guard behind `put_draft`/`put_page_draft`/`put_app_draft`.

    Mirrors `KfClient._read_verify_write` (`client.py:776-797`
    pre-refactor) exactly: re-fetch the live entity, abort with the same
    message if it drifted since the caller planned against
    `expect_version`, else write.

    `expect_version=None` means "I expect a draft that has no version yet",
    not "skip the check" -- a live draft that already carries a version
    would otherwise be clobbered by a caller who never read it first
    (security-judge finding 3, Stage C hardening). The single equality below
    covers both the versioned case and this one: `None != None` is `False`
    (a brand new draft, nothing to clobber, write proceeds), while
    `None != "v-live"` is `True` (the live draft has a version the caller
    never planned against, refuse).

    Args:
        read: Re-reads the live entity (`get_draft`/`get_page_draft`/
            `get_app_draft`).
        write: Performs the PUT once the version check passes.
        expect_version: The `_meta_version` this write was planned against,
            or `None` when the caller expects a still-versionless draft.
        error_cls: `RepositoryError` (every caller of this helper is a
            builder-API family).

    Returns:
        The entity `write()` returns.

    Raises:
        error_cls: `read()` failed, or the live version does not equal
            `expect_version` (`code="CONFLICT"`).
    """
    current = await read()
    # A plain `current.version` does not type-check here: `T` is bound to a
    # Union of three concrete entities, and a property access through a
    # TypeVar bound to a Union is not something ty resolves (each variant's
    # `version` descriptor has a different, non-unifiable `self` type). All
    # three entities expose the identical `version` property, so this is
    # exactly the duck-typed read that justifies it.
    live_version: str | None = getattr(current, "version")  # noqa: B009
    if expect_version != live_version:
        message = (
            f"draft changed under us: expected {expect_version!r}, "
            f"live {live_version!r}"
        )
        raise error_cls(message, code="CONFLICT")
    return await write()
