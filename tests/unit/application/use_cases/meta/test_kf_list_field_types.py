"""Spec for app.application.use_cases.meta.kf_list_field_types.

Pure and offline -- no port, so no fake is needed. `tests/test_mcp_boundary.py`'s
`test_a_tool_whose_result_has_no_isError_key_is_left_alone` and `test_tools.py`'s
`test_field_type_catalog` assertions are ported here, against the response DTO.
"""

from __future__ import annotations

import pytest

from app.application.models.requests.meta.kf_list_field_types_request import (
    KfListFieldTypesRequest,
)
from app.application.use_cases.meta.kf_list_field_types import KfListFieldTypes
from app.domain.value_objects.field_type import FieldType


@pytest.mark.asyncio
async def test_returns_the_engine_field_type_catalog() -> None:
    resp = await KfListFieldTypes().execute(KfListFieldTypesRequest())

    assert resp.model_dump(mode="json") == [t.value for t in FieldType]
    assert "Text" in resp.model_dump(mode="json")
