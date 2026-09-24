"""`_styles`: the section/root read-back "landed" checks `ForgeSetStyles`
uses. Ported from `tests/test_client.py`'s `apply_section_style` cases
(pre-refactor). The wire shape of one style value is
`value_objects.style.style_wire_value`, tested in its own mirror file."""

from __future__ import annotations

from app.application.use_cases.flow._styles import (
    _root_style_landed,
    _section_style_landed,
)


def _draft_with_section_style() -> dict:
    return {
        "Sec1": {
            "Type": "Section",
            "Name": "M",
            "Column::Appearance": ["App1"],
        },
        "App1": {"Appearance::Style": ["Style1"]},
        "Style1": {"Value": {"Section.Bg.Color": {"ref": "Color.Info.300"}}},
    }


def test_section_style_landed_true_when_the_value_matches() -> None:
    draft = _draft_with_section_style()
    assert (
        _section_style_landed(draft, "M", {"Section.Bg.Color": "Color.Info.300"})
        is True
    )


def test_section_style_landed_false_for_an_unknown_section() -> None:
    draft = _draft_with_section_style()
    assert _section_style_landed(draft, "NoSuchSection", {}) is False


def test_section_style_landed_false_with_no_appearance_or_style_chain() -> None:
    draft = {"Sec1": {"Type": "Section", "Name": "M"}}
    assert _section_style_landed(draft, "M", {"X": "y"}) is False


def test_section_style_landed_false_when_appearance_has_no_style_chain() -> None:
    draft = {
        "Sec1": {"Type": "Section", "Name": "M", "Column::Appearance": ["App1"]},
        "App1": {},
    }
    assert _section_style_landed(draft, "M", {"X": "y"}) is False


def test_section_style_landed_ignores_none_valued_properties() -> None:
    draft = _draft_with_section_style()
    assert _section_style_landed(draft, "M", {"Removed.Prop": None}) is True


def _draft_with_root_style() -> dict:
    return {
        "Root": "M1",
        "M1": {"Model::Appearance": ["App1"]},
        "App1": {"Appearance::Style": ["Style1"], "HintTextPosition": "Icon"},
        "Style1": {"Value": {"Form.Field.Color": {"ref": "Color.Primary.500"}}},
    }


def test_root_style_landed_true_for_matching_style_and_hint_position() -> None:
    draft = _draft_with_root_style()
    assert (
        _root_style_landed(draft, {"Form.Field.Color": "Color.Primary.500"}, "Icon")
        is True
    )


def test_root_style_landed_false_when_hint_position_disagrees() -> None:
    draft = _draft_with_root_style()
    assert (
        _root_style_landed(draft, {"Form.Field.Color": "Color.Primary.500"}, "Top")
        is False
    )


def test_root_style_landed_false_with_no_appearance_chain() -> None:
    assert _root_style_landed({"Root": "M1", "M1": {}}, {"X": "y"}, None) is False


def test_root_style_landed_false_when_appearance_has_no_style_chain() -> None:
    draft = {"Root": "M1", "M1": {"Model::Appearance": ["App1"]}, "App1": {}}
    assert _root_style_landed(draft, {"X": "y"}, None) is False


def test_root_style_landed_true_with_nothing_requested() -> None:
    draft = _draft_with_root_style()
    assert _root_style_landed(draft, None, None) is True
