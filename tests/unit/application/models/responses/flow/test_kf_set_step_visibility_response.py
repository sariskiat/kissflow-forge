"""`KfSetStepVisibilityResponse`: same free-form-shape reasoning as
`ForgeSetVisibilityResponse` -- see that DTO's test module."""

from __future__ import annotations

from app.application.models.responses.flow.kf_set_step_visibility_response import (
    KfSetStepVisibilityResponse,
)

# `app.infrastructure.kissflow.client.StepPermissionReport.as_tool_result()`'s own
# key set (pre-refactor). `note` is set on BOTH branches of that method, so it is
# in the base set too -- see fix-9 follow-up note in
# test_kf_apply_field_change_response.py.
OLD_KEYS_BASE = {
    "flow_id",
    "pair_counts",
    "missing",
    "by_section",
    "by_step",
    "uncovered_sections",
    "remediation",
    "summarised",
    "meta_version",
    "published",
    "note",
    "isError",
}
OLD_KEYS_INCLUDE_PAIRS = OLD_KEYS_BASE | {"pairs", "collateral"}


def test_model_dump_equals_the_wrapped_dict_exactly() -> None:
    payload = {
        "flow_id": "F1",
        "pair_counts": {
            "added": 1,
            "skipped": 0,
            "verified": 1,
            "missing": 0,
            "collateral": 0,
        },
        "missing": [],
        "by_section": ["Intake: 1 pair(s) written, 1 verified, 0 missing"],
        "by_step": ["Start: 1 pair(s) written, 1 verified, 0 missing"],
        "uncovered_sections": [],
        "remediation": [],
        "summarised": 1,
        "meta_version": "v2",
        "published": True,
        "note": "1 pair entries summarised ...",
        "snapshot_version": "v1",
    }
    resp = KfSetStepVisibilityResponse(payload)
    assert resp.model_dump(mode="json") == payload
    assert "isError" not in resp.model_dump(mode="json")


def test_key_set_matches_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    base_payload: dict[str, object] = {
        "flow_id": "F1",
        "pair_counts": {
            "added": 0,
            "skipped": 0,
            "verified": 0,
            "missing": 0,
            "collateral": 0,
        },
        "missing": [],
        "by_section": [],
        "by_step": [],
        "uncovered_sections": [],
        "remediation": [],
        "summarised": 0,
        "meta_version": "v2",
        "published": False,
        "note": "...",
        "snapshot_version": "v1",
    }
    resp = KfSetStepVisibilityResponse(base_payload)
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS_BASE - {"isError"}) | {
        "snapshot_version"
    }

    with_pairs_payload = dict(base_payload)
    with_pairs_payload["pairs"] = {
        "added": [],
        "skipped": [],
        "verified": [],
        "missing": [],
    }
    with_pairs_payload["collateral"] = []
    resp = KfSetStepVisibilityResponse(with_pairs_payload)
    assert set(resp.model_dump(mode="json")) == (
        OLD_KEYS_INCLUDE_PAIRS - {"isError"}
    ) | {"snapshot_version"}
