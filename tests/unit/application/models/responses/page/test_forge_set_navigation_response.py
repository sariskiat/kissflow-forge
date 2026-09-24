"""Spec for app.application.models.responses.page.forge_set_navigation_response."""

from __future__ import annotations

from app.application.models.responses.page.forge_set_navigation_response import (
    ForgeSetNavigationResponse,
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeSetNavigationResponse(
        app_id="A1",
        menu_id="Menu_1",
        unified_nav_ids=["Navigation_Sample01"],
        swept_orphans=[],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert resp.model_dump(mode="json") == {
        "app_id": "A1",
        "menu_id": "Menu_1",
        "unified_nav_ids": ["Navigation_Sample01"],
        "swept_orphans": [],
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeSetNavigationResponse(
        app_id="A1",
        menu_id=None,
        unified_nav_ids=[],
        swept_orphans=[],
        meta_version=None,
        published=False,
    )
    assert resp.snapshot_version is None
