"""Pure navigation helpers for `ForgeSetNavigation`.

Ported from `app.infrastructure.kissflow.pages_live.apply_navigation`
(pre-refactor). Both functions here read only `Navigation.list_navigation()`'s
own `{nav_id: [menu_id, ...]}` mapping -- never a raw node dict -- so they
never need to reach into the entity's `.nodes` (CLAUDE.md > lesson 3).
"""

from __future__ import annotations


def new_menu_ids(before: list[str], after: list[str]) -> list[str]:
    """The Menu ids `after` carries that `before` did not.

    Args:
        before: One Navigation's own Menu ids, read before the write.
        after: The same Navigation's Menu ids, read after
            `Navigation.add_page_menu`.

    Returns:
        Every id in `after` absent from `before`, in `after`'s own order.
    """
    seen = set(before)
    return [m for m in after if m not in seen]


def menu_reachable(menu_id: str, navigation: dict[str, list[str]]) -> bool:
    """Is `menu_id` reachable from any Navigation's own Menu list?

    Args:
        menu_id: The Menu id to look for.
        navigation: `Navigation.list_navigation()`'s own mapping, read back
            after the write.

    Returns:
        Whether some Navigation's Menu list contains `menu_id`.
    """
    return any(menu_id in menus for menus in navigation.values())
