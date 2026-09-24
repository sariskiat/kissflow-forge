"""app.application.use_cases.app._sweep — pure/private helpers for `forge_sweep`.

Ported from `app.infrastructure.kissflow.client.run_sweep` (Stage D group 6, app
family). `run_sweep`'s old per-scope `Err` buckets become a per-call try/except
here: a `FlowRepository`/`AppRepository`/`PageRepository` method now RAISES
`ApplicationError` instead of returning one, so `read_bucket` is what keeps a
single failing sub-scope from taking the whole sweep down -- CLAUDE.md's own
"every batch operation ends with an output-invariant audit": one scope's read
failure lands in its OWN `error` bucket, never aborts the others and never
propagates out of `ForgeSweep.execute()` (`forge_sweep` is a verdict tool, rule 7
of `brief_stage_d_common.md`: it reports its verdict IN the response).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.exceptions import ApplicationError
from app.domain.value_objects.kinds import AnyFlowKind

#: The five real sweep sub-scopes, in the fixed order `forge_sweep(scope="all")`
#: fans out to. Not itself a `SweepScope` member -- `"all"` is the alias that
#: expands to this tuple.
SWEEP_SCOPES: tuple[str, ...] = ("apps", "flows", "pages", "roles", "lists")

#: Every flow kind `run_sweep`'s own "flows" bucket lists, one sub-bucket each.
SWEEP_FLOW_KINDS: tuple[AnyFlowKind, ...] = (
    "process",
    "form",
    "case",
    "list",
    "dataset",
)


async def read_bucket(call: Callable[[], Awaitable[list[Any]]]) -> dict[str, Any]:
    """Run one sweep sub-scope's read, landing it in exactly one bucket.

    Args:
        call: A zero-argument async callable making the one port read this
            bucket reports on.

    Returns:
        `{"status": "read", "count", "items", "error": None}` on success, or
        `{"status": "error", "count": 0, "items": [], "error": <message>}`
        when `call` raises -- never propagated, so one failing sub-scope can
        never take the rest of the sweep down with it.
    """
    try:
        got = await call()
    except ApplicationError as exc:
        return {"status": "error", "count": 0, "items": [], "error": exc.message}
    return {"status": "read", "count": len(got), "items": got, "error": None}
