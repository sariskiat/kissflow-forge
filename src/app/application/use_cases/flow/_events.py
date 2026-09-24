"""Trigger derivation for `ForgeSetEvents`.

Copied from `app.infrastructure.kissflow.client`'s `_EventPlan` and
`_resolve_event_triggers` (pre-refactor), adapted to read a
`FlowDraft.to_wire()` dict instead of the old client's raw draft dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.value_objects.field_type import (
    NO_EVENT_FIELD_TYPES,
    TRIGGER_LIVE_CONFIRMED,
    FieldType,
    trigger_for,
)

Draft = dict[str, Any]


@dataclass(frozen=True)
class EventPlan:
    """What `resolve_event_triggers` worked out, before a single byte is
    written.

    Attributes:
        events: Ready for `FlowDraft.set_field_events` -- no `None` trigger
            left.
        triggers: `"<field> (<Type>) -> <trigger>"` per event, what actually
            got written.
        derived: Field names whose trigger this call derived (the caller
            omitted it).
        unverified: Triggers whose `(type -> trigger)` pair is not
            live-confirmed.
    """

    events: dict[str, list[tuple[str, str]]]
    triggers: tuple[str, ...]
    derived: tuple[str, ...]
    unverified: tuple[str, ...]


def resolve_event_triggers(
    draft: Draft,
    events: dict[str, list[tuple[str | None, str]]],
) -> EventPlan:
    """Resolve every event's trigger against the source field's real type.

    CLAUDE.md Field events: the trigger is a function of the source field's
    type -- Select fires `onClick`, Date and Number fire `onSelect`,
    Text/Textarea fire `onChange`. A hand-picked wrong trigger writes fine,
    publishes fine, and simply never fires, so it is invisible to every
    later check. `trigger_for` is the one table.

    Three refusals, all raised before any write, all naming what they saw:
    the source field's type takes no event at all (`NO_EVENT_FIELD_TYPES`);
    the caller stated a trigger that disagrees with the derived one (both
    are named); the type is real but outside `trigger_for`'s table and the
    caller stated nothing, so there is nothing to derive from and nothing
    to guess with.

    A field name absent from the draft is deliberately not refused here:
    `FlowDraft.set_field_events` owns that message.

    Args:
        draft: The flow's wire-format draft, read fresh before any write.
        events: `{field name: [(trigger, script), ...]}`, `trigger` `None`
            or `""` meaning "derive it".

    Returns:
        The resolved plan.

    Raises:
        ValueError: A source field's type takes no event at all, a stated
            trigger disagrees with the derived one, or a type outside
            `trigger_for`'s table has nothing to derive a trigger from.
    """
    by_name = {
        v.get("Name"): v
        for v in draft.values()
        if isinstance(v, dict) and v.get("Kind") == "Field"
    }
    resolved: dict[str, list[tuple[str, str]]] = {}
    triggers: list[str] = []
    derived: list[str] = []
    unverified: list[str] = []

    for fname, specs in events.items():
        node = by_name.get(fname)
        if node is None:
            # not this function's refusal to make -- `set_field_events` says "no
            # field named X" better than anything derived from a type we could not
            # read. Pass through verbatim, unless there is nothing to pass through.
            if any(t in (None, "") for t, _s in specs):
                raise ValueError(
                    f"cannot derive a trigger for {fname!r}: no field of that name "
                    "is on this flow"
                )
            resolved[fname] = [(t, sc) for t, sc in specs if t]
            continue
        raw = node.get("Type")
        want: str | None = None
        if isinstance(raw, str):
            if raw in NO_EVENT_FIELD_TYPES:
                raise ValueError(
                    f"{fname!r} is a {raw} field: it can never carry an event — "
                    "the builder offers no Event tab for it, so no trigger string "
                    f"exists (CLAUDE.md Field events). This engine refuses "
                    f"{len(NO_EVENT_FIELD_TYPES)}: {sorted(NO_EVENT_FIELD_TYPES)}. "
                    "CLAUDE.md names a SIXTH event-less type on the platform, Rich "
                    "text, which is deliberately absent from that set: its wire "
                    "shape is uncaptured and its inferred shape is "
                    "Textarea+AllowFormatting, indistinguishable from a plain "
                    "Textarea, which legitimately fires onChange "
                    "(types.NO_EVENT_FIELD_TYPES)"
                )
            try:
                ftype = FieldType(raw)
            except ValueError:
                ftype = None  # a real type this engine has no mapping for
            if ftype is not None:
                want = trigger_for(ftype).value
                if ftype not in TRIGGER_LIVE_CONFIRMED:
                    unverified.append(
                        f"{fname} ({raw}) -> {want}: family-inferred from the "
                        "field type, NOT live-confirmed on a published flow "
                        "(CLAUDE.md Field events)"
                    )

        out: list[tuple[str, str]] = []
        for given, script in specs:
            given = given or None  # "" from a wire caller means "derive it"
            if want is None:
                if given is None:
                    raise ValueError(
                        f"{fname!r} is of type {raw!r}, which is not in "
                        "`types.trigger_for` — this engine has no captured "
                        "trigger for it and will not guess one; state the trigger "
                        "explicitly, or capture it off the builder first"
                    )
                unverified.append(
                    f"{fname} ({raw}) -> {given}: taken from the caller — {raw!r} "
                    "is outside `types.trigger_for`, so nothing here could "
                    "confirm or contradict it"
                )
                out.append((given, script))
                triggers.append(f"{fname} ({raw}) -> {given}")
                continue
            if given is None:
                derived.append(fname)
            elif given != want:
                raise ValueError(
                    f"{fname!r} is a {raw} field: it fires {want!r}, but the spec "
                    f"asks for {given!r} — a wrong trigger writes fine, publishes "
                    "fine, and simply never fires (CLAUDE.md Field events). Omit "
                    "it and it is derived for you"
                )
            out.append((want, script))
            triggers.append(f"{fname} ({raw}) -> {want}")
        resolved[fname] = out

    return EventPlan(
        resolved,
        tuple(triggers),
        tuple(dict.fromkeys(derived)),
        tuple(dict.fromkeys(unverified)),
    )
