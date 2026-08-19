"""Typed core for the Kissflow builder MCP. Frozen structs, closed enums."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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


class EventTrigger(StrEnum):
    """The field-event trigger string (CLAUDE.md Field events). All three wire strings are now
    LIVE-OBSERVED on a published flow (2026-08-10 eval-case-1 read, issue #12 — replacing the
    earlier "per-docs guess" belief outright): a Select source fires `onClick`, Date and Number
    sources fire `onSelect`, Text/Textarea sources fire `onChange`. The trigger is a FUNCTION of
    the SOURCE field's type — derive it with `trigger_for`, never pick it by hand: a wrong
    trigger writes fine, publishes fine, and simply never fires.

    Lives here, not in `kfforge.intake.schema` where it was born, because BOTH the spec layer
    (intake/compile) and the live write path (client.apply_field_events) must derive from the
    same table — a second copy is how a Select ends up with `onChange` on one route and
    `onClick` on the other. `kfforge.intake.schema` re-exports it, so every existing import site
    still resolves to this one enum.
    """
    ON_CHANGE = "onChange"  # live: Text, Textarea
    ON_SELECT = "onSelect"  # live: Date, Number · family-inferred, unverified: User
    ON_CLICK = "onClick"    # live: Select        · family-inferred, unverified: Boolean


# The (source type -> trigger) pairs actually observed on a live published flow. A derivation for
# a type OUTSIDE this set still compiles, but the plan flags it UNVERIFIED so the uncertainty
# travels with the op instead of getting silently smoothed over.
TRIGGER_LIVE_CONFIRMED: frozenset[FieldType] = frozenset({
    FieldType.TEXT, FieldType.TEXTAREA, FieldType.DATE, FieldType.NUMBER, FieldType.SELECT,
})


# Wire `Type` strings that can NEVER carry an event: the builder offers no Event tab for them, so
# there is no trigger string to find no matter how hard you look (CLAUDE.md Field events names
# six types — Attachment, Image, Rich text, Signature, Sequence number, Geolocation).
#
# Only FIVE are listed, and that is deliberate, not an oversight:
#   * Attachment / Image / Signature / SequenceNumber are captured wire strings
#     (types.FieldType.ATTACHMENT, shapes/field_image.json, shapes/field_signature.json,
#     graph.add_sequence_number).
#   * "Geolocation" is the field-palette name; its node shape is NOT captured
#     (docs/capabilities/field.geolocation.md — copilot refuses the type). It is listed anyway
#     because the only thing a wrong guess here can do is REFUSE a field that does not exist,
#     never write one.
#   * "Rich text" is deliberately ABSENT. Its wire shape is not captured either, and its inferred
#     shape (docs/capabilities/field.rich-text.md) is `Textarea` + `AllowFormatting` — which is
#     indistinguishable from a plain Textarea, a type that DOES fire onChange. Refusing on that
#     guess would block a real capability, so this list stays silent about it rather than
#     inventing a rule for an uncaptured shape (CLAUDE.md THE RULE).
NO_EVENT_FIELD_TYPES: frozenset[str] = frozenset({
    "Attachment", "Image", "Signature", "SequenceNumber", "Geolocation",
})


def trigger_for(t: FieldType) -> EventTrigger:
    """The event trigger a SOURCE field of type `t` actually fires (issue #12: defaulting every
    event to `onChange` gave Select/Date/Number sources a trigger that never fires, with no error
    anywhere). Attachment takes no events at all (CLAUDE.md Field events) — refused loudly here,
    never downgraded."""
    match t:
        case FieldType.TEXT | FieldType.TEXTAREA:
            return EventTrigger.ON_CHANGE
        case FieldType.DATE | FieldType.NUMBER | FieldType.USER:
            return EventTrigger.ON_SELECT
        case FieldType.SELECT | FieldType.BOOLEAN:
            return EventTrigger.ON_CLICK
        case FieldType.ATTACHMENT:
            raise ValueError(
                "Attachment fields take no events at all (CLAUDE.md Field events) — an event "
                "cannot be wired onto an Attachment source"
            )


class Visibility(StrEnum):
    """What one field column looks like at one workflow step.

    Wire-strings taken from the UI-built oracle (a captured draft snapshot, 132 Kissflow-generated
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
    # The LIST FLOW whose items are this field's options. REQUIRED when `type` is SELECT and
    # meaningless on every other type: a Select with no list is a dropdown bound to nothing,
    # which PUTs 200 and then dies on publish with a bare 500 MetadataError (CLAUDE.md Write
    # path, ReferredList #13). `graph.apply_changes` refuses to mint one.
    referred_list: str | None = None
    field_id: str | None = None
    # Per-type keys the builder writes ONLY on some fields of that type (Textarea
    # `AllowFormatting`, Attachment `CaptureOnly`). NOT universal defaults — a plain Textarea
    # omits `AllowFormatting` and renders fine — so opt-in per field. Written verbatim onto the
    # Field node; values pass through as-is (`False`, "true", …).
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
    """Preview of a change set. adds/edits are the requested specs; human_readable is for confirm."""
    adds: tuple[FieldSpec, ...]
    edits: tuple[FieldSpec, ...]
    skipped: tuple[str, ...]  # names already present (idempotent reconcile)
    human_readable: str
