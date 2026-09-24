"""app.application.use_cases.item._write_fail — the item family's own
`raise_if_write_failed` (`brief_stage_d_common.md` rule 7, and lesson 14: one
copy of this helper per family).

A copy of `app.application.use_cases.flow._fields.raise_if_write_failed`
(lesson 11 forbids importing another family's private helper except
`use_cases/flow/_write_order.py`): same signature, same message shape. The
item family's own write (`ForgeSimulateCase`'s walk) has no publish step to
skip, but it DOES leave real, addressable state behind on a partial
failure -- an item that was created, steps that already filled and
advanced -- so every caller of this helper folds that landed state into
`collateral`, not just intended side effects: a caller who reads the
failure must still be able to find the item it already created (THE RULE,
CLAUDE.md), never just a bare error string.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.application.exceptions import VERIFY_FAILED, ApplicationError


def raise_if_write_failed(
    *,
    published: bool | str,
    remediation: Sequence[str] = (),
    collateral: Sequence[str] = (),
    **buckets: Sequence[Any],
) -> None:
    """Raise when a write did not fully land: a caller must never read a
    failed write as a success.

    Every write use case in the item family calls this once, after it has
    computed its own output-invariant buckets, and before it builds its
    response.

    Args:
        published: Whether this write went on to publish. A short statement
            (for example "n/a (item data-plane write, no publish step)")
            for a kind that has no publish step at all.
        remediation: Tool names the caller can run next, when any. Folded
            into the message so it is not lost now that the response never
            returns on this path.
        collateral: Human-readable lines describing state the write already
            created (an item id, the steps already filled or advanced),
            when any. Never itself a reason to raise -- but folded into the
            message so it is not lost on the one path where this call never
            reaches its own response DTO.
        **buckets: Each output-invariant bucket that means failure when
            non-empty (for example `failed=(...)`), keyed by its own
            response field name.

    Raises:
        ApplicationError: At least one bucket in `buckets` is non-empty,
            `code=VERIFY_FAILED`. The message names every non-empty bucket
            with its items, whether anything published, `collateral` and
            `remediation` when given.
    """
    failing = {name: list(items) for name, items in buckets.items() if items}
    if not failing:
        return
    named = "; ".join(f"{name}={items}" for name, items in failing.items())
    coll = f"; collateral={list(collateral)}" if collateral else ""
    tail = f"; remediation={list(remediation)}" if remediation else ""
    raise ApplicationError(
        f"write did not fully land ({named}){coll}; published={published}{tail}",
        code=VERIFY_FAILED,
    )
