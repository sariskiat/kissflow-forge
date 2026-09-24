"""`ItemService`: the ABC refuses instantiation; the fake implements every abstract
method."""

from __future__ import annotations

import pytest
from tests.fakes.item import FakeItemService

from app.application.interfaces.item import ItemService


def test_item_service_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        ItemService()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakeItemService()

    await fake.create_item("F1")
    await fake.put_fields("F1", "I1", {"Name": "Alice"})
    await fake.get_detail("F1", "I1")
    await fake.submit("F1", "I1", "AI1")
    await fake.reject("F1", "I1", "AI1", "not ready")

    assert [call[0] for call in fake.calls] == [
        "create_item",
        "put_fields",
        "get_detail",
        "submit",
        "reject",
    ]


@pytest.mark.asyncio
async def test_no_call_carries_an_app_id() -> None:
    """The item family is scoped by flow_id alone -- never by application (spec G7
    Part 1)."""
    fake = FakeItemService()
    await fake.create_item("F1")
    _name, args, kwargs = fake.calls[0]
    assert args == ("F1",)
    assert kwargs == {}
