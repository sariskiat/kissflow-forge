"""Per-step section visibility over a fully synthetic process draft.

Same rules as the original suite, but every expectation is COMPUTED from the generated
draft (tests/synthetic.py) — no live counts, no real-app content.
"""
from __future__ import annotations

from typing import Any

import pytest
from synthetic import OWNERS, synthetic_process_draft

from kfforge.graph import (
    NO_PERMISSION_NODETYPES,
    progressive_matrix,
    set_step_permissions,
)
from kfforge.types import Visibility

Draft = dict[str, Any]


@pytest.fixture(scope="module")
def draft() -> Draft:
    return synthetic_process_draft()


@pytest.fixture(scope="module")
def matrix(draft: Draft):
    return progressive_matrix(draft, OWNERS)


@pytest.fixture(scope="module")
def applied(draft: Draft, matrix) -> Draft:
    return set_step_permissions(draft, matrix)


def _nodes(d: Draft, kind: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _bearing(d: Draft) -> set[str]:
    return {k for k, v in _nodes(d, "Activity").items()
            if v.get("NodeType") not in NO_PERMISSION_NODETYPES}


def _act(d: Draft, name: str) -> str:
    return next(k for k, v in _nodes(d, "Activity").items() if v.get("Name") == name)


def _section_cols(d: Draft) -> dict[str, list[str]]:
    cols, rows = _nodes(d, "Column"), _nodes(d, "Row")
    out: dict[str, list[str]] = {}
    for sec in cols.values():
        if sec.get("Type") not in ("Section", "Model") or not sec.get("Name"):
            continue
        members = [cid for rid in (sec.get("Column::Row") or [])
                   for cid in ((rows.get(rid) or {}).get("Row::Column") or [])
                   if cid in cols and cols[cid].get("Type") == "Field"]
        out[sec["Name"]] = members
    return out


# ---- matrix shape ----------------------------------------------------------

def test_matrix_covers_every_named_section(draft, matrix):
    secs = _section_cols(draft)
    assert set(matrix) == set(secs)
    assert any(n not in OWNERS for n in secs), "expected an unowned trailing section"


def test_every_row_covers_every_bearing_activity(draft, matrix):
    bearing = _bearing(draft)
    for name, row in matrix.items():
        assert set(row) == bearing, name


def test_editable_at_owner(draft, matrix):
    for sec, owners in OWNERS.items():
        for step in owners:
            assert matrix[sec][_act(draft, step)] == Visibility.EDITABLE, (sec, step)


def test_start_coowns_intake_only(draft, matrix):
    start = _act(draft, "Start")
    assert matrix["Intake"][start] == Visibility.EDITABLE
    assert matrix["Wrap-up"][start] == Visibility.HIDDEN


def test_hidden_before_readonly_after(draft, matrix):
    assert matrix["Wrap-up"][_act(draft, "Assess unit")] == Visibility.HIDDEN
    assert matrix["Intake"][_act(draft, "Wrap-up report")] == Visibility.READONLY


def test_sibling_branches_hidden_from_each_other(draft, matrix):
    assert matrix["Path B"][_act(draft, "Self-help guide")] == Visibility.HIDDEN
    assert matrix["Path A"][_act(draft, "Quick bench review")] == Visibility.HIDDEN
    assert matrix["Path A"][_act(draft, "Assign specialist")] == Visibility.HIDDEN
    assert matrix["Path B"][_act(draft, "Deep repair session")] == Visibility.HIDDEN


def test_unowned_section_readonly_everywhere(draft, matrix):
    other = next(n for n in matrix if n not in OWNERS)
    assert set(matrix[other].values()) == {Visibility.READONLY}


# ---- applying the matrix ---------------------------------------------------

def test_apply_writes_field_level_pairs(draft, applied, matrix):
    secs = _section_cols(draft)
    expected = sum(len(secs[name]) * len(row) for name, row in matrix.items())
    perms = _nodes(applied, "Permission")
    assert len(perms) == expected
    levels = {p["Permission"] for p in perms.values()}
    assert levels <= {"Editable", "ReadOnly", "Hidden"}


def test_backrefs_bidirectional(applied):
    cols, acts = _nodes(applied, "Column"), _nodes(applied, "Activity")
    for pid, p in _nodes(applied, "Permission").items():
        assert pid in (cols[p["Column"]].get("Column::Permission") or [])
        assert pid in (acts[p["Activity"]].get("Activity::Permission") or [])


def test_no_permissions_on_structural_nodes(applied):
    structural = {k for k, v in _nodes(applied, "Activity").items()
                  if v.get("NodeType") in NO_PERMISSION_NODETYPES}
    for p in _nodes(applied, "Permission").values():
        assert p["Activity"] not in structural


def test_apply_is_idempotent(draft, matrix):
    once = set_step_permissions(draft, matrix)
    twice = set_step_permissions(once, matrix)
    assert len(_nodes(once, "Permission")) == len(_nodes(twice, "Permission"))


def test_sparse_matrix_raises(draft, matrix):
    incomplete = {k: v for k, v in matrix.items() if k != "Intake"}
    with pytest.raises(ValueError):
        set_step_permissions(draft, incomplete)
