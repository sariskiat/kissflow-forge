"""Synthetic process draft — built BY the engine itself (dogfood), zero real-app content.

Mirrors the structural difficulty of a real build: a 3-way Parallel, a section co-owned by
Start, and an unowned trailing section. Deterministic (engine ids are name-hashed).
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from kfforge.graph import apply_changes, build_workflow, regroup_into_sections
from kfforge.types import FieldSpec, FieldType

Draft = dict[str, Any]

BASE = pathlib.Path(__file__).parent / "fixtures" / "empty_form_draft.json"

ROLE_FRONT, ROLE_TECH, ROLE_LEAD = "Ro_front_001", "Ro_tech_0002", "Ro_lead_0003"

FIELDS: list[tuple[str, FieldType, bool]] = [
    ("Ticket No", FieldType.TEXT, False),
    ("Contact Date", FieldType.DATE, False),
    ("Unit Serial", FieldType.TEXT, True),
    ("Problem", FieldType.TEXTAREA, True),
    ("Urgency", FieldType.SELECT, False),
    ("Assessment Notes", FieldType.TEXTAREA, False),
    ("Route Choice", FieldType.SELECT, True),
    ("Self-help Doc", FieldType.ATTACHMENT, False),
    ("Self-help Result", FieldType.TEXT, False),
    ("Bench Notes", FieldType.TEXTAREA, False),
    ("Bench Done", FieldType.BOOLEAN, False),
    ("Specialist", FieldType.TEXT, False),
    ("Session Notes", FieldType.TEXTAREA, False),
    ("Deep Done", FieldType.BOOLEAN, False),
    ("Wrap Summary", FieldType.TEXTAREA, True),
    ("Outcome", FieldType.SELECT, False),
    ("Handoff Owner", FieldType.TEXT, False),
    ("Extra Note", FieldType.TEXT, False),          # deliberately unowned -> "Other"
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

STEPS = [("Ticket arrives", ROLE_FRONT), ("Assess unit", ROLE_TECH),
         ("Route to path", ROLE_TECH), ("Wrap-up report", ROLE_LEAD)]
BRANCHES = [
    ("Path A", [("Self-help guide", ROLE_FRONT), ("Verify fix", ROLE_TECH)]),
    ("Path B", [("Quick bench review", ROLE_TECH), ("Bench work", ROLE_TECH)]),
    ("Path C", [("Assign specialist", ROLE_LEAD), ("Book bench slot", ROLE_LEAD),
                ("Deep repair session", ROLE_TECH)]),
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
    draft = apply_changes(draft, [FieldSpec(name=n, type=t, required=r) for n, t, r in FIELDS])
    draft = regroup_into_sections(draft, SECTIONS)
    draft = build_workflow(draft, STEPS, parallel=("Repair paths", BRANCHES),
                           parallel_after=3,
                           roles={ROLE_FRONT: "Front Desk", ROLE_TECH: "Technician",
                                  ROLE_LEAD: "Lead"})
    return draft
