"""`ForgeCreatePage`: ported from `tests/test_pages_live.py`'s
`test_create_page_flow_*` cases (pre-refactor), now against the response DTO
or the raised `ApplicationError` and its code, with
`tests.fakes.page.FakePageRepository`.

No `assert_write_order` here (review fix 2): the pre-refactor
`create_page_flow` itself calls `client.create_page(...)` FIRST
(`pages_live.py:61`), a write, and only verifies afterward via
`list_pages` -- there is no pre-existing page to read before one exists.
This use case keeps that same order on purpose; see its own module
docstring for the documented CREATE exemption.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.page import FakePageRepository

from app.application.exceptions import ApplicationError
from app.application.models.requests.page.forge_create_page_request import (
    ForgeCreatePageRequest,
)
from app.application.use_cases.page.forge_create_page import ForgeCreatePage


def _request(**overrides: Any) -> ForgeCreatePageRequest:
    fields: dict[str, Any] = {"app_id": "App1", "name": "Sample Page"}
    fields.update(overrides)
    return ForgeCreatePageRequest(**fields)


@pytest.mark.asyncio
async def test_creates_and_verifies_via_list_pages() -> None:
    fake = FakePageRepository()
    fake.results["create_page"] = ["Page_1"]
    fake.results["list_pages"] = [[{"_id": "Page_1", "Name": "Sample Page"}]]

    resp = await ForgeCreatePage(page=fake).execute(_request())

    assert resp.page_id == "Page_1"
    assert resp.verified is True
    assert resp.published is False
    assert resp.snapshot_version is None
    assert [c[0] for c in fake.calls] == ["create_page", "list_pages"]


@pytest.mark.asyncio
async def test_raises_verify_failed_when_list_route_disagrees() -> None:
    """Mirrors `test_create_page_flow_reports_unverified_when_list_route_disagrees`:
    the create "worked" but the list route disagrees -- rule 7, never a
    success response."""
    fake = FakePageRepository()
    fake.results["create_page"] = ["Page_1"]
    fake.results["list_pages"] = [[]]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeCreatePage(page=fake).execute(_request())

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "did not verify" in exc_info.value.message


@pytest.mark.asyncio
async def test_publishes_when_requested_and_verified() -> None:
    fake = FakePageRepository()
    fake.results["create_page"] = ["Page_1"]
    fake.results["list_pages"] = [[{"_id": "Page_1", "Name": "Sample Page"}]]

    resp = await ForgeCreatePage(page=fake).execute(_request(publish=True))

    assert resp.published is True
    assert [c[0] for c in fake.calls] == ["create_page", "list_pages", "publish_page"]


@pytest.mark.asyncio
async def test_does_not_publish_when_unverified() -> None:
    fake = FakePageRepository()
    fake.results["create_page"] = ["Page_1"]
    fake.results["list_pages"] = [[]]

    with pytest.raises(ApplicationError):
        await ForgeCreatePage(page=fake).execute(_request(publish=True))

    assert [c[0] for c in fake.calls] == ["create_page", "list_pages"]


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakePageRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeCreatePage(page=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert "no app selected" in exc_info.value.message
    assert fake.calls == []
