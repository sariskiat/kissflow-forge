"""Pure read-back audit helpers for `ForgeSetStyles`.

The section/root "landed" checks are copied from the `_landed`/`_root_landed`
closures inside `app.infrastructure.kissflow.client.apply_section_style`
(pre-refactor), adapted to read a `FlowDraft.to_wire()` dict instead of the old
client's raw draft dict. The wire shape of one style value comes from
`app.domain.value_objects.style.style_wire_value`, the one copy of that rule.
"""

from __future__ import annotations

from typing import Any

from app.domain.value_objects.style import style_wire_value

Draft = dict[str, Any]


def _section_style_landed(read_back: Draft, name: str, wanted: dict[str, Any]) -> bool:
    """Whether a section's Style node carries every wanted, non-`None`
    property.

    Args:
        read_back: The flow's wire-format draft (a read-back, for the audit).
        name: The section name to check.
        wanted: The style properties requested for that section.

    Returns:
        Whether the section, its Appearance and its Style node all resolve,
        and the Style's `Value` matches every non-`None` wanted property.
    """
    by_name = {
        v.get("Name"): v
        for v in read_back.values()
        if isinstance(v, dict) and v.get("Type") == "Section"
    }
    sec = by_name.get(name) or {}
    app_ids = sec.get("Column::Appearance") or []
    if not app_ids:
        return False
    app = read_back.get(app_ids[0]) or {}
    style_ids = app.get("Appearance::Style") or []
    if not style_ids:
        return False
    style = read_back.get(style_ids[0]) or {}
    value = style.get("Value") or {}
    return all(
        value.get(k) == style_wire_value(k, v)
        for k, v in wanted.items()
        if v is not None
    )


def _root_style_landed(
    read_back: Draft,
    root_style: dict[str, Any] | None,
    hint_text_position: str | None,
) -> bool:
    """Whether the root Model's Style node carries every wanted, non-`None`
    property, and its Appearance carries the wanted `HintTextPosition`.

    Args:
        read_back: The flow's wire-format draft (a read-back, for the audit).
        root_style: The style properties requested for the root chain.
        hint_text_position: The requested `HintTextPosition`, or `None` when
            not requested.

    Returns:
        Whether the root Model, its Appearance and its Style node all
        resolve, its Style's `Value` matches every non-`None` wanted
        property, and (when requested) `HintTextPosition` matches.
    """
    model_id = read_back.get("Root", "")
    app_ids = (read_back.get(model_id) or {}).get("Model::Appearance") or []
    if not app_ids:
        return False
    app = read_back.get(app_ids[0]) or {}
    style_ids = app.get("Appearance::Style") or []
    if not style_ids:
        return False
    value = (read_back.get(style_ids[0]) or {}).get("Value") or {}
    ok = all(
        value.get(k) == style_wire_value(k, v)
        for k, v in (root_style or {}).items()
        if v is not None
    )
    if hint_text_position is not None:
        ok = ok and app.get("HintTextPosition") == hint_text_position
    return ok
