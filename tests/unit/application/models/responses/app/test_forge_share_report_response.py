"""`ForgeShareReportResponse`: `model_dump(mode="json")` equals today's
`apply_report_members` success dict (pre-refactor) without `isError`, plus
`snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.app.forge_share_report_response import (
    ForgeShareReportResponse,
)

_NOTE = (
    "no documented GET route for a report's own member list — not "
    "independently read-back verified, unlike every other write in this engine"
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeShareReportResponse(
        flow_id="F1",
        report_id="Rep1",
        requested=[{"_id": "R1", "Name": "Lead", "Kind": "AppRole"}],
        posted={"ok": True},
        verified=None,
        note=_NOTE,
    )
    assert resp.model_dump(mode="json") == {
        "flow_id": "F1",
        "report_id": "Rep1",
        "requested": [{"_id": "R1", "Name": "Lead", "Kind": "AppRole"}],
        "posted": {"ok": True},
        "verified": None,
        "note": _NOTE,
        "snapshot_version": None,
    }


def test_verified_is_always_none() -> None:
    resp = ForgeShareReportResponse(
        flow_id="F1",
        report_id="Rep1",
        requested=[],
        posted=None,
        verified=None,
        note="",
    )
    assert resp.verified is None
