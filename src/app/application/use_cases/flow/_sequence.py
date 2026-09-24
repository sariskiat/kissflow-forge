"""Pure read-back audit helpers for `ForgeAddSequenceNumber`.

Copied from `app.infrastructure.kissflow.client`'s `_is_sequence_field` and
`_verify_sequence_number` (pre-refactor), adapted to read a
`FlowDraft.to_wire()` dict instead of the old client's raw draft dict.
"""

from __future__ import annotations

from typing import Any

Draft = dict[str, Any]


def _is_sequence_field(v: Any, name: str) -> bool:
    """True when `v` is the SequenceNumber field named `name`.

    Args:
        v: A candidate node from the draft, or any other value.
        name: The field name to match.

    Returns:
        Whether `v` is a `Kind: "Field"`, `Type: "SequenceNumber"` node with
        that `Name`.
    """
    return (
        isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Type") == "SequenceNumber"
        and v.get("Name") == name
    )


def _verify_sequence_number(draft: Draft, name: str) -> bool:
    """Verify the SequenceNumber field named `name` landed with all 3
    Property nodes.

    Args:
        draft: The flow's wire-format draft (a read-back, for the audit).
        name: The field name to verify.

    Returns:
        Whether a matching field exists and carries exactly 3
        `Field::Property` entries.
    """
    for v in draft.values():
        if _is_sequence_field(v, name):
            props = v.get("Field::Property")
            return isinstance(props, list) and len(props) == 3
    return False
