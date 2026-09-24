"""`infrastructure.mcp.tools._shared`: the seven annotation profiles, and
`run_use_case` -- the one call every thin tool makes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from app.application.exceptions import ApplicationError
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.tools import _shared

_PROFILES = (
    _shared.OFFLINE_PURE,
    _shared.OFFLINE_ARTIFACT,
    _shared.LIVE_READ,
    _shared.LIVE_ADD,
    _shared.LIVE_ADD_ONCE,
    _shared.LIVE_REPLACE,
    _shared.LIVE_REPLACE_ONCE,
)


def test_every_profile_carries_the_four_tool_annotation_keys() -> None:
    keys = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
    for profile in _PROFILES:
        assert set(profile) == keys


def test_the_seven_profiles_are_pairwise_distinct() -> None:
    as_tuples = {tuple(sorted(p.items())) for p in _PROFILES}
    assert len(as_tuples) == len(_PROFILES)


def test_live_read_is_read_only_and_open_world() -> None:
    assert _shared.LIVE_READ["readOnlyHint"] is True
    assert _shared.LIVE_READ["openWorldHint"] is True


def test_offline_pure_touches_neither_the_tenant_nor_the_filesystem() -> None:
    assert _shared.OFFLINE_PURE["readOnlyHint"] is True
    assert _shared.OFFLINE_PURE["openWorldHint"] is False


def _settings(mcp_http: bool, key_id: str | None, key_secret: str | None) -> Settings:
    return Settings(
        kf_dev_domain="dev-acme.kissflow.com",
        kf_dev_account_id="ACC1",
        kf_app=None,
        kf_process_template=None,
        port=8080,
        mcp_http=mcp_http,
        kf_dev_access_key_id=key_id,
        kf_dev_access_key_secret=key_secret,
        http_timeout_seconds=10.0,
    )


class _Request(BaseModel):
    flow_id: str


def _ctx(settings: Settings) -> Any:
    ctx = AsyncMock()
    ctx.lifespan_context = {"settings": settings, "resources": "the-resources"}
    return ctx


@pytest.mark.asyncio
async def test_run_use_case_happy_path_builds_and_executes() -> None:
    settings = _settings(mcp_http=False, key_id="k1", key_secret="s1")
    seen_resources: list[Any] = []

    class _UseCase:
        async def execute(self, request: _Request) -> str:
            return f"ran with {request.flow_id}"

    def build_use_case(resources: Any) -> _UseCase:
        seen_resources.append(resources)
        return _UseCase()

    result = await _shared.run_use_case(
        _ctx(settings),
        build_request=lambda: _Request(flow_id="F1"),
        build_use_case=build_use_case,
    )

    assert result == "ran with F1"
    assert seen_resources == ["the-resources"]


@pytest.mark.asyncio
async def test_run_use_case_raises_tool_error_with_no_key_pair() -> None:
    settings = _settings(mcp_http=False, key_id=None, key_secret=None)
    called = False

    def build_request() -> _Request:
        nonlocal called
        called = True
        return _Request(flow_id="F1")

    with pytest.raises(ToolError, match="no Kissflow key pair on this call"):
        await _shared.run_use_case(
            _ctx(settings),
            build_request=build_request,
            build_use_case=lambda resources: (_ for _ in ()).throw(
                AssertionError("must not build a use case with no key pair")
            ),
        )

    assert called is False  # the pair check runs before the request is even built


@pytest.mark.asyncio
async def test_run_use_case_skips_the_key_pair_check_when_not_needed() -> None:
    """intake/design tools are offline -- needs_kissflow=False runs with no pair at
    all."""
    settings = _settings(mcp_http=False, key_id=None, key_secret=None)

    class _UseCase:
        async def execute(self, request: _Request) -> str:
            return request.flow_id

    result = await _shared.run_use_case(
        _ctx(settings),
        build_request=lambda: _Request(flow_id="F1"),
        build_use_case=lambda resources: _UseCase(),
        needs_kissflow=False,
    )

    assert result == "F1"


@pytest.mark.asyncio
async def test_run_use_case_translates_a_validation_error() -> None:
    settings = _settings(mcp_http=False, key_id="k1", key_secret="s1")

    def build_request() -> _Request:
        return _Request.model_validate({})  # missing required flow_id

    with pytest.raises(ToolError):
        await _shared.run_use_case(
            _ctx(settings),
            build_request=build_request,
            build_use_case=lambda resources: (_ for _ in ()).throw(
                AssertionError("must not build a use case with an invalid request")
            ),
        )


@pytest.mark.asyncio
async def test_run_use_case_translates_an_application_error() -> None:
    settings = _settings(mcp_http=False, key_id="k1", key_secret="s1")

    class _UseCase:
        async def execute(self, request: _Request) -> str:
            raise ApplicationError("draft not found", code="NOT_FOUND")

    with pytest.raises(ToolError, match="draft not found"):
        await _shared.run_use_case(
            _ctx(settings),
            build_request=lambda: _Request(flow_id="F1"),
            build_use_case=lambda resources: _UseCase(),
        )


def test_a_validation_error_is_still_a_validation_error() -> None:
    """Sanity: `_Request.model_validate({})` really does raise pydantic's own error --
    proves the translation test above exercises the real exception type."""
    with pytest.raises(ValidationError):
        _Request.model_validate({})
