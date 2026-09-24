"""`ForgeCreateTemplateAppResponse`: `model_dump(mode="json")` equals today's
`create_template_app` success dict (pre-refactor) without `isError`, plus
`snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.app.forge_create_template_app_response import (
    ForgeCreateTemplateAppResponse,
)


def _response(**overrides: object) -> ForgeCreateTemplateAppResponse:
    base: dict[str, object] = {
        "app_id": "App_1",
        "name": "Sample Template App",
        "flow_id": "F1",
        "role_id": "R1",
        "role_name": "Sample Template App Role",
        "members": {"target_flow_id": "F1", "applied": ["R1"], "missing": []},
        "process_status": "Live",
        "app_publish": {
            "app_id": "App_1",
            "published": True,
            "runtime_id": None,
            "meta_version": "v2",
            "note": None,
        },
        "doctor": {"flow_id": "F1", "ok": True, "problems": []},
        "app_url": "https://dev-x.example.com/view/app/App_1",
        "process_url": "https://dev-x.example.com/view/process/F1",
        "url_verified": False,
        "graph_nodes_verified": 12,
    }
    base.update(overrides)
    return ForgeCreateTemplateAppResponse.model_validate(base)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = _response()
    assert resp.model_dump(mode="json") == {
        "app_id": "App_1",
        "name": "Sample Template App",
        "flow_id": "F1",
        "role_id": "R1",
        "role_name": "Sample Template App Role",
        "members": {"target_flow_id": "F1", "applied": ["R1"], "missing": []},
        "process_status": "Live",
        "app_publish": {
            "app_id": "App_1",
            "published": True,
            "runtime_id": None,
            "meta_version": "v2",
            "note": None,
        },
        "doctor": {"flow_id": "F1", "ok": True, "problems": []},
        "app_url": "https://dev-x.example.com/view/app/App_1",
        "process_url": "https://dev-x.example.com/view/process/F1",
        "url_verified": False,
        "graph_nodes_verified": 12,
        "snapshot_version": None,
    }


def test_snapshot_version_defaults_to_none() -> None:
    assert _response().snapshot_version is None
