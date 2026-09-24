"""`AppRepository`: the ABC refuses instantiation; the fake implements every abstract
method."""

from __future__ import annotations

import pytest
from tests.fakes.app import FakeAppRepository

from app.application.interfaces.app import AppRepository
from app.domain.entities.navigation import Navigation


def test_app_repository_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        AppRepository()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakeAppRepository()
    nav = Navigation.from_wire({"_meta_version": "v1"})

    await fake.list_app_roles("A1")
    await fake.get_app_role("Ro1")
    await fake.put_app_role("A1", "Ro1", {"Users": []})
    await fake.get_assignee("jane")
    await fake.create_app_role("Reviewers", "A1")
    await fake.delete_app_role("Ro1")
    await fake.list_applications()
    await fake.create_application("New app")
    await fake.delete_application("A1", archive_first=False)
    await fake.get_app_draft("A1")
    await fake.put_app_draft("A1", nav, "v1")
    await fake.publish_app("A1")

    assert [call[0] for call in fake.calls] == [
        "list_app_roles",
        "get_app_role",
        "put_app_role",
        "get_assignee",
        "create_app_role",
        "delete_app_role",
        "list_applications",
        "create_application",
        "delete_application",
        "get_app_draft",
        "put_app_draft",
        "publish_app",
    ]


@pytest.mark.asyncio
async def test_list_app_roles_defaults_app_id_filter_to_none() -> None:
    fake = FakeAppRepository()
    await fake.list_app_roles()
    assert fake.calls[0] == ("list_app_roles", (), {"app_id": None})


@pytest.mark.asyncio
async def test_get_app_draft_returns_a_navigation_by_default() -> None:
    fake = FakeAppRepository()
    result = await fake.get_app_draft("A1")
    assert isinstance(result, Navigation)
