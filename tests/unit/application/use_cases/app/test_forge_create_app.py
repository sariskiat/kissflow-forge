"""Spec for app.application.use_cases.app.forge_create_app.

Ports `tests/test_client.py::test_create_application_verified_happy_path` onto
the new fake-port architecture.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.app.forge_create_app_request import (
    ForgeCreateAppRequest,
)
from app.application.use_cases.app.forge_create_app import ForgeCreateApp


@pytest.mark.asyncio
async def test_happy_path_reports_the_verified_new_app() -> None:
    fake = FakeAppRepository()
    fake.results["create_application"] = ["App_1"]
    fake.results["list_applications"] = [[], [{"_id": "App_1", "Name": "Sample App"}]]

    resp = await ForgeCreateApp(fake).execute(ForgeCreateAppRequest(name="Sample App"))

    assert resp.app_id == "App_1"
    assert resp.name == "Sample App"
    assert resp.verified is True
    assert resp.snapshot_version is None
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_unverified_create_is_a_loud_failure() -> None:
    fake = FakeAppRepository()
    fake.results["create_application"] = ["App_1"]
    fake.results["list_applications"] = [[], []]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeCreateApp(fake).execute(ForgeCreateAppRequest(name="Sample App"))
    assert exc_info.value.code == "VERIFY_FAILED"


@pytest.mark.asyncio
async def test_a_repository_error_propagates_unchanged() -> None:
    class _Failing(FakeAppRepository):
        async def create_application(self, name: str) -> str:  # type: ignore[override]
            raise RepositoryError("FlowNameAlreadyExists")

    with pytest.raises(RepositoryError):
        await ForgeCreateApp(_Failing()).execute(
            ForgeCreateAppRequest(name="Sample App")
        )
