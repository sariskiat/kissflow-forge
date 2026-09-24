"""`app_lifespan`: one pool, opened with the Settings timeout and closed on exit; every
`AppResources` field is an instance of its port; no field holds a credential."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.application.interfaces.app import AppRepository
from app.application.interfaces.artifacts import ArtifactWriter
from app.application.interfaces.copilot import CopilotService
from app.application.interfaces.dataset import DatasetRepository
from app.application.interfaces.docs import DocsReader
from app.application.interfaces.flow import FlowRepository
from app.application.interfaces.item import ItemService
from app.application.interfaces.page import PageRepository
from app.infrastructure.config.settings import Settings
from app.infrastructure.kissflow.credentials import KissflowKeyPair
from app.infrastructure.mcp.lifespan import AppResources, app_lifespan


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "ACC1",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": "key-1",
        "kf_dev_access_key_secret": "secret-1",  # gitleaks:allow
        "http_timeout_seconds": 17.0,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_opens_one_pool_with_the_settings_timeout_and_no_redirects() -> None:
    fake_client = AsyncMock(spec=httpx.AsyncClient)

    with patch("httpx.AsyncClient", return_value=fake_client) as client_cls:
        async with app_lifespan(AsyncMock(), _settings()) as ctx:
            assert isinstance(ctx["resources"], AppResources)

    client_cls.assert_called_once_with(timeout=17.0, follow_redirects=False)
    fake_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_closes_the_pool_even_when_the_caller_raises() -> None:
    fake_client = AsyncMock(spec=httpx.AsyncClient)

    with (
        patch("httpx.AsyncClient", return_value=fake_client),
        pytest.raises(RuntimeError, match="boom"),
    ):
        async with app_lifespan(AsyncMock(), _settings()):
            raise RuntimeError("boom")

    fake_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_every_resource_shares_the_one_pool_and_actually_sends_requests() -> None:
    """Not a spy: a real httpx.AsyncClient over MockTransport, proving every adapter
    routes through the SAME pool the lifespan opened, not one of its own."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"_meta_version": "v1"})

    real_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def _build_client(*, timeout: float, follow_redirects: bool) -> httpx.AsyncClient:
        assert timeout == 17.0
        assert follow_redirects is False
        return real_client

    with patch("httpx.AsyncClient", side_effect=_build_client):
        async with app_lifespan(AsyncMock(), _settings()) as ctx:
            resources: AppResources = ctx["resources"]
            await resources.flow.get_draft("A1", "process", "F1")

    assert seen == [
        "https://dev-acme.kissflow.com/metadata/2/ACC1/process/F1/draft"
        "?_application_id=A1"
    ]
    assert real_client.is_closed


@pytest.mark.asyncio
async def test_every_field_is_an_instance_of_its_port() -> None:
    async with app_lifespan(AsyncMock(), _settings()) as ctx:
        resources: AppResources = ctx["resources"]

    assert isinstance(resources.flow, FlowRepository)
    assert isinstance(resources.app, AppRepository)
    assert isinstance(resources.page, PageRepository)
    assert isinstance(resources.dataset, DatasetRepository)
    assert isinstance(resources.item, ItemService)
    assert isinstance(resources.copilot, CopilotService)
    assert isinstance(resources.docs, DocsReader)
    assert isinstance(resources.artifacts, ArtifactWriter)


@pytest.mark.asyncio
async def test_approval_secret_is_32_random_bytes_new_each_process() -> None:
    """The intake family's approval-token gate: one secret per process, never
    derivable from anything a caller can observe (spec D8)."""
    async with app_lifespan(AsyncMock(), _settings()) as ctx1:
        secret1: bytes = ctx1["resources"].approval_secret
    async with app_lifespan(AsyncMock(), _settings()) as ctx2:
        secret2: bytes = ctx2["resources"].approval_secret

    assert isinstance(secret1, bytes)
    assert len(secret1) == 32
    assert secret1 != secret2


@pytest.mark.asyncio
async def test_settings_is_also_yielded_for_caller_keys_and_kf_app() -> None:
    settings = _settings(kf_app="A1")
    async with app_lifespan(AsyncMock(), settings) as ctx:
        assert ctx["settings"] is settings


@pytest.mark.asyncio
async def test_repr_does_not_print_the_approval_secret() -> None:
    """A `repr(AppResources(...))` is exactly the kind of thing that ends up in a
    log line or a debugger dump -- the raw HMAC secret must never appear in it."""
    async with app_lifespan(AsyncMock(), _settings()) as ctx:
        resources: AppResources = ctx["resources"]

    text = repr(resources)
    assert repr(resources.approval_secret) not in text
    assert "approval_secret" not in text


@pytest.mark.asyncio
async def test_no_resource_field_holds_a_credential() -> None:
    """HR2: AppResources holds no key pair of any kind, no field or attribute."""
    async with app_lifespan(AsyncMock(), _settings()) as ctx:
        resources: AppResources = ctx["resources"]

    for field_name in resources.__dataclass_fields__:
        adapter = getattr(resources, field_name)
        assert not isinstance(adapter, KissflowKeyPair)
        for attr_name in vars(adapter) if hasattr(adapter, "__dict__") else ():
            attr = getattr(adapter, attr_name)
            assert not isinstance(attr, KissflowKeyPair), (
                f"{field_name}.{attr_name} holds a key pair"
            )
