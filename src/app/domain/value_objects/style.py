"""Normalizing one style property to its Kissflow wire shape.

Moved out of `entities._flow_ops` (G9 review): a pure string/dict normalizer
with no node-graph or entity state, so it belongs at the value-object level,
not as a private helper only the entity that happens to call it first can
reach. `entities._flow_ops._write_style_props` and
`infrastructure.kissflow.client` both call this same function; neither owns
a copy of its body.
"""

from __future__ import annotations

from typing import Any


def style_wire_value(prop: str, v: str | dict[str, Any]) -> dict[str, Any]:
    """Normalize one style property to its wire shape.

    A bare token string wraps as `{"ref": token}` (the dominant, form-proven
    shape); an explicit `{"ref": ...}` or `{"value": ...}` dict passes
    through verbatim (#11 — the old bare-string type rejected the real
    captured shape at the tool boundary, so styles never landed at all).

    Args:
        prop: The style property name (e.g. `"Section.Bg.Color"`), used only
            to name the property in a refusal.
        v: A bare token string, or an already-wire-shaped `{"ref": ...}` /
            `{"value": ...}` dict.

    Returns:
        The wire-shaped `{"ref": ...}` or `{"value": ...}` dict.

    Raises:
        ValueError: `v` is a dict carrying a key other than `ref`/`value`.
    """
    if isinstance(v, dict):
        if v and set(v) <= {"ref", "value"}:
            return v
        raise ValueError(
            f"style {prop!r}: a dict value must use 'ref' or 'value', got {v!r}"
        )
    return {"ref": v}
