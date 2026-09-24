"""Field, flow-reference and diff value objects for the Kissflow builder MCP.

Frozen dataclasses — stdlib only. Split out of the former single domain
types module (G9a): `FieldType`, `EventTrigger`, `Visibility` and
`FlowType` live next door in `field_type.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.value_objects.field_type import FieldType, FlowType


@dataclass(frozen=True)
class FieldSpec:
    """A desired field. field_id=None means CREATE a new field."""

    name: str
    type: FieldType
    required: bool = False
    # The LIST FLOW whose items are this field's options. REQUIRED when `type` is SELECT
    # and meaningless on every other type: a Select with no list is a dropdown bound to
    # nothing, which PUTs 200 and then dies on publish with a bare 500 MetadataError
    # (CLAUDE.md Write path, ReferredList #13). `graph.apply_changes` refuses to mint
    # one.
    referred_list: str | None = None
    field_id: str | None = None
    # Per-type keys the builder writes ONLY on some fields of that type (Textarea
    # `AllowFormatting`, Attachment `CaptureOnly`). NOT universal defaults — a plain
    # Textarea omits `AllowFormatting` and renders fine — so opt-in per field. Written
    # verbatim onto the Field node; values pass through as-is (`False`, "true", …).
    options: dict[str, Any] | None = None


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
    """Preview of a change set. adds/edits are the requested specs; human_readable is
    for confirm."""

    adds: tuple[FieldSpec, ...]
    edits: tuple[FieldSpec, ...]
    skipped: tuple[str, ...]  # names already present (idempotent reconcile)
    human_readable: str
