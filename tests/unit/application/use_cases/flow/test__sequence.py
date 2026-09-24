"""`_sequence`: the read-back audit helpers `ForgeAddSequenceNumber` uses.
Ported from `tests/test_client.py::test_is_sequence_field_and_verify_helpers`
(pre-refactor)."""

from __future__ import annotations

from app.application.use_cases.flow._sequence import (
    _is_sequence_field,
    _verify_sequence_number,
)


def test_is_sequence_field_rejects_non_dicts() -> None:
    assert _is_sequence_field("not_a_dict", "ID") is False


def test_is_sequence_field_rejects_the_wrong_kind() -> None:
    assert _is_sequence_field({"Kind": "Model"}, "ID") is False


def test_is_sequence_field_rejects_the_wrong_type() -> None:
    assert (
        _is_sequence_field({"Kind": "Field", "Type": "Text", "Name": "ID"}, "ID")
        is False
    )


def test_is_sequence_field_rejects_the_wrong_name() -> None:
    assert (
        _is_sequence_field(
            {"Kind": "Field", "Type": "SequenceNumber", "Name": "Other"}, "ID"
        )
        is False
    )


def test_is_sequence_field_matches_kind_type_and_name() -> None:
    assert (
        _is_sequence_field(
            {"Kind": "Field", "Type": "SequenceNumber", "Name": "ID"}, "ID"
        )
        is True
    )


def test_verify_sequence_number_true_with_three_properties() -> None:
    draft = {
        "F1": {
            "Kind": "Field",
            "Type": "SequenceNumber",
            "Name": "Case ID",
            "Field::Property": ["p1", "p2", "p3"],
        }
    }
    assert _verify_sequence_number(draft, "Case ID") is True


def test_verify_sequence_number_false_with_the_wrong_property_count() -> None:
    draft = {
        "F1": {
            "Kind": "Field",
            "Type": "SequenceNumber",
            "Name": "Case ID",
            "Field::Property": ["only_one_prop"],
        }
    }
    assert _verify_sequence_number(draft, "Case ID") is False


def test_verify_sequence_number_false_when_the_field_is_absent() -> None:
    assert _verify_sequence_number({}, "Case ID") is False
