"""`app.application.use_cases.dataset._records`: ported from
`tests/test_client.py`'s `test_dataset_*` field-name-resolution cases
(pre-refactor), now testing the pure `field_name_index`/`resolve_value_keys`
functions directly.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.dataset._records import (
    field_name_index,
    resolve_value_keys,
)


def _dataset_draft() -> dict:
    """Minimal dataform draft: a root Model with two named fields."""
    return {
        "Root": "M1",
        "M1": {
            "Id": "M1",
            "Kind": "Model",
            "FlowType": "Dataset",
            "Model::Field": ["Field_a", "Field_b"],
        },
        "Field_a": {
            "Id": "Field_a",
            "Kind": "Field",
            "Name": "Item Name",
            "Model": "M1",
        },
        "Field_b": {
            "Id": "Field_b",
            "Kind": "Field",
            "Name": "Category",
            "Model": "M1",
        },
    }


def test_field_name_index_maps_names_to_ids() -> None:
    idx = field_name_index(_dataset_draft())
    assert idx == {"Item Name": "Field_a", "Category": "Field_b"}


def test_resolve_value_keys_resolves_names_and_passes_name_through() -> None:
    idx = field_name_index(_dataset_draft())
    resolved = resolve_value_keys(
        {"Name": "Widget A", "Item Name": "Widget A", "Category": "Tools"},
        idx,
        passthrough=frozenset({"Name"}),
    )
    assert resolved == {"Name": "Widget A", "Field_a": "Widget A", "Field_b": "Tools"}
    assert "Item Name" not in resolved and "Category" not in resolved


def test_resolve_value_keys_accepts_field_ids_too() -> None:
    idx = field_name_index(_dataset_draft())
    resolved = resolve_value_keys(
        {"Name": "K1", "Field_a": "v", "Category": "Tools"},
        idx,
        passthrough=frozenset({"Name"}),
    )
    assert resolved == {"Name": "K1", "Field_a": "v", "Field_b": "Tools"}


def test_resolve_value_keys_unknown_field_name_fails_loud() -> None:
    idx = field_name_index(_dataset_draft())
    with pytest.raises(ValueError, match="Nope") as exc_info:
        resolve_value_keys(
            {"Name": "K", "Nope": "x"}, idx, passthrough=frozenset({"Name"})
        )
    assert "Item Name" in str(exc_info.value)  # lists available names
