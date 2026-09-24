"""Spec for app.application.models.responses.dataset.forge_dataset_records_response."""

from __future__ import annotations

from app.application.models.responses.dataset.forge_dataset_records_response import (
    ForgeDatasetRecordsResponse,
)

_BASE_KEYS = {"flow_id", "op", "created", "listed", "updated", "deleted", "failed"}


def test_create_dump_matches_the_old_base_dict_shape() -> None:
    resp = ForgeDatasetRecordsResponse(
        flow_id="Flow_1", op="create", created=1, record={"_id": "Rec_new"}
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["created"] == 1
    assert dumped["listed"] == 0
    assert dumped["updated"] == 0
    assert dumped["deleted"] == 0
    assert dumped["failed"] == 0
    assert dumped["record"] == {"_id": "Rec_new"}
    assert dumped["snapshot_version"] is None


def test_list_dump_carries_columns_and_records() -> None:
    resp = ForgeDatasetRecordsResponse(
        flow_id="Flow_1",
        op="list",
        listed=2,
        columns=[{"Id": "Name"}],
        records=[{"_id": "Rec_1"}, {"_id": "Rec_2"}],
    )
    assert resp.listed == 2
    assert resp.columns == [{"Id": "Name"}]
    assert len(resp.records) == 2


def test_defaults_are_all_zero_and_empty() -> None:
    resp = ForgeDatasetRecordsResponse(flow_id="Flow_1", op="list")
    assert resp.created == 0
    assert resp.listed == 0
    assert resp.updated == 0
    assert resp.deleted == 0
    assert resp.failed == 0
    assert resp.record is None
    assert resp.record_id is None
    assert resp.columns == []
    assert resp.records == []


def test_create_key_set_matches_the_old_dict_exactly() -> None:
    """`apply_dataset_records`'s `create` branch returns `{**base, "created":
    1, "record": got}` -- no `record_id`, `columns` or `records` key at
    all."""
    resp = ForgeDatasetRecordsResponse(
        flow_id="Flow_1", op="create", created=1, record={"_id": "Rec_new"}
    )
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == _BASE_KEYS | {"record", "snapshot_version"}


def test_update_key_set_matches_the_old_dict_exactly() -> None:
    """`apply_dataset_records`'s `update` branch returns `{**base, "updated":
    1, "record_id": ..., "record": got}` -- no `columns`/`records` key."""
    resp = ForgeDatasetRecordsResponse(
        flow_id="Flow_1",
        op="update",
        updated=1,
        record_id="Rec_1",
        record={"_id": "Rec_1"},
    )
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == _BASE_KEYS | {"record_id", "record", "snapshot_version"}


def test_delete_key_set_matches_the_old_dict_exactly() -> None:
    """`apply_dataset_records`'s `delete` branch returns `{**base, "deleted":
    1, "record_id": ...}` -- no `record`, `columns` or `records` key."""
    resp = ForgeDatasetRecordsResponse(
        flow_id="Flow_1", op="delete", deleted=1, record_id="Rec_1"
    )
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == _BASE_KEYS | {"record_id", "snapshot_version"}


def test_list_key_set_matches_the_old_dict_exactly() -> None:
    """`apply_dataset_records`'s `list` branch returns `{**base, "listed":
    N, "columns": ..., "records": ...}` -- no `record`/`record_id` key, and
    `columns`/`records` stay present even when empty (a real zero-record
    dataform, not an absent key)."""
    resp = ForgeDatasetRecordsResponse(flow_id="Flow_1", op="list", listed=0)
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == _BASE_KEYS | {"columns", "records", "snapshot_version"}
    assert dumped["columns"] == []
    assert dumped["records"] == []
