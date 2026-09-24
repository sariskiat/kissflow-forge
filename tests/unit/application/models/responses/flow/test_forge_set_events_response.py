"""`ForgeSetEventsResponse`: `model_dump(mode="json")` equals today's
`EventReport.as_tool_result()` (pre-refactor) without `isError`, plus
`snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_set_events_response import (
    ForgeSetEventsResponse,
)

# `app.infrastructure.kissflow.client.EventReport.as_tool_result()`'s own key set
# (pre-refactor) -- see fix-9 follow-up note in
# test_kf_apply_field_change_response.py.
OLD_KEYS = {
    "flow_id",
    "fields",
    "verified",
    "missing",
    "triggers",
    "derived",
    "unverified",
    "meta_version",
    "published",
    "isError",
}


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeSetEventsResponse(
        flow_id="F1",
        fields=["Route"],
        verified=["Route"],
        missing=[],
        triggers=["Route (Select) -> onClick"],
        derived=["Route"],
        unverified=[],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert resp.model_dump(mode="json") == {
        "flow_id": "F1",
        "fields": ["Route"],
        "verified": ["Route"],
        "missing": [],
        "triggers": ["Route (Select) -> onClick"],
        "derived": ["Route"],
        "unverified": [],
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeSetEventsResponse(
        flow_id="F1",
        fields=[],
        verified=[],
        missing=[],
        triggers=[],
        derived=[],
        unverified=[],
        meta_version=None,
        published=False,
    )
    assert resp.snapshot_version is None


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    resp = ForgeSetEventsResponse(
        flow_id="F1",
        fields=["Route"],
        verified=["Route"],
        missing=[],
        triggers=["Route (Select) -> onClick"],
        derived=["Route"],
        unverified=[],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }
