"""`PageRepository`: the ABC refuses instantiation; the fake implements every abstract
method."""

from __future__ import annotations

import pytest
from tests.fakes.page import FakePageRepository

from app.application.interfaces.page import PageRepository
from app.domain.entities.page_draft import PageDraft


def test_page_repository_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        PageRepository()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakePageRepository()
    draft = PageDraft.from_wire({"_meta_version": "v1"})

    await fake.list_pages("A1")
    await fake.create_page("A1", "Dashboard")
    await fake.delete_page("A1", "P1")
    await fake.get_page_draft("A1", "P1")
    await fake.put_page_draft("A1", "P1", draft, "v1")
    await fake.publish_page("A1", "P1")

    assert [call[0] for call in fake.calls] == [
        "list_pages",
        "create_page",
        "delete_page",
        "get_page_draft",
        "put_page_draft",
        "publish_page",
    ]


@pytest.mark.asyncio
async def test_get_page_draft_returns_a_page_draft_by_default() -> None:
    fake = FakePageRepository()
    result = await fake.get_page_draft("A1", "P1")
    assert isinstance(result, PageDraft)
