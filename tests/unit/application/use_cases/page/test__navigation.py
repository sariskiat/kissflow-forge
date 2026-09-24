"""Spec for app.application.use_cases.page._navigation."""

from __future__ import annotations

from app.application.use_cases.page._navigation import menu_reachable, new_menu_ids


def test_new_menu_ids_returns_only_the_added_ones() -> None:
    assert new_menu_ids(["Menu_1"], ["Menu_1", "Menu_2"]) == ["Menu_2"]


def test_new_menu_ids_empty_when_nothing_added() -> None:
    assert new_menu_ids(["Menu_1"], ["Menu_1"]) == []


def test_new_menu_ids_preserves_after_order() -> None:
    assert new_menu_ids([], ["Menu_2", "Menu_1"]) == ["Menu_2", "Menu_1"]


def test_menu_reachable_true_when_some_navigation_carries_it() -> None:
    nav = {"Navigation_1": ["Menu_1"], "Navigation_2": ["Menu_2"]}
    assert menu_reachable("Menu_2", nav) is True


def test_menu_reachable_false_when_no_navigation_carries_it() -> None:
    nav = {"Navigation_1": ["Menu_1"]}
    assert menu_reachable("Menu_9", nav) is False


def test_menu_reachable_false_on_an_empty_navigation_map() -> None:
    assert menu_reachable("Menu_1", {}) is False
