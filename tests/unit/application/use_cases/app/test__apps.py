"""Spec for app.application.use_cases.app._apps.

Ports the matching cases of `tests/test_client.py`'s `create_application_verified`
tests and `tests/test_p4_surface.py`'s `publish_application_verified` tests onto
the new fake-port architecture: an `Err` return becomes a `RepositoryError` the
port raises directly, so there is nothing left for this layer to translate --
the propagation tests below prove the one thing this layer still owns. The
empty-app-id rule itself lives in `app.application.use_cases.app._app_id`,
shared by the whole app family (see `tests/unit/application/use_cases/app/
test__app_id.py`) -- it is not restated here.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.use_cases.app._apps import (
    create_application_verified,
    publish_application_verified,
)
from app.domain.entities.navigation import Navigation


@pytest.mark.asyncio
async def test_create_application_verified_reads_before_it_writes() -> None:
    fake = FakeAppRepository()
    fake.results["create_application"] = ["App_1"]
    fake.results["list_applications"] = [[], [{"_id": "App_1", "Name": "Demo"}]]

    app_id = await create_application_verified(fake, "Demo")

    assert app_id == "App_1"
    assert [c[0] for c in fake.calls] == [
        "list_applications",
        "create_application",
        "list_applications",
    ]


@pytest.mark.asyncio
async def test_create_application_verified_raises_when_the_new_id_never_verifies() -> (
    None
):
    fake = FakeAppRepository()
    fake.results["create_application"] = ["App_1"]
    fake.results["list_applications"] = [[], []]

    with pytest.raises(ApplicationError) as exc_info:
        await create_application_verified(fake, "Demo")
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "App_1" in exc_info.value.message


@pytest.mark.asyncio
async def test_create_application_verified_propagates_a_repository_error() -> None:
    class _Failing(FakeAppRepository):
        async def create_application(self, name: str) -> str:  # type: ignore[override]
            raise RepositoryError("FlowNameAlreadyExists")

    with pytest.raises(RepositoryError, match="FlowNameAlreadyExists"):
        await create_application_verified(_Failing(), "Demo")


@pytest.mark.asyncio
async def test_publish_application_verified_reads_back_meta_version() -> None:
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [
        Navigation.from_wire({"Root": "M0", "_meta_version": "v8", "M0": {"Id": "M0"}}),
        Navigation.from_wire({"Root": "M1", "_meta_version": "v9", "M1": {"Id": "M1"}}),
    ]

    (
        runtime_id,
        meta_version,
        note,
        snapshot_version,
    ) = await publish_application_verified(fake, "App1")

    assert runtime_id is None
    assert meta_version == "v9"
    assert note is not None
    # The PRE-publish read's own version -- the write-order invariant's
    # leading read, not the post-publish read-back (`forge_publish_app`'s own
    # `snapshot_version`, review fix 7).
    assert snapshot_version == "v8"
    assert [c[0] for c in fake.calls] == [
        "get_app_draft",
        "publish_app",
        "get_app_draft",
    ]


@pytest.mark.asyncio
async def test_publish_application_verified_surfaces_a_runtime_node_when_present() -> (
    None
):
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [
        Navigation.from_wire({}),
        Navigation.from_wire(
            {
                "Root": "M1",
                "_meta_version": "v9",
                "M1": {"Id": "M1"},
                "Runtime_abc123": {"Id": "Runtime_abc123"},
            }
        ),
    ]

    (
        runtime_id,
        _meta_version,
        note,
        _snapshot_version,
    ) = await publish_application_verified(fake, "App1")

    assert runtime_id == "Runtime_abc123"
    assert note is None


@pytest.mark.asyncio
async def test_publish_application_verified_propagates_a_publish_failure() -> None:
    class _Failing(FakeAppRepository):
        async def publish_app(self, app_id: str) -> None:  # type: ignore[override]
            raise RepositoryError("boom")

    with pytest.raises(RepositoryError, match="boom"):
        await publish_application_verified(_Failing(), "App1")


@pytest.mark.asyncio
async def test_publish_application_verified_translates_a_readback_failure() -> None:
    class _Failing(FakeAppRepository):
        def __init__(self) -> None:
            super().__init__()
            self._reads = 0

        async def get_app_draft(self, app_id: str) -> Navigation:  # type: ignore[override]
            self._reads += 1
            if self._reads == 1:
                return Navigation.from_wire({})
            raise RepositoryError("500 Internal Server Error")

    with pytest.raises(ApplicationError) as exc_info:
        await publish_application_verified(_Failing(), "App1")
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "read-back failed" in exc_info.value.message
