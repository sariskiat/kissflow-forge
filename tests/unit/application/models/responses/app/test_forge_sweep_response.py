"""`ForgeSweepResponse`: `model_dump(mode="json")` equals today's `run_sweep`
result dict (pre-refactor), with `isError` replaced by its own negation, `ok`.
A pure read -- no `snapshot_version` field at all."""

from __future__ import annotations

from app.application.models.responses.app.forge_sweep_response import (
    ForgeSweepResponse,
)


def test_model_dump_matches_the_old_result_dict_with_ok_instead_of_is_error() -> None:
    resp = ForgeSweepResponse(
        scope="apps",
        app_id="App1",
        results={
            "apps": {
                "status": "read",
                "count": 1,
                "items": [{"_id": "App_1", "Name": "Demo"}],
                "error": None,
            }
        },
        ok=True,
    )
    assert resp.model_dump(mode="json") == {
        "scope": "apps",
        "app_id": "App1",
        "results": {
            "apps": {
                "status": "read",
                "count": 1,
                "items": [{"_id": "App_1", "Name": "Demo"}],
                "error": None,
            }
        },
        "ok": True,
    }


def test_carries_no_snapshot_version_field() -> None:
    assert "snapshot_version" not in ForgeSweepResponse.model_fields


def test_ok_is_false_when_any_bucket_errored() -> None:
    resp = ForgeSweepResponse(
        scope="all",
        app_id="",
        results={"apps": {"status": "error", "count": 0, "items": [], "error": "boom"}},
        ok=False,
    )
    assert resp.ok is False
