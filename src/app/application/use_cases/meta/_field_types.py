"""app.application.use_cases.meta._field_types — the field-type catalog THIS ENGINE
can build.

Copied from `app.application.tools.list_field_types` (kept there, unmodified, for the
old `server.py` tool until Stage E deletes it) rather than imported: new code never
imports the old `application/tools.py` module.
"""

from __future__ import annotations

from app.domain.value_objects.field_type import FieldType


def list_field_types() -> list[str]:
    """The field types THIS ENGINE can build -- the guard against 'wrong type' errors.

    Not the platform's catalog: Kissflow's own field palette is much wider (Image, Rich
    text, Signature, Geolocation, Currency, … — see docs/capabilities/, served over MCP
    by forge_capabilities). These are the ones whose wire shape is captured, so they are
    the ones a write here may name; anything else is refused at compile rather than
    guessed (ADR-0004).

    Returns:
        Every `FieldType` member's wire value, in enum declaration order.
    """
    return [t.value for t in FieldType]
