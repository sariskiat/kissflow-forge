"""`DocsReader`: the ABC refuses instantiation; the fake implements every abstract
method."""

from __future__ import annotations

import pytest
from tests.fakes.docs import FakeDocsReader

from app.application.interfaces.docs import DocsReader


def test_docs_reader_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        DocsReader()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakeDocsReader()

    await fake.playbook()
    await fake.capabilities("workflow")

    assert [call[0] for call in fake.calls] == ["playbook", "capabilities"]


@pytest.mark.asyncio
async def test_capabilities_defaults_query_to_empty_string() -> None:
    fake = FakeDocsReader()
    await fake.capabilities()
    assert fake.calls[0] == ("capabilities", (), {"query": ""})
