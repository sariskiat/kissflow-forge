"""Offline tool-layer tests (dict I/O). No framework, no network."""
import json
import pathlib

import pytest

from kfforge.tools import list_field_types, plan_field_change

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "form_draft.json"


def _draft() -> dict:
    return json.loads(FIXTURE.read_text())


def test_field_type_catalog():
    ts = list_field_types()
    assert {"Text", "Boolean", "Select", "Date", "User"} <= set(ts)


def test_plan_tool_dict_io():
    out = plan_field_change(_draft(), [{"name": "Notes", "type": "Text", "required": True}])
    assert out["adds"][0] == {"name": "Notes", "type": "Text", "required": True}
    assert out["edits"] == []
    assert "Notes" in out["human_readable"]


def test_plan_tool_rejects_bad_type():
    with pytest.raises((ValueError, TypeError, KeyError)):
        plan_field_change(_draft(), [{"name": "x", "type": "Nope"}])
