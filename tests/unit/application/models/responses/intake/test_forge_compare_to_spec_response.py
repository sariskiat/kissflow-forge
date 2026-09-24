"""Tests for `ForgeCompareToSpecResponse` payload parity.

Same key set as today's `CompareReport.as_tool_result()`, minus `isError`,
INCLUDING `ok` -- the shared-brief correction: a verdict tool keeps every
key the old success dict had, never adds one it did not.
"""

from __future__ import annotations

from app.application.models.responses.intake.forge_compare_to_spec_response import (
    ForgeCompareToSpecResponse,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgeCompareToSpecResponse(
        ok=False, mismatches=["a mismatch"], checked={"fields": 5}, ignored=["User"]
    )
    assert response.model_dump(mode="json") == {
        "ok": False,
        "mismatches": ["a mismatch"],
        "checked": {"fields": 5},
        "ignored": ["User"],
    }
