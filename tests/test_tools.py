"""Offline tool-layer tests (dict I/O). No framework, no network."""

import copy
import json
import pathlib

import pytest

from app.application.tools import list_field_types, plan_field_change, plan_step_visibility

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


def test_plan_step_visibility_is_offline_and_audited():
    """The preview must report exactly the pair count the writer would emit — a preview that
    counts permission nodes the writer will skip (or misses ones it will write) lies to the
    human being asked to sign off before a DESTRUCTIVE matrix rebuild."""
    from synthetic import OWNERS, synthetic_process_draft

    from app.domain.graph import (
        add_sequence_number,
        progressive_matrix,
        set_step_permissions,
    )

    def _written(d: dict) -> int:
        applied = set_step_permissions(copy.deepcopy(d), progressive_matrix(d, OWNERS))
        return sum(
            1 for v in applied.values() if isinstance(v, dict) and v.get("Kind") == "Permission"
        )

    # plain draft: preview and writer already agree
    base = synthetic_process_draft()
    assert plan_step_visibility(base, OWNERS)["permission_nodes"] == _written(base)

    # a SequenceNumber column inside a section takes no Permission (#9) — the preview must
    # not count the pairs the writer skips
    seq = add_sequence_number(
        copy.deepcopy(base), "Running No", "Intake", "TCK-", "0001", "Ticket arrives"
    )
    assert plan_step_visibility(seq, OWNERS)["permission_nodes"] == _written(seq)

    # a hidden column inside a section is skipped by the writer for the same reason
    hidden = copy.deepcopy(base)
    f = next(v for v in hidden.values() if isinstance(v, dict) and v.get("Name") == "Extra Note")
    hidden[f["Column"]]["IsHidden"] = True
    assert plan_step_visibility(hidden, OWNERS)["permission_nodes"] == _written(hidden)
