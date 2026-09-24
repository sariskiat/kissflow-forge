"""Spec for app.application.models.responses.intake.build_plan.

`tests/fixtures/build_plan_golden/*.json` are the JSON `to_wire(op)` arrays the OLD
dataclass-based `compile.py` produced for a handful of representative specs, captured
before `serde.py` (and its `to_wire`) were deleted. This file proves the new Pydantic
`Op`/`BuildPlan` pair reproduces them exactly: `[op.model_dump(mode="json") for op in
plan.ops]` equals the golden array, for every golden file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.application.models.responses.intake.build_plan import BuildPlan
from app.application.models.responses.intake.op import Op

GOLDEN_DIR = Path(__file__).resolve().parents[5] / "fixtures" / "build_plan_golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.json"))


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_op_model_dump_reproduces_each_golden_build_plan(path: Path) -> None:
    ops_wire = json.loads(path.read_text(encoding="utf-8"))
    plan = BuildPlan(ops=tuple(Op.model_validate(o) for o in ops_wire))
    got = [op.model_dump(mode="json") for op in plan.ops]
    assert got == ops_wire


def test_at_least_the_documented_golden_shapes_are_present() -> None:
    names = {p.stem for p in GOLDEN_FILES}
    assert names == {"full", "linear", "page_design", "page_behavior"}


def test_summary_counts_ops_by_kind() -> None:
    plan = BuildPlan(
        ops=(
            Op(kind="create_process", args={}, why="x"),
            Op(kind="apply_fields", args={}, why="x"),
            Op(kind="apply_fields", args={}, why="x"),
        )
    )
    assert plan.summary() == {"create_process": 1, "apply_fields": 2}


def test_summary_is_computed_from_ops_not_tracked_separately() -> None:
    empty = BuildPlan(ops=())
    assert empty.summary() == {}
