"""Spec for app.application.use_cases.app.forge_list_apps.

No old test in `tests/test_client.py`/`tests/test_p4_surface.py` covers this
orchestration directly (it lived inline in `server.py`'s own tool body, not a
separate `client.py` helper) -- the happy path and one failure path below are
new, per `brief_stage_d_common.md` section 5.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository

from app.application.exceptions import RepositoryError
from app.application.models.requests.app.forge_list_apps_request import (
    ForgeListAppsRequest,
)
from app.application.use_cases.app.forge_list_apps import ForgeListApps


@pytest.mark.asyncio
async def test_lists_every_application_as_id_and_name_pairs() -> None:
    fake = FakeAppRepository()
    fake.results["list_applications"] = [
        [
            {"_id": "App_1", "Name": "Demo", "Extra": "dropped"},
            {"_id": "App_2", "Name": "Other"},
        ]
    ]

    resp = await ForgeListApps(fake).execute(ForgeListAppsRequest())

    assert resp.apps == [
        {"_id": "App_1", "Name": "Demo"},
        {"_id": "App_2", "Name": "Other"},
    ]
    assert resp.count == 2
    assert fake.calls == [("list_applications", (), {})]


@pytest.mark.asyncio
async def test_an_empty_account_reports_zero_apps() -> None:
    fake = FakeAppRepository()
    fake.results["list_applications"] = [[]]

    resp = await ForgeListApps(fake).execute(ForgeListAppsRequest())

    assert resp.apps == []
    assert resp.count == 0


@pytest.mark.asyncio
async def test_a_repository_error_propagates_unchanged() -> None:
    class _Failing(FakeAppRepository):
        async def list_applications(self):  # type: ignore[override]
            raise RepositoryError("500 Internal Server Error")

    with pytest.raises(RepositoryError):
        await ForgeListApps(_Failing()).execute(ForgeListAppsRequest())


@pytest.mark.asyncio
async def test_a_non_list_answer_raises_repository_error() -> None:
    """Old (`server.py:1742-1745`): a non-list `list_applications` answer was
    a guarded `Err("http", f"list_applications returned an unexpected shape:
    {got!r}")`, never an `AttributeError` from calling `.get` on it."""
    fake = FakeAppRepository()
    fake.results["list_applications"] = [{"Data": []}]

    with pytest.raises(RepositoryError) as exc_info:
        await ForgeListApps(fake).execute(ForgeListAppsRequest())

    assert exc_info.value.message == (
        "list_applications returned an unexpected shape: {'Data': []}"
    )
