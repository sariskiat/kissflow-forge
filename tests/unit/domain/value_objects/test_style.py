"""Unit tests for app.domain.value_objects.style.style_wire_value.

Moved out of test__flow_ops.py (G9 review): the function itself moved out of
the entity's private module to a value object, since it carries no
node-graph or entity state of its own.
"""

from __future__ import annotations

import pytest

from app.domain.value_objects.style import style_wire_value


def test_style_wire_value_wraps_a_bare_token_as_a_ref() -> None:
    assert style_wire_value("Section.Bg.Color", "Color.Info.300") == {
        "ref": "Color.Info.300"
    }


def test_style_wire_value_passes_an_explicit_ref_dict_through() -> None:
    given = {"ref": "Color.Info.300"}

    assert style_wire_value("Section.Bg.Color", given) is given


def test_style_wire_value_passes_an_explicit_value_dict_through() -> None:
    given = {"value": "#123456"}

    assert style_wire_value("Section.Bg.Color", given) is given


def test_style_wire_value_rejects_an_unrecognized_dict_key() -> None:
    with pytest.raises(ValueError, match="ref.*value"):
        style_wire_value("Section.Bg.Color", {"nope": "x"})
