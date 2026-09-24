"""Synthetic process draft — built BY the engine itself (dogfood), zero real-app content.

Mirrors the structural difficulty of a real build: a 3-way Parallel, a section co-owned by
Start, and an unowned trailing section. Deterministic (engine ids are name-hashed).
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

from app.domain.entities.flow_draft import FlowDraft
from app.domain.value_objects.field_spec import FieldSpec
from app.domain.value_objects.field_type import FieldType

Draft = dict[str, Any]

BASE = pathlib.Path(__file__).parent / "fixtures" / "empty_form_draft.json"

ROLE_FRONT, ROLE_TECH, ROLE_LEAD = "Ro_front_001", "Ro_tech_0002", "Ro_lead_0003"

# A Select's OPTIONS live in a SEPARATE list flow, never in this graph — so every Select below
# names one (neutral ids, no real list on any tenant). A bare Select is a dropdown bound to
# nothing: `apply_changes` refuses to mint one, and `verify.doctor` rule 7b flags any that arrives
# from a template or a hand-built draft.
LIST_URGENCY, LIST_ROUTE, LIST_OUTCOME = (
    "List_Sample01",
    "List_Sample02",
    "List_Sample03",
)

# (name, type, required, referred_list) — the list id is None for every type that is not a Select.
FIELDS: list[tuple[str, FieldType, bool, str | None]] = [
    ("Ticket No", FieldType.TEXT, False, None),
    ("Contact Date", FieldType.DATE, False, None),
    ("Unit Serial", FieldType.TEXT, True, None),
    ("Problem", FieldType.TEXTAREA, True, None),
    ("Urgency", FieldType.SELECT, False, LIST_URGENCY),
    ("Assessment Notes", FieldType.TEXTAREA, False, None),
    ("Route Choice", FieldType.SELECT, True, LIST_ROUTE),
    ("Self-help Doc", FieldType.ATTACHMENT, False, None),
    ("Self-help Result", FieldType.TEXT, False, None),
    ("Bench Notes", FieldType.TEXTAREA, False, None),
    ("Bench Done", FieldType.BOOLEAN, False, None),
    ("Specialist", FieldType.TEXT, False, None),
    ("Session Notes", FieldType.TEXTAREA, False, None),
    ("Deep Done", FieldType.BOOLEAN, False, None),
    ("Wrap Summary", FieldType.TEXTAREA, True, None),
    ("Outcome", FieldType.SELECT, False, LIST_OUTCOME),
    ("Handoff Owner", FieldType.TEXT, False, None),
    ("Extra Note", FieldType.TEXT, False, None),  # deliberately unowned -> "Other"
]

SECTIONS: list[tuple[str, list[str]]] = [
    ("Intake", ["Ticket No", "Contact Date", "Unit Serial", "Problem"]),
    ("Assessment", ["Urgency", "Assessment Notes"]),
    ("Route", ["Route Choice"]),
    ("Path A", ["Self-help Doc", "Self-help Result"]),
    ("Path B", ["Bench Notes", "Bench Done"]),
    ("Path C", ["Specialist", "Session Notes", "Deep Done"]),
    ("Wrap-up", ["Wrap Summary", "Outcome", "Handoff Owner"]),
]

STEPS: list[tuple[str, str | None]] = [
    ("Ticket arrives", ROLE_FRONT),
    ("Assess unit", ROLE_TECH),
    ("Route to path", ROLE_TECH),
    ("Wrap-up report", ROLE_LEAD),
]
BRANCHES: list[tuple[str, list[tuple[str, str | None]]]] = [
    ("Path A", [("Self-help guide", ROLE_FRONT), ("Verify fix", ROLE_TECH)]),
    ("Path B", [("Quick bench review", ROLE_TECH), ("Bench work", ROLE_TECH)]),
    (
        "Path C",
        [
            ("Assign specialist", ROLE_LEAD),
            ("Book bench slot", ROLE_LEAD),
            ("Deep repair session", ROLE_TECH),
        ],
    ),
]

OWNERS: dict[str, list[str]] = {
    # Start co-owns Intake ON PURPOSE: StartEvent IS the submission form.
    "Intake": ["Start", "Ticket arrives"],
    "Assessment": ["Assess unit"],
    "Route": ["Route to path"],
    "Path A": ["Self-help guide", "Verify fix"],
    "Path B": ["Quick bench review", "Bench work"],
    "Path C": ["Assign specialist", "Book bench slot", "Deep repair session"],
    "Wrap-up": ["Wrap-up report"],
    # "Other" (holding Extra Note) deliberately unowned -> ReadOnly everywhere.
}


def synthetic_process_draft() -> Draft:
    draft: Draft = json.loads(BASE.read_text())
    flow = FlowDraft.from_wire(draft).apply_changes(
        [
            FieldSpec(name=n, type=t, required=r, referred_list=rl)
            for n, t, r, rl in FIELDS
        ]
    )
    flow = flow.regroup_into_sections(SECTIONS)
    flow = flow.build_workflow(
        STEPS,
        parallel=("Repair paths", BRANCHES),
        parallel_after=3,
        roles={ROLE_FRONT: "Front Desk", ROLE_TECH: "Technician", ROLE_LEAD: "Lead"},
    )
    return flow.to_wire()


def with_goto_and_event(draft: Draft) -> Draft:
    """Layer a minimal backward-loop GotoTask + Boolean gate + Activity::Expression condition,
    plus one field Event, onto an already-built process draft. Pure: returns a NEW draft.

    Wire shapes match what the builder itself writes (captured live from a UI-built flow,
    documented in the project's CLAUDE.md): a GotoTask edge node with a `Goto` back-ref, an
    `Activity::Expression` loop condition testing a Boolean field against the zero-arg `false()`
    literal, and an Event node whose script references the gate field by its own
    (platform-prefixed) id — the smallest shape that is genuinely CLEAN under
    `FlowDraft.problems`, so seeded-defect tests can mutate a deep copy of it
    to break exactly one thing.

    Ids are deliberately neutral (`Activity_Sample01` style — no app-specific names). Applied
    AFTER step permissions are set: a GotoTask renders no form of its own and correctly carries
    no Permission, matching how the builder behaves when a loop is added to an already-wired flow.
    """
    new: Draft = copy.deepcopy(draft)
    root = new["Root"]
    model = new[root]

    pd_id = model["RootProcessDef"]
    pd = new[pd_id]
    chain = list(pd["ProcessDef::Activity"])
    if len(chain) < 2:
        raise ValueError(
            "draft's workflow needs Start + at least one real step to loop back to"
        )
    target_id = chain[1]  # loop back to the first real step after Start

    gate_id = "Field_SampleGate01"
    new[gate_id] = {
        "Id": gate_id,
        "Kind": "Field",
        "Type": "Boolean",
        "Name": "Sample Gate",
        "Model": root,
        "CreatedAt": "2026-01-01T00:00:00.000Z",
        "Required": False,
    }
    model.setdefault("Model::Field", []).append(gate_id)

    goto_id = "Activity_SampleGoto01"
    new[goto_id] = {
        "Id": goto_id,
        "Kind": "Activity",
        "NodeType": "GotoTask",
        "Name": "Goto-Sample",
        "ProcessDef": pd_id,
        "CreatedAt": "2026-01-01T00:00:00.000Z",
        "Goto": target_id,
    }
    new[target_id].setdefault("Goto::Activity", []).append(goto_id)
    pd["ProcessDef::Activity"] = [*chain, goto_id]  # GotoTask sits LAST

    # loop condition: Sample Gate = false()
    lhs_id, rhs_id, cond_root_id, expr_id = (
        "Node_SampleLhs01",
        "Node_SampleRhs01",
        "Node_SampleRoot01",
        "Expression_SampleCond01",
    )
    new[lhs_id] = {
        "Id": lhs_id,
        "Type": "Field",
        "Field": gate_id,
        "DataType": "Boolean",
        "Node": cond_root_id,
    }
    new[rhs_id] = {
        "Id": rhs_id,
        "Type": "Function",
        "Value": "false",
        "DataType": "Boolean",
        "Category": "Boolean",
        "Node": cond_root_id,
    }
    new[cond_root_id] = {
        "Id": cond_root_id,
        "Type": "Function",
        "Value": "=",
        "Syntax": "Infix",
        "DataType": "Boolean",
        "Category": "Boolean",
        "FieldRefCount": 1,
        "Node::Node": [lhs_id, rhs_id],
    }
    new[expr_id] = {
        "Id": expr_id,
        "Kind": "Expression",
        "ExpressionStr": f"{gate_id} = false()",
        "Activity": goto_id,
        "Expression::Node": [cond_root_id],
    }
    new[goto_id]["Activity::Expression"] = [expr_id]
    new[gate_id]["Field::Node"] = [lhs_id]

    # one Event on the gate field: a script that references the gate field's OWN platform-
    # prefixed id, so this baseline shape is provably clean (nothing it references is missing).
    event_id = "Event_SampleSet01"
    new[event_id] = {
        "Id": event_id,
        "Kind": "Event",
        "Field": gate_id,
        "Trigger": "onChange",
        "Script": f"(async () => {{ kf.form.setFieldValue('{gate_id}', false); }})();",
    }
    new[gate_id]["Field::Event"] = [event_id]

    return new
