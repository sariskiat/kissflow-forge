"""Spec for app.application.models.responses.page.forge_create_page_response."""

from __future__ import annotations

from app.application.models.responses.page.forge_create_page_response import (
    ForgeCreatePageResponse,
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeCreatePageResponse(
        app_id="A1",
        page_id="Page_1",
        name="Sample Page",
        verified=True,
        published=False,
        snapshot_version=None,
    )
    assert resp.model_dump(mode="json") == {
        "app_id": "A1",
        "page_id": "Page_1",
        "name": "Sample Page",
        "verified": True,
        "published": False,
        "snapshot_version": None,
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeCreatePageResponse(
        app_id="A1",
        page_id="Page_1",
        name="Sample Page",
        verified=True,
        published=False,
    )
    assert resp.snapshot_version is None
