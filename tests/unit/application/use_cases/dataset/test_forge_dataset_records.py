"""`ForgeDatasetRecords`: ported from `tests/test_client.py`'s
`test_dataset_*` cases (pre-refactor), now against the response DTO or the
raised `ApplicationError` and its code, with
`tests.fakes.dataset.FakeDatasetRepository` and
`tests.fakes.flow.FakeFlowRepository`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.dataset import FakeDatasetRepository
from tests.fakes.flow import FakeFlowRepository

from app.application.exceptions import ApplicationError, RepositoryError
from app.application.models.requests.dataset.forge_dataset_records_request import (
    ForgeDatasetRecordsRequest,
)
from app.application.use_cases.dataset.forge_dataset_records import ForgeDatasetRecords
from app.domain.entities.flow_draft import FlowDraft


def _dataset_draft() -> FlowDraft:
    return FlowDraft.from_wire(
        {
            "Root": "M1",
            "M1": {
                "Id": "M1",
                "Kind": "Model",
                "FlowType": "Dataset",
                "Model::Field": ["Field_a", "Field_b"],
            },
            "Field_a": {
                "Id": "Field_a",
                "Kind": "Field",
                "Name": "Item Name",
                "Model": "M1",
            },
            "Field_b": {
                "Id": "Field_b",
                "Kind": "Field",
                "Name": "Category",
                "Model": "M1",
            },
        }
    )


def _request(**overrides: Any) -> ForgeDatasetRecordsRequest:
    fields: dict[str, Any] = {"flow_id": "Flow_1", "op": "list", "app_id": "App1"}
    fields.update(overrides)
    return ForgeDatasetRecordsRequest(**fields)


class _ConflictingDataset(FakeDatasetRepository):
    """Raises `RepositoryError(code=CONFLICT)` on `create_dataset_record`,
    the way the httpx adapter translates a live 409 (spec G8's conflict
    rule)."""

    async def create_dataset_record(
        self, app_id: str, flow_id: str, record: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(("create_dataset_record", (app_id, flow_id, record), {}))
        raise RepositoryError("duplicate key", code="CONFLICT")


# ============================================================================
# create
# ============================================================================


@pytest.mark.asyncio
async def test_create_resolves_field_names_to_ids() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_dataset_draft()]
    dataset = FakeDatasetRepository()
    dataset.results["create_dataset_record"] = [{"_id": "Rec_new"}]

    resp = await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
        _request(
            op="create",
            record={"Name": "Widget A", "Item Name": "Widget A", "Category": "Tools"},
        )
    )

    assert resp.created == 1
    sent = dataset.calls[0][1][2]
    assert sent == {"Name": "Widget A", "Field_a": "Widget A", "Field_b": "Tools"}
    assert "Item Name" not in sent
    # Review fix 2: no `assert_write_order` here -- the write lands on the
    # DATASET port, not the FLOW port (whose own `get_draft` is only for
    # field-name resolution). The DATASET port itself gets no read-back
    # (see the use case's own module docstring): `create_dataset_record`
    # is its ONLY call, matching `apply_dataset_records`'s pre-refactor
    # behavior exactly.
    assert [c[0] for c in dataset.calls] == ["create_dataset_record"]


@pytest.mark.asyncio
async def test_create_accepts_field_ids_too() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_dataset_draft()]
    dataset = FakeDatasetRepository()

    resp = await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
        _request(
            op="create", record={"Name": "K1", "Field_a": "v", "Category": "Tools"}
        )
    )

    assert resp.created == 1
    sent = dataset.calls[0][1][2]
    assert sent == {"Name": "K1", "Field_a": "v", "Field_b": "Tools"}


@pytest.mark.asyncio
async def test_create_unknown_field_name_fails_loud_before_any_write() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_dataset_draft()]
    dataset = FakeDatasetRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(op="create", record={"Name": "K", "Nope": "x"})
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "Nope" in exc_info.value.message and "Item Name" in exc_info.value.message
    assert dataset.calls == []


@pytest.mark.asyncio
async def test_create_requires_a_non_empty_record() -> None:
    flow = FakeFlowRepository()
    dataset = FakeDatasetRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(op="create", record=None)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert flow.calls == [] and dataset.calls == []


@pytest.mark.asyncio
async def test_create_duplicate_name_is_a_named_conflict() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_dataset_draft()]
    dataset = _ConflictingDataset()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(op="create", record={"Name": "Widget A", "Item Name": "x"})
        )

    assert exc_info.value.code == "CONFLICT"
    assert "Widget A" in exc_info.value.message
    assert "already exists" in exc_info.value.message


@pytest.mark.asyncio
async def test_create_draft_read_failure_is_verify_failed() -> None:
    """Matches `_resolve_dataset_record_keys`'s own translation (pre-refactor
    `client.py`): a draft-read failure during field-name resolution becomes
    a `VERIFY_FAILED` naming "cannot resolve dataform field names", never a
    raw `RepositoryError` -- the same message a caller saw before this
    refactor."""

    class _NoDraft(FakeFlowRepository):
        async def get_draft(self, app_id, kind, flow_id):  # type: ignore[override]
            self.calls.append(("get_draft", (app_id, kind, flow_id), {}))
            raise RepositoryError("draft 500")

    flow = _NoDraft()
    dataset = FakeDatasetRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(op="create", record={"Name": "K", "Item Name": "x"})
        )
    assert exc_info.value.code == "VERIFY_FAILED"
    assert "cannot resolve dataform field names — draft read failed" in (
        exc_info.value.message
    )
    assert dataset.calls == []


# ============================================================================
# update
# ============================================================================


@pytest.mark.asyncio
async def test_update_resolves_and_hits_the_id_scoped_route() -> None:
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [_dataset_draft()]
    dataset = FakeDatasetRepository()

    resp = await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
        _request(op="update", record={"Category": "New"}, record_id="Rec_9")
    )

    assert resp.updated == 1 and resp.record_id == "Rec_9"
    assert dataset.calls[0][1] == ("App1", "Flow_1", "Rec_9", {"Field_b": "New"})


@pytest.mark.asyncio
async def test_update_requires_record_id() -> None:
    flow = FakeFlowRepository()
    dataset = FakeDatasetRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(op="update", record={"Category": "New"})
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "record_id" in exc_info.value.message
    assert dataset.calls == []


# ============================================================================
# delete
# ============================================================================


@pytest.mark.asyncio
async def test_delete_sends_the_name_body() -> None:
    flow = FakeFlowRepository()
    dataset = FakeDatasetRepository()

    resp = await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
        _request(op="delete", record={"Name": "K1"}, record_id="Rec_9")
    )

    assert resp.deleted == 1
    assert dataset.calls[0][1] == ("App1", "Flow_1", "Rec_9", "K1")
    assert flow.calls == []  # delete needs no field-name resolution


@pytest.mark.asyncio
async def test_delete_requires_the_name_body() -> None:
    flow = FakeFlowRepository()
    dataset = FakeDatasetRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(op="delete", record_id="Rec_9")
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "Name" in exc_info.value.message
    assert dataset.calls == []


# ============================================================================
# list
# ============================================================================


@pytest.mark.asyncio
async def test_list_counts_rows() -> None:
    flow = FakeFlowRepository()
    dataset = FakeDatasetRepository()
    dataset.results["list_dataset_records"] = [
        {"Columns": [{"Id": "Name"}], "Data": [{"_id": "Rec_1"}, {"_id": "Rec_2"}]}
    ]

    resp = await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
        _request(op="list")
    )

    assert resp.listed == 2
    assert len(resp.records) == 2
    assert flow.calls == []


# ============================================================================
# common
# ============================================================================


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    flow = FakeFlowRepository()
    dataset = FakeDatasetRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeDatasetRecords(dataset=dataset, flow=flow).execute(
            _request(app_id="")
        )

    assert exc_info.value.code == "REFUSED"
    assert flow.calls == [] and dataset.calls == []
