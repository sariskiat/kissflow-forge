"""Spec for app.application.models.responses.item.forge_simulate_case_response."""

from __future__ import annotations

from app.application.models.responses.item.forge_simulate_case_response import (
    ForgeSimulateCaseResponse,
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeSimulateCaseResponse(
        flow_id="Flow_1",
        iid="ITEM-1",
        created=True,
        planned=["step-1", "step-2"],
        filled=["step-1", "step-2"],
        advanced=["step-1", "step-2"],
        rejected=[],
        failed=[],
        error=None,
    )
    assert resp.model_dump(mode="json") == {
        "flow_id": "Flow_1",
        "iid": "ITEM-1",
        "created": True,
        "planned": ["step-1", "step-2"],
        "filled": ["step-1", "step-2"],
        "advanced": ["step-1", "step-2"],
        "rejected": [],
        "failed": [],
        "error": None,
        "snapshot_version": None,
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeSimulateCaseResponse(
        flow_id="Flow_1",
        iid=None,
        created=False,
        planned=[],
        filled=[],
        advanced=[],
        rejected=[],
        failed=[],
        error="create: create failed",
    )
    assert resp.snapshot_version is None
