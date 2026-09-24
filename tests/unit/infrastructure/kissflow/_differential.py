"""Shared differential-test harness for G8's adapters (refactor spec G8, Part 2 tests).

For one port method: call the NEW adapter method through an `httpx.MockTransport` that
records the outbound request and returns a canned 200 JSON response, then assert the
same method, URL and JSON body the OLD `KfClient`/`LiveDataPlane` made for that same
call went out -- read from the committed fixture at
`tests/fixtures/recorded/<family>/<method>.json`, rather than a live OLD-client call.

Stage E deletes `app.infrastructure.kissflow.client`/`dataplane` (the refactor's whole
point): there is no live OLD client left to call. Before that deletion, this same
function called both clients side by side and wrote each recorded pair to its fixture
file -- see `git log` on this file and on `tests/fixtures/recorded/` for that history.
The "old" half of every fixture is now the frozen ground truth; only the "new" half is
still refreshed on every run, so the file stays a live diff against the new adapter,
never a relic that can silently drift from what the adapter actually sends.

Not itself a port fake or an adapter -- a private test helper living entirely under
`tests/`, so the mirror rule (`tests_mirror_src`) does not apply to it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.application.exceptions import ApplicationError
from app.infrastructure.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
RECORDED_DIR = REPO_ROOT / "tests" / "fixtures" / "recorded"


@dataclass(frozen=True)
class _Recorded:
    """One outbound request, as either transport saw it."""

    method: str
    url: str
    body: Any


def _load_old_calls(family: str, method_name: str) -> list[_Recorded]:
    """Read the frozen OLD-client recording off the committed fixture.

    Args:
        family: The port family (`tests/fixtures/recorded/<family>/`).
        method_name: The port method name (`<method_name>.json`).

    Returns:
        Every request the OLD `KfClient`/`LiveDataPlane` made for this
        method, captured before Stage E deleted that module.

    Raises:
        FileNotFoundError: No fixture was ever recorded for this
            family/method -- see `_record_new`'s docstring on how to add
            one, since the live OLD client this used to run against is
            gone.
    """
    path = RECORDED_DIR / family / f"{method_name}.json"
    recorded = json.loads(path.read_text(encoding="utf-8"))
    return [_Recorded(**c) for c in recorded["old"]]


def _record_new(
    canned: Any,
) -> tuple[list[_Recorded], Callable[[httpx.Request], httpx.Response]]:
    calls: list[_Recorded] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append(_Recorded(method=request.method, url=str(request.url), body=body))
        return httpx.Response(200, json=canned)

    return calls, handler


def _identity(value: Any) -> Any:
    return value


async def assert_differential(
    *,
    family: str,
    method_name: str,
    canned_json: Any,
    call_new: Callable[[httpx.AsyncClient], Awaitable[Any]],
    normalize_new_result: Callable[[Any], Any] = _identity,
    expected_calls: int = 1,
) -> None:
    """Run one port method through the new adapter and diff it against the frozen OLD
    recording.

    Args:
        family: The port family, naming `tests/fixtures/recorded/<family>/`.
        method_name: The port method name, naming the fixture file.
        canned_json: The 200 JSON body every request of the new transport
            returns (the same body on every call -- enough to prove method,
            URL and request-body agreement; a `put_draft`-shaped method
            makes two calls, GET then PUT, both against this same body).
        call_new: Invokes the NEW adapter method (async), given the
            `MockTransport`-backed client.
        normalize_new_result: Converts the new adapter's return value into
            the shape the OLD client's return value used to take (for
            example `FlowDraft.to_wire`); identity by default. Still called
            on every run, so a normalizer that itself raises still fails
            the test -- there is no live OLD result left to compare against
            (Stage E), so this is no longer asserted equal to anything.
        expected_calls: How many outbound requests this one port-method call
            makes. 1 for a plain read or write; 2 for a read-verify-write
            guard (`put_draft`/`put_page_draft`/`put_app_draft`: GET then
            PUT).

    Raises:
        AssertionError: The new adapter's call count disagrees with the
            frozen OLD recording, or any one call's method, URL or body
            does.
    """
    old_calls = _load_old_calls(family, method_name)

    new_calls, handler = _record_new(canned_json)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        new_result = await call_new(client)
    normalize_new_result(new_result)

    assert len(old_calls) == expected_calls, (
        f"recorded old client made {len(old_calls)} calls, expected {expected_calls}"
    )
    assert len(new_calls) == expected_calls, (
        f"new adapter made {len(new_calls)} calls, expected {expected_calls}"
    )

    for old_call, new_call in zip(old_calls, new_calls, strict=True):
        assert new_call.method == old_call.method, (new_call.method, old_call.method)
        assert new_call.url == old_call.url, (new_call.url, old_call.url)
        assert new_call.body == old_call.body, (new_call.body, old_call.body)

    out_dir = RECORDED_DIR / family
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{method_name}.json").write_text(
        json.dumps(
            {
                "old": [asdict(c) for c in old_calls],
                "new": [asdict(c) for c in new_calls],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _status_handler(
    status: int, text: str
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=text)

    return handler


async def assert_error_translation(
    *,
    call: Callable[[httpx.AsyncClient], Awaitable[Any]],
    error_cls: type[ApplicationError],
) -> None:
    """Run one adapter call against every status `_http.py` translates, once each.

    `_http.py`'s `send_json` is the one shared code path behind every method
    of every adapter, so this runs once per adapter (against one
    representative method), not once per port method (spec G8, Part 2 test
    3: "error translation per status").

    Args:
        call: Invokes one adapter method against the given MockTransport
            client, with arguments already bound.
        error_cls: The error class this adapter raises
            (`RepositoryError` or `ExternalServiceError`).

    Raises:
        AssertionError: A case did not raise `error_cls` with the expected
            `.code`, or its `.message` does not carry the response status.
    """
    default_code = error_cls("probe").code

    async def _raises(
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> ApplicationError:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(error_cls) as excinfo:
                await call(client)
        return excinfo.value

    exc = await _raises(_status_handler(404, "not found"))
    assert exc.code == default_code
    assert "404" in exc.message

    exc = await _raises(_status_handler(409, "conflict"))
    assert exc.code == "CONFLICT"
    assert "409" in exc.message

    exc = await _raises(_status_handler(400, '{"error":"KISSFLOW_ERROR_04602"}'))
    assert exc.code == "CONFLICT"

    exc = await _raises(_status_handler(400, "bad request"))
    assert exc.code == default_code

    exc = await _raises(_status_handler(500, "boom"))
    assert exc.code == default_code
    assert "500" in exc.message

    def non_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    exc = await _raises(non_json)
    assert "non-JSON body" in exc.message

    def transport_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    exc = await _raises(transport_error)
    assert exc.message.startswith("transport error:")


async def assert_conflict_on_drift(
    *,
    put_call: Callable[[httpx.AsyncClient, str | None], Awaitable[Any]],
    live_version: str,
    error_cls: type[ApplicationError],
) -> None:
    """Assert a `put_*` call raises `code="CONFLICT"` on a version drift, and never
    issues the PUT (the read-verify-write guard, spec G8, Part 2 test 4).

    Args:
        put_call: Invokes the adapter's `put_draft`/`put_page_draft`/
            `put_app_draft`, given the MockTransport client and the
            `expect_version` to plan against.
        live_version: The `_meta_version` the mock GET returns -- deliberately
            different from the `expect_version` `put_call` is invoked with.
        error_cls: `RepositoryError` (every read-verify-write caller is a
            builder-API family).

    Raises:
        AssertionError: The call did not raise `code="CONFLICT"`, or a PUT
            request was issued despite the drift.
    """
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"_meta_version": live_version})
        return httpx.Response(200, json={"_meta_version": "should-not-be-written"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error_cls) as excinfo:
            await put_call(client, "stale-version")

    assert excinfo.value.code == "CONFLICT"
    assert methods == ["GET"], f"a PUT was issued despite the drift: {methods}"


async def assert_refuses_off_tenant_requests(
    *,
    build_adapter: Callable[[httpx.AsyncClient, str, Settings], Any],
    call: Callable[[Any], Awaitable[Any]],
    settings: Settings,
    error_cls: type[ApplicationError],
) -> None:
    """Assert an adapter refuses to send a request off the configured tenant host,
    with no request made (security-judge finding 2, Stage C hardening: the check is
    independent of whatever `base_url` the adapter itself was built with -- it is
    `settings.base_url` that decides the expected host, not the adapter's own
    constructor argument).

    Args:
        build_adapter: Builds the adapter under test, given the MockTransport
            client, a `base_url` (deliberately wrong in both cases below),
            and the real `settings`.
        call: Invokes one adapter method, given the adapter built above.
        settings: The real `Settings` -- `settings.base_url`'s host is the
            one a request must target regardless of `build_adapter`'s
            `base_url` argument.
        error_cls: The error class this adapter raises.

    Raises:
        AssertionError: A call did not raise `error_cls`, or a request was
            sent despite the mismatch.
    """
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = build_adapter(client, "https://evil.example.com", settings)
        with pytest.raises(error_cls):
            await call(adapter)
    assert calls == [], f"a request reached the wrong host: {[c.url for c in calls]}"

    wrong_scheme_base = "http://" + settings.base_url.removeprefix("https://")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = build_adapter(client, wrong_scheme_base, settings)
        with pytest.raises(error_cls):
            await call(adapter)
    assert calls == [], f"a request was sent over http: {[c.url for c in calls]}"
