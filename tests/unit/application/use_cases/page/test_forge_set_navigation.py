"""`ForgeSetNavigation`: ported from `tests/test_pages_live.py`'s
`test_apply_navigation_*` cases (pre-refactor), now against the response DTO
or the raised `ApplicationError` and its code, with
`tests.fakes.app.FakeAppRepository`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.app import FakeAppRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.page.forge_set_navigation_request import (
    ForgeSetNavigationRequest,
)
from app.application.use_cases.page.forge_set_navigation import ForgeSetNavigation
from app.domain.entities.navigation import Navigation


def _seed_app_draft() -> dict[str, Any]:
    return {
        "Root": "Model_Sample01",
        "_meta_version": "v1",
        "Model_Sample01": {
            "Id": "Model_Sample01",
            "Kind": "Application",
            "FlowType": "Application",
            "Name": "Sample Application",
            "DefaultPage": "Page_Sample01",
            "Application::Navigation": ["Navigation_Sample01"],
        },
        "Navigation_Sample01": {
            "Id": "Navigation_Sample01",
            "Kind": "Navigation",
            "Name": "Requester Navigation",
            "Application": "Model_Sample01",
            "Navigation::Menu": ["Menu_Sample01"],
        },
        "Menu_Sample01": {
            "Id": "Menu_Sample01",
            "Kind": "Menu",
            "Name": "Overview",
            "Navigation": "Navigation_Sample01",
            "Menu::FieldMapping": ["FieldMapping_Sample01"],
        },
        "FieldMapping_Sample01": {
            "Id": "FieldMapping_Sample01",
            "Kind": "FieldMapping",
            "Name": "Page",
            "Menu": "Menu_Sample01",
            "FieldMapping::Property": ["Property_Sample01"],
        },
        "Property_Sample01": {
            "Id": "Property_Sample01",
            "Kind": "Property",
            "Type": "Page",
            "Value": "Page_Sample01",
            "FieldMapping": "FieldMapping_Sample01",
        },
    }


class _StatefulFakeAppRepository(FakeAppRepository):
    """Real stateful get/put: `Navigation.add_page_menu` mints a RANDOM Menu
    id, so a test cannot precompute the "after" draft and queue it -- the
    id would never match. Mirrors the pre-refactor `FakePageClient`'s own
    real-storage behaviour for `get_app_draft`/`put_app_draft`.
    """

    def __init__(self, initial: Navigation) -> None:
        super().__init__()
        self._stored = initial

    async def get_app_draft(self, app_id: str) -> Navigation:
        self.calls.append(("get_app_draft", (app_id,), {}))
        return self._stored

    async def put_app_draft(
        self, app_id: str, new: Navigation, expect_version: str | None
    ) -> Navigation:
        self.calls.append(
            ("put_app_draft", (app_id, new), {"expect_version": expect_version})
        )
        self._stored = new
        return new


def _request(**overrides: Any) -> ForgeSetNavigationRequest:
    fields: dict[str, Any] = {
        "app_id": "App1",
        "page_id": "Page_New",
        "label": "Sample Tab",
    }
    fields.update(overrides)
    return ForgeSetNavigationRequest(**fields)


@pytest.mark.asyncio
async def test_adds_menu_and_verifies() -> None:
    fake = _StatefulFakeAppRepository(Navigation.from_wire(_seed_app_draft()))

    resp = await ForgeSetNavigation(app=fake).execute(_request(unify=False))

    assert resp.menu_id is not None
    assert resp.published is False
    assert resp.snapshot_version == "v1"
    assert [c[0] for c in fake.calls] == [
        "get_app_draft",
        "put_app_draft",
        "get_app_draft",
    ]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_unifies_every_navigation_when_asked() -> None:
    app = _seed_app_draft()
    app["Navigation_Sample02"] = {
        "Id": "Navigation_Sample02",
        "Kind": "Navigation",
        "Name": "Admin Navigation",
        "Application": "Model_Sample01",
        "Navigation::Menu": ["Menu_Sample01"],
    }
    app["Model_Sample01"]["Application::Navigation"].append("Navigation_Sample02")
    fake = _StatefulFakeAppRepository(Navigation.from_wire(app))

    resp = await ForgeSetNavigation(app=fake).execute(_request(unify=True))

    assert resp.menu_id is not None
    read_back = fake._stored.list_navigation()
    assert resp.menu_id in read_back["Navigation_Sample02"], (
        "unify=True must point EVERY Navigation at the new menu too"
    )
    assert set(resp.unified_nav_ids) == {"Navigation_Sample01", "Navigation_Sample02"}


@pytest.mark.asyncio
async def test_no_navigation_node_rejected_before_any_write() -> None:
    fake = _StatefulFakeAppRepository(
        Navigation.from_wire(
            {
                "Root": "M1",
                "_meta_version": "v1",
                "M1": {"Id": "M1", "Kind": "Application"},
            }
        )
    )

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetNavigation(app=fake).execute(_request())

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "no Navigation node" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_app_draft"]


@pytest.mark.asyncio
async def test_sweeps_orphaned_menus_when_asked() -> None:
    app = _seed_app_draft()
    fake = _StatefulFakeAppRepository(Navigation.from_wire(app))

    resp = await ForgeSetNavigation(app=fake).execute(_request(unify=True, sweep=True))

    assert resp.menu_id is not None
    assert resp.swept_orphans == []  # the seed's own Menu_Sample01 stays reachable


@pytest.mark.asyncio
async def test_verify_failure_message_keeps_swept_orphans_findable() -> None:
    """Review fix 1: `sweep=True` already dropped a Menu offline before the
    write, even on a call whose read-back never verifies -- the message
    must still name it (pages_live.py:370-379, pre-refactor, kept
    `swept_orphans` in its own `isError: true` dict)."""
    app = _seed_app_draft()
    app["Menu_Orphan"] = {
        "Id": "Menu_Orphan",
        "Kind": "Menu",
        "Name": "Orphan",
        "Navigation": "Navigation_Sample01",
    }
    seed = Navigation.from_wire(app)
    fake = FakeAppRepository()
    fake.results["get_app_draft"] = [seed, seed]  # unchanged read-back

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetNavigation(app=fake).execute(_request(sweep=True))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "Menu_Orphan" in exc_info.value.message
    assert not any(c[0] == "publish_app" for c in fake.calls)


@pytest.mark.asyncio
async def test_publishes_when_requested_and_verified() -> None:
    fake = _StatefulFakeAppRepository(Navigation.from_wire(_seed_app_draft()))

    resp = await ForgeSetNavigation(app=fake).execute(_request(publish=True))

    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_app_draft",
        "put_app_draft",
        "get_app_draft",
        "publish_app",
    ]


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = _StatefulFakeAppRepository(Navigation.from_wire(_seed_app_draft()))

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeSetNavigation(app=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert fake.calls == []
