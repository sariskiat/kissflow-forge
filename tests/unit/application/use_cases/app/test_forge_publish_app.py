"""Spec for app.application.use_cases.app.forge_publish_app.

Ports `tests/test_p4_surface.py`'s `publish_application_verified` tests onto
the new fake-port architecture.
"""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.app.forge_publish_app_request import (
    ForgePublishAppRequest,
)
from app.application.use_cases.app.forge_publish_app import ForgePublishApp
from app.domain.entities.navigation import Navigation


@pytest.mark.asyncio
async def test_publish_app_reads_back_meta_version_no_runtime_node() -> None:
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [
        Navigation.from_wire({}),
        Navigation.from_wire({"Root": "M1", "_meta_version": "v9", "M1": {"Id": "M1"}}),
    ]

    resp = await ForgePublishApp(fake).execute(ForgePublishAppRequest(app_id="App1"))

    assert resp.published is True
    assert resp.meta_version == "v9"
    assert resp.runtime_id is None and resp.note
    # The pre-publish read carried no version of its own here (`{}`), so
    # `snapshot_version` is legitimately `None` -- see the next test for a
    # draft that DOES carry one.
    assert resp.snapshot_version is None
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_publish_app_snapshot_version_is_the_pre_publish_read() -> None:
    """Review fix 7: the response's `snapshot_version` is the PRE-publish
    read's own version (`_apps.py:81`'s leading `get_app_draft`), the same
    write-order-first read `forge_publish(kind="application")` uses for its
    own `snapshot_version` (`use_cases/flow/forge_publish.py`) -- never a
    bare `None`."""
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [
        Navigation.from_wire({"Root": "M0", "_meta_version": "v8", "M0": {"Id": "M0"}}),
        Navigation.from_wire({"Root": "M1", "_meta_version": "v9", "M1": {"Id": "M1"}}),
    ]

    resp = await ForgePublishApp(fake).execute(ForgePublishAppRequest(app_id="App1"))

    assert resp.meta_version == "v9"
    assert resp.snapshot_version == "v8"


@pytest.mark.asyncio
async def test_publish_app_surfaces_a_runtime_node_when_present() -> None:
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

    resp = await ForgePublishApp(fake).execute(ForgePublishAppRequest(app_id="App1"))

    assert resp.runtime_id == "Runtime_abc123"
    assert resp.note is None


@pytest.mark.asyncio
async def test_publish_app_propagates_publish_failure() -> None:
    class _Failing(FakeAppRepository):
        async def publish_app(self, app_id: str) -> None:  # type: ignore[override]
            raise RepositoryError("boom")

    with pytest.raises(RepositoryError):
        await ForgePublishApp(_Failing()).execute(ForgePublishAppRequest(app_id="App1"))


@pytest.mark.asyncio
async def test_no_app_id_is_refused_before_any_port_call() -> None:
    fake = FakeAppRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgePublishApp(fake).execute(ForgePublishAppRequest(app_id=""))
    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
