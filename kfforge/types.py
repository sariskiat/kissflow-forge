"""Typed core for the Kissflow builder MCP. Frozen structs, closed enums."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FieldType(StrEnum):
    # Wire-strings confirmed against live dev fields. Text/Textarea/Date/Boolean/Select/Number/
    # Attachment all seen in the 2026-08-03 read-only sweep (spikes/spike_capture_schema.py, all 7
    # dev flows). User verified in earlier recon (no live User field in the current flows). FINDINGS.md.
    TEXT = "Text"
    TEXTAREA = "Textarea"      # multiline / canvas boxes — a real type, NOT Text + a Widget
    DATE = "Date"
    BOOLEAN = "Boolean"
    SELECT = "Select"
    USER = "User"
    NUMBER = "Number"          # 19 live fields (scores, weights, hours, counts)
    ATTACHMENT = "Attachment"  # 2 live fields (file upload)


class Visibility(StrEnum):
    """What one field column looks like at one workflow step.

    Wire-strings taken from the UI-built oracle (aicase_draft_snapshot.json, 132 Kissflow-generated
    Permission nodes: 118 ReadOnly, 11 Editable, 3 Hidden). There is no fourth value and no
    section-level variant — hiding a section means hiding every field column inside it.
    """
    EDITABLE = "Editable"
    READONLY = "ReadOnly"
    HIDDEN = "Hidden"


class FlowType(StrEnum):
    FORM = "form"
    PROCESS = "process"
    CASE = "case"  # Board, internally


@dataclass(frozen=True)
class FieldSpec:
    """A desired field. field_id=None means CREATE a new field."""
    name: str
    type: FieldType
    required: bool = False
    referred_list: str | None = None  # only for SELECT
    field_id: str | None = None


@dataclass(frozen=True)
class FlowRef:
    account: str
    app_id: str
    flow_id: str
    flow_type: FlowType


@dataclass(frozen=True)
class ParsedField:
    field_id: str
    name: str
    type: FieldType
    required: bool
    column_id: str | None


@dataclass(frozen=True)
class Diff:
    """Preview of a change set. adds/edits are the requested specs; human_readable is for confirm."""
    adds: tuple[FieldSpec, ...]
    edits: tuple[FieldSpec, ...]
    skipped: tuple[str, ...]  # names already present (idempotent reconcile)
    human_readable: str
