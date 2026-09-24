"""Spec for app.application.use_cases.meta._field_types.

Ported from `tests/test_tools.py::test_field_type_catalog`.
"""

from __future__ import annotations

from app.application.use_cases.meta._field_types import list_field_types
from app.domain.value_objects.field_type import FieldType


def test_lists_every_engine_field_type() -> None:
    ts = list_field_types()

    assert {"Text", "Boolean", "Select", "Date", "User"} <= set(ts)


def test_equals_the_field_type_enum_values_in_order() -> None:
    assert list_field_types() == [t.value for t in FieldType]
