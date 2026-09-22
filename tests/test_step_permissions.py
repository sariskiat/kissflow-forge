"""Per-step section visibility over a fully synthetic process draft.

Same rules as the original suite, but every expectation is COMPUTED from the generated
draft (tests/synthetic.py) — no live counts, no real-app content.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from synthetic import OWNERS, synthetic_process_draft

from app.domain.graph import (
    NO_PERMISSION_NODETYPES,
    add_sequence_number,
    add_table,
    progressive_matrix,
    set_step_permissions,
)
from app.domain.types import FieldType, Visibility

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
    return {
        k
        for k, v in _nodes(d, "Activity").items()
        if v.get("NodeType") not in NO_PERMISSION_NODETYPES
    }


def _act(d: Draft, name: str) -> str:
    return next(k for k, v in _nodes(d, "Activity").items() if v.get("Name") == name)


def _section_cols(d: Draft) -> dict[str, list[str]]:
    cols, rows = _nodes(d, "Column"), _nodes(d, "Row")
    out: dict[str, list[str]] = {}
    for sec in cols.values():
        if sec.get("Type") not in ("Section", "Model") or not sec.get("Name"):
            continue
        members = [
            cid
            for rid in (sec.get("Column::Row") or [])
            for cid in ((rows.get(rid) or {}).get("Row::Column") or [])
            if cid in cols and cols[cid].get("Type") == "Field"
        ]
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
    structural = {
        k
        for k, v in _nodes(applied, "Activity").items()
        if v.get("NodeType") in NO_PERMISSION_NODETYPES
    }
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


# ---- hidden / SequenceNumber columns take no Permissions (#9) --------------
# CLAUDE.md > Visibility: "Hidden columns ... and sequence-number columns themselves
# take no Permissions at all." Rule is stated on column properties, not field names.


@pytest.fixture(scope="module")
def seq_draft(draft: Draft) -> Draft:
    return add_sequence_number(draft, "Running No", "Intake", "TCK-", "0001", "Ticket arrives")


def _seq_col(d: Draft) -> str:
    return next(
        v["Column"] for v in _nodes(d, "Field").values() if v.get("Type") == "SequenceNumber"
    )


def test_sequence_column_gets_no_permissions(seq_draft, matrix):
    applied = set_step_permissions(seq_draft, matrix)
    col = _seq_col(applied)
    assert [p for p in _nodes(applied, "Permission").values() if p["Column"] == col] == []
    assert not (_nodes(applied, "Column")[col].get("Column::Permission") or [])


def test_plain_hidden_column_gets_no_permissions(draft, matrix):
    d = copy.deepcopy(draft)
    f = next(v for v in _nodes(d, "Field").values() if v.get("Name") == "Extra Note")
    col = f["Column"]
    d[col]["IsHidden"] = True
    applied = set_step_permissions(d, matrix)
    assert [p for p in _nodes(applied, "Permission").values() if p["Column"] == col] == []


def test_field_matrix_on_excluded_column_raises(seq_draft, matrix):
    row = next(iter(matrix.values()))
    with pytest.raises(ValueError, match="no Permissions"):
        set_step_permissions(seq_draft, matrix, field_matrix={"Running No": dict(row)})


def test_sequence_exclusion_is_call_order_independent(draft, seq_draft, matrix):
    # the ticket's requirement: seq-then-visibility and visibility-then-seq give the same graph
    seq_first = set_step_permissions(seq_draft, matrix)
    vis_first = add_sequence_number(
        set_step_permissions(draft, matrix),
        "Running No",
        "Intake",
        "TCK-",
        "0001",
        "Ticket arrives",
    )
    assert len(_nodes(seq_first, "Permission")) == len(_nodes(vis_first, "Permission"))
    for d in (seq_first, vis_first):
        col = _seq_col(d)
        assert [p for p in _nodes(d, "Permission").values() if p["Column"] == col] == []


def test_sequence_exclusion_does_not_ride_on_ishidden(seq_draft, matrix):
    # exercise the SequenceNumber clause on its own: a seq column that is NOT IsHidden
    d = copy.deepcopy(seq_draft)
    del d[_seq_col(d)]["IsHidden"]
    applied = set_step_permissions(d, matrix)
    assert [
        p for p in _nodes(applied, "Permission").values() if p["Column"] == _seq_col(applied)
    ] == []


# ---- a table host column takes no Permission and never breaks coverage (#table+vis) ----------
# CLAUDE.md > Tables: a table's HOST column (Type:"Model") sits in its OWN root Row, never a
# Section, and takes NO Permissions — Kissflow shows/hides the whole table, not its host cell.
# Before this fix, set_step_permissions and add_table were mutually exclusive: a table-bearing
# flow was rejected here as "field columns outside every matrix section".


def _table_cols(d: Draft) -> tuple[str, set[str]]:
    """(host column id, {child column ids}) for the single table in the draft."""
    host = next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
    children = {v["Column"] for v in _nodes(d, "Field").values() if v.get("Name") in ("SKU", "Qty")}
    return host, children


def test_table_host_and_child_columns_take_no_permission(draft, matrix):
    d = add_table(draft, "Line Items", [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    host, children = _table_cols(d)
    applied = set_step_permissions(d, progressive_matrix(d, OWNERS))  # no rejection
    perms = _nodes(applied, "Permission")
    assert [p for p in perms.values() if p["Column"] == host] == []
    assert [p for p in perms.values() if p["Column"] in children] == []


def test_section_owner_name_binds_section_not_same_named_table_host(draft):
    # A banner Section and a table can share a Name (the golden "FDE Log": a banner caption above a
    # same-named table). The section-owner name must bind the SECTION node, never the empty
    # table-host Model column. Before the fix, a last-wins name map bound the host, left the real
    # section's field column covered by nothing, and set_step_permissions hard-rejected the flow.
    collide = "Intake"  # an existing Section that OWNS field columns in the synthetic draft
    section_cols = _section_cols(draft)[collide]
    assert section_cols, "precondition: the colliding section must hold at least one field"
    d = add_table(draft, collide, [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    host, children = _table_cols(d)
    applied = set_step_permissions(d, progressive_matrix(d, OWNERS))  # must NOT raise
    perms = _nodes(applied, "Permission")
    # the banner section's own field columns ARE covered (permissions emitted for them)...
    for cid in section_cols:
        assert [p for p in perms.values() if p["Column"] == cid], cid
    # ...and the same-named table host emits no Permission at all.
    assert [p for p in perms.values() if p["Column"] == host] == []
    assert [p for p in perms.values() if p["Column"] in children] == []


def test_table_child_columns_excluded_even_when_nested_model_backref_missing(draft, matrix):
    # A live read-back can drop the nested table Model's `Column` back-ref; the host column's own
    # `Column::Model` must still let the coverage check resolve (and exclude) the table's columns,
    # or a table-bearing flow can never get a visibility matrix. This is the real live break.
    d = add_table(draft, "Line Items", [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    tbl = next(k for k, v in _nodes(d, "Model").items() if v.get("Name") == "Line Items")
    del d[tbl]["Column"]  # simulate the read-back that dropped the back-ref
    host, children = _table_cols(d)
    applied = set_step_permissions(d, progressive_matrix(d, OWNERS))  # must NOT raise
    perms = _nodes(applied, "Permission")
    assert [p for p in perms.values() if p["Column"] == host] == []
    assert [p for p in perms.values() if p["Column"] in children] == []
