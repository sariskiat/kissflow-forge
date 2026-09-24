"""Spec for app.application.models.responses.page.forge_build_page_response.

One response type for both `forge_build_page` entries, but the dump must
equal the OLD dict for whichever entry actually ran -- `PageBuildReport.
as_tool_result()` (pages_live.py near line 118) for `steps`, or
`BuildPageOpReport.as_tool_result()` (near line 494) for `op` -- never a
union of both. The response carries which entry it came from (`entry`), and
a wrap serializer drops both `entry` itself and the other entry's fields.
"""

from __future__ import annotations

from app.application.models.responses.page.forge_build_page_response import (
    ForgeBuildPageResponse,
)

# `PageBuildReport.as_tool_result()`'s own keys, minus `isError` (server.py's
# `forge_build_page` `steps` path returns that dict unchanged on success).
_OLD_STEPS_KEYS = {
    "app_id",
    "page_id",
    "applied",
    "verified",
    "missing",
    "node_counts",
    "meta_version",
    "published",
}

# `BuildPageOpReport.as_tool_result()`'s own keys, minus `isError` (server.py's
# `forge_build_page` `op` path returns that dict unchanged on success).
_OLD_OP_KEYS = {
    "app_id",
    "page_id",
    "page_name",
    "page_created",
    "built",
    "skipped",
    "refused",
    "verified",
    "missing",
    "meta_version",
    "published",
}


def _steps_response(snapshot_version: str | None = None) -> ForgeBuildPageResponse:
    return ForgeBuildPageResponse(
        entry="steps",
        app_id="A1",
        page_id="Page_1",
        applied=["container:Banner=Container_2"],
        verified=["container:Banner=Container_2"],
        missing=[],
        node_counts={"Container": 2},
        meta_version="v2",
        published=False,
        snapshot_version=snapshot_version,
    )


def _op_response(snapshot_version: str | None = None) -> ForgeBuildPageResponse:
    return ForgeBuildPageResponse(
        entry="op",
        app_id="A1",
        page_id="Page_1",
        page_name="Ops Home",
        page_created=True,
        built=["widget:general/label"],
        skipped=["kpi:Open cases: ..."],
        refused=[],
        verified=["widget:general/label"],
        missing=[],
        meta_version="v2",
        published=False,
        snapshot_version=snapshot_version,
    )


def test_steps_entry_key_set_matches_the_old_page_build_report_exactly() -> None:
    """The `steps` path's dump is EXACTLY the old `PageBuildReport.
    as_tool_result()` key set (without `isError`) plus `snapshot_version` --
    never `page_name`/`page_created`/`built`/`skipped`/`refused`, which the
    old dict never had at all on this path."""
    dumped = _steps_response(snapshot_version="v1").model_dump(mode="json")
    assert set(dumped) == _OLD_STEPS_KEYS | {"snapshot_version"}


def test_op_entry_key_set_matches_the_old_build_page_op_report_exactly() -> None:
    """The `op` path's dump is EXACTLY the old `BuildPageOpReport.
    as_tool_result()` key set (without `isError`) plus `snapshot_version` --
    never `applied`/`node_counts`, which the old dict never had at all on
    this path."""
    dumped = _op_response(snapshot_version="v1").model_dump(mode="json")
    assert set(dumped) == _OLD_OP_KEYS | {"snapshot_version"}


def test_steps_path_dump_carries_the_steps_only_values() -> None:
    dumped = _steps_response().model_dump(mode="json")
    assert dumped["applied"] == ["container:Banner=Container_2"]
    assert dumped["node_counts"] == {"Container": 2}


def test_op_path_dump_carries_the_op_only_values() -> None:
    dumped = _op_response().model_dump(mode="json")
    assert dumped["page_name"] == "Ops Home"
    assert dumped["page_created"] is True
    assert dumped["built"] == ["widget:general/label"]


def test_snapshot_version_defaults_to_none() -> None:
    resp = _steps_response()
    assert resp.snapshot_version is None
