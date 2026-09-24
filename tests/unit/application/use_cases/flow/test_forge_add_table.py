"""`ForgeAddTable`: ported from `tests/test_client.py`'s `apply_table` cases
(pre-refactor), now against the response DTO or the raised
`ApplicationError` and its code, with `tests.fakes.flow.FakeFlowRepository`.
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.fakes.flow import FakeFlowRepository
from tests.unit.application.use_cases.test_write_order_contract import (
    assert_write_order,
)

from app.application.exceptions import ApplicationError
from app.application.models.requests.flow.forge_add_table_request import (
    ForgeAddTableRequest,
)
from app.application.use_cases.flow.forge_add_table import ForgeAddTable
from app.domain.entities.flow_draft import FlowDraft

_BARE = {
    "Root": "M1",
    "M1": {"Id": "M1", "Kind": "Model", "Name": "F", "FlowType": "Form"},
}


def _request(**overrides: Any) -> ForgeAddTableRequest:
    fields: dict[str, Any] = {
        "flow_id": "F1",
        "name": "Rounds",
        "columns": [("Round", "Number"), ("Notes", "Text")],
        "app_id": "A1",
    }
    fields.update(overrides)
    return ForgeAddTableRequest(**fields)


@pytest.mark.asyncio
async def test_creates_and_verifies_columns() -> None:
    bare = FlowDraft.from_wire(_BARE)
    after = bare.add_table("Rounds", [("Round", "Number"), ("Notes", "Text")])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [bare, after]

    resp = await ForgeAddTable(flow=fake).execute(_request())

    assert resp.created is True
    assert resp.verified_columns == ["Round", "Notes"]
    assert resp.missing_columns == []
    assert resp.published is False
    assert resp.snapshot_version is None
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]
    assert_write_order(fake)


@pytest.mark.asyncio
async def test_is_idempotent_and_writes_nothing_second_time() -> None:
    bare = FlowDraft.from_wire(_BARE)
    existing = bare.add_table("Rounds", [("Round", "Number")])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [existing, existing]

    resp = await ForgeAddTable(flow=fake).execute(
        _request(columns=[("Round", "Number")])
    )

    assert resp.created is False
    assert resp.verified_columns == ["Round"]
    assert [c[0] for c in fake.calls] == ["get_draft", "get_draft"]


@pytest.mark.asyncio
async def test_offline_rejection_never_reaches_put() -> None:
    bare = FlowDraft.from_wire(_BARE)
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [bare]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddTable(flow=fake).execute(_request(columns=[("Grade", "Select")]))

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "offline add_table rejected the spec" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_publishes_when_requested_and_verified() -> None:
    bare = FlowDraft.from_wire(_BARE)
    after = bare.add_table("Rounds", [("Round", "Number")])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [bare, after]

    resp = await ForgeAddTable(flow=fake).execute(
        _request(columns=[("Round", "Number")], publish=True)
    )

    assert resp.published is True
    assert [c[0] for c in fake.calls] == [
        "get_draft",
        "put_draft",
        "get_draft",
        "publish",
    ]


@pytest.mark.asyncio
async def test_missing_columns_raises_verify_failed_and_skips_publish() -> None:
    """Rule 7: a write that did not fully land is a failure, never a success
    response -- the old `isError: true` (missing_columns non-empty) becomes
    a raised `ApplicationError`, not a returned response."""
    bare = FlowDraft.from_wire(_BARE)
    fake = FakeFlowRepository()
    # the read-back never reflects the write (simulates a column that never landed)
    fake.results["get_draft"] = [bare, bare]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddTable(flow=fake).execute(
            _request(columns=[("Round", "Number"), ("Notes", "Text")], publish=True)
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "missing_columns=['Round', 'Notes']" in exc_info.value.message
    assert "published=False" in exc_info.value.message
    assert "write did not fully land" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft", "put_draft", "get_draft"]


@pytest.mark.asyncio
async def test_a_bad_column_spec_on_an_existing_table_is_still_refused() -> None:
    """`brief_stage_d_common.md` review fix 3: the old `_prepare_table_draft`
    always ran `add_table` offline first, even when a table of that name already
    existed -- a table that is a no-op for a GOOD spec must still be refused for
    a BAD one, an unbound Select with no ReferredList (never silently accepted
    because the table already exists)."""
    bare = FlowDraft.from_wire(_BARE)
    existing = bare.add_table("Rounds", [("Round", "Number")])
    fake = FakeFlowRepository()
    fake.results["get_draft"] = [existing]

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddTable(flow=fake).execute(
            _request(name="Rounds", columns=[("Round", "Select")])
        )

    assert exc_info.value.code == "VERIFY_FAILED"
    assert "offline add_table rejected the spec" in exc_info.value.message
    assert [c[0] for c in fake.calls] == ["get_draft"]


@pytest.mark.asyncio
async def test_empty_app_id_is_refused_before_any_call() -> None:
    fake = FakeFlowRepository()

    with pytest.raises(ApplicationError) as exc_info:
        await ForgeAddTable(flow=fake).execute(_request(app_id=""))

    assert exc_info.value.code == "REFUSED"
    assert "no app selected" in exc_info.value.message
    assert fake.calls == []
