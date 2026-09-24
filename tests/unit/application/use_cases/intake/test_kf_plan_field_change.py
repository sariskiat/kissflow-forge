"""Tests for `KfPlanFieldChange`, ported from `tests/test_tools.py`'s
`plan_field_change` coverage (Stage D group 8; the tool moved from
`app.application.tools.plan_field_change`).
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from app.application.exceptions import ApplicationError
from app.application.models.requests.intake.kf_plan_field_change_request import (
    KfPlanFieldChangeRequest,
)
from app.application.use_cases.intake.kf_plan_field_change import KfPlanFieldChange

FIXTURE = pathlib.Path(__file__).resolve().parents[4] / "fixtures" / "form_draft.json"


def _draft() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.mark.asyncio
async def test_plan_tool_dict_io() -> None:
    use_case = KfPlanFieldChange()
    request = KfPlanFieldChangeRequest(
        draft=_draft(),
        changes=[{"name": "Notes", "type": "Text", "required": True}],
    )
    out = await use_case.execute(request)
    assert out.adds[0].model_dump() == {
        "name": "Notes",
        "type": "Text",
        "required": True,
    }
    assert out.edits == []
    assert "Notes" in out.human_readable


@pytest.mark.asyncio
async def test_plan_tool_rejects_bad_type() -> None:
    """A type outside the closed `FieldType` enum is now rejected by the DTO
    itself, at request-build time, before the use case ever runs -- the
    shape check `coerce_field_specs` used to run by hand. The refusal text
    is the old `app.application.tools._field_type` message, byte for byte."""
    with pytest.raises(ValidationError, match="Nope") as exc_info:
        KfPlanFieldChangeRequest(
            draft=_draft(), changes=[{"name": "x", "type": "Nope"}]
        )
    message = str(exc_info.value)
    assert "is not a field type this engine can build" in message
    assert "kf_list_field_types" in message
    assert "forge_capabilities" in message
    assert "ADR-0004" in message


@pytest.mark.asyncio
async def test_offline_rejection_raises_verify_failed() -> None:
    """A shape `plan_change` itself refuses (not the DTO's job -- e.g. a
    conflict the offline apply detects) surfaces as `VERIFY_FAILED`."""
    use_case = KfPlanFieldChange()
    request = KfPlanFieldChangeRequest(draft={"Root": "Missing"}, changes=[])
    with pytest.raises(ApplicationError) as exc_info:
        await use_case.execute(request)
    assert exc_info.value.code == "VERIFY_FAILED"
