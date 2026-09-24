"""Tests for `ForgePlanAppResponse` payload parity."""

from __future__ import annotations

from app.application.models.responses.intake.forge_plan_app_response import (
    ForgePlanAppResponse,
)
from app.application.models.responses.intake.op import Op


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgePlanAppResponse(
        ops=[Op(kind="create_process", args={}, why="because")],
        summary={"create_process": 1},
        op_count=1,
    )
    assert response.model_dump(mode="json") == {
        "ops": [{"kind": "create_process", "args": {}, "why": "because"}],
        "summary": {"create_process": 1},
        "op_count": 1,
    }
