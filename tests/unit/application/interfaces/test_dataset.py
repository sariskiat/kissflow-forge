"""`DatasetRepository`: the ABC refuses instantiation; the fake implements every
abstract method."""

from __future__ import annotations

import pytest
from tests.fakes.dataset import FakeDatasetRepository

from app.application.interfaces.dataset import DatasetRepository


def test_dataset_repository_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        DatasetRepository()  # type: ignore[abstract]


@pytest.mark.asyncio
async def test_fake_implements_every_abstract_method_in_call_order() -> None:
    fake = FakeDatasetRepository()

    await fake.create_dataset_record("A1", "F1", {"Name": "rec-1"})
    await fake.list_dataset_records("A1", "F1")
    await fake.update_dataset_record("A1", "F1", "rec-1", {"Status": "Done"})
    await fake.delete_dataset_record("A1", "F1", "rec-1", "rec-1")

    assert [call[0] for call in fake.calls] == [
        "create_dataset_record",
        "list_dataset_records",
        "update_dataset_record",
        "delete_dataset_record",
    ]


@pytest.mark.asyncio
async def test_create_dataset_record_records_its_arguments() -> None:
    fake = FakeDatasetRepository()
    await fake.create_dataset_record("A1", "F1", {"Name": "rec-1"})
    assert fake.calls[0] == (
        "create_dataset_record",
        ("A1", "F1", {"Name": "rec-1"}),
        {},
    )
