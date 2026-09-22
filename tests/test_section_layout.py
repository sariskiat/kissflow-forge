"""The section-layout fact base — app.domain.graph.section_layout.

One frozen context object holds everything the visibility machinery knows about a draft's
sections and columns, so the writer (set_step_permissions), the auditor (verify.doctor) and the
preview (tools.plan_step_visibility) stop each re-walking the graph with their own copy of the
rules. These tests pin the FACT BASE itself: name resolution (Section beats a same-named table
host), membership, and the no-Permission exclusions.

Behavior tests only — every expectation is computed from the generated synthetic draft, no live
Kissflow content.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from synthetic import OWNERS, synthetic_process_draft

from app.domain.graph import add_sequence_number, add_table, section_layout
from app.domain.types import FieldType

Draft = dict[str, Any]


@pytest.fixture(scope="module")
def draft() -> Draft:
    return synthetic_process_draft()


def _nodes(d: Draft, kind: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if isinstance(v, dict) and v.get("Kind") == kind}


def _col_of_field(d: Draft, field_name: str) -> str:
    return next(v["Column"] for v in _nodes(d, "Field").values() if v.get("Name") == field_name)


def _section_id(d: Draft, name: str) -> str:
    return next(
        k
        for k, v in _nodes(d, "Column").items()
        if v.get("Type") == "Section" and v.get("Name") == name
    )


def _section_field_cols(d: Draft, name: str) -> set[str]:
    """Field-type columns directly inside a named Section — the layout's own expectation."""
    sid = _section_id(d, name)
    return {
        cid
        for rid in (d[sid].get("Column::Row") or [])
        for cid in (d.get(rid) or {}).get("Row::Column") or []
        if d[cid].get("Type") == "Field"
    }


def test_layout_names_every_section(draft: Draft) -> None:
    layout = section_layout(draft)
    assert set(layout.section_id_of_name) == set(OWNERS) | {"Other"}
    for name, sid in layout.section_id_of_name.items():
        assert draft[sid].get("Type") == "Section", name
        assert draft[sid].get("Name") == name


def test_layout_members_are_section_field_columns(draft: Draft) -> None:
    layout = section_layout(draft)
    for name in OWNERS:
        sid = layout.section_id_of_name[name]
        assert set(layout.members[sid]) == _section_field_cols(draft, name), name
    # an unowned trailing section is a member like any other
    other = layout.section_id_of_name["Other"]
    assert set(layout.members[other]) == _section_field_cols(draft, "Other")


def test_owner_section_maps_column_to_its_section(draft: Draft) -> None:
    layout = section_layout(draft)
    assert layout.owner_section(_col_of_field(draft, "Ticket No")) == "Intake"
    assert layout.owner_section(_col_of_field(draft, "Bench Notes")) == "Path B"
    assert layout.owner_section(_col_of_field(draft, "Extra Note")) == "Other"


def test_no_permission_columns_include_hidden_and_sequence(draft: Draft) -> None:
    d = add_sequence_number(
        copy.deepcopy(draft), "Running No", "Intake", "TCK-", "0001", "Ticket arrives"
    )
    layout = section_layout(d)
    seq_col = _col_of_field(d, "Running No")
    assert seq_col in layout.no_permission_columns

    d2 = copy.deepcopy(draft)
    hidden_col = _col_of_field(d2, "Extra Note")
    d2[hidden_col]["IsHidden"] = True
    layout2 = section_layout(d2)
    assert hidden_col in layout2.no_permission_columns


def test_table_exclusions_detected(draft: Draft) -> None:
    d = add_table(draft, "Line Items", [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    layout = section_layout(d)
    host = next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
    children = {_col_of_field(d, "SKU"), _col_of_field(d, "Qty")}
    assert host in layout.table_host_columns
    assert children <= layout.table_child_columns
    # a table host column takes no Permission, so it is excluded from the section-member
    # machinery's write targets too (the coverage rule's own subtraction)
    assert host not in layout.no_permission_columns


def test_section_name_beats_same_named_table_host(draft: Draft) -> None:
    # The golden "banner above a same-named table" pattern (CLAUDE.md > Tables): a Section and a
    # table host Model may share a Name. Name resolution must bind the SECTION node, never the
    # empty host column — the e23f8f2 fix's rule, now pinned on the fact base itself.
    collide = "Intake"
    d = add_table(draft, collide, [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    layout = section_layout(d)
    assert layout.section_id_of_name[collide] == _section_id(d, collide)
    # the colliding host is still a table host (its own signal is untouched)
    host = next(
        k
        for k, v in _nodes(d, "Column").items()
        if v.get("Type") == "Model" and v.get("Name") == collide
    )
    assert host in layout.table_host_columns


def test_model_name_kept_as_fallback_when_no_section_owns_it(draft: Draft) -> None:
    d = add_table(draft, "Line Items", [("SKU", FieldType.TEXT), ("Qty", FieldType.NUMBER)])
    layout = section_layout(d)
    host = next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
    assert layout.section_id_of_name["Line Items"] == host
    # a Model unit governs exactly its own host column (CLAUDE.md > Tables: the whole table is
    # one unit — and the host takes no Permission, so this row emits nothing at write time)
    assert layout.members[host] == (host,)
    assert layout.owner_section(host) == "Line Items"


def test_owner_section_covers_model_host_nested_inside_a_section(draft: Draft) -> None:
    # The doctor's old secof walk credited a Model host NESTED in a Section's row to that
    # section (the "table nested inside a section" case). owner_section must mirror that: a
    # column directly in a Section's rows belongs to the Section, whatever its Type.
    d = copy.deepcopy(draft)
    host = (
        next(k for k, v in _nodes(d, "Column").items() if v.get("Type") == "Model")
        if any(v.get("Type") == "Model" for v in _nodes(d, "Column").values())
        else None
    )
    if host is None:  # plant a Model column inside the Intake section's first row
        rows = d[_section_id(d, "Intake")].get("Column::Row") or []
        row_id = rows[0]
        host = "Column_FakeTableHost"
        d[host] = {
            "Id": host,
            "Kind": "Column",
            "Type": "Model",
            "Name": "Fake Table",
            "Row": row_id,
            "Column::Model": ["Model_FakeTable"],
        }
        d[row_id]["Row::Column"].append(host)
        d["Model_FakeTable"] = {
            "Id": "Model_FakeTable",
            "Kind": "Model",
            "Name": "Fake Table",
            "Model": d["Root"],
            "Column": host,
        }
    layout = section_layout(d)
    assert layout.owner_section(host) == "Intake"
