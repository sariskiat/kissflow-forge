"""The item data plane: the documented (non-builder) `/process` API — create an item, fill it with
a verified read-back, submit/reject it, and walk it end to end. CLAUDE.md > Item data plane is the
authoritative capture of every route and trap here; this module is the executable form of it.

THE TRAP this whole module exists to defend against: an HTTP 200 is not verification. Kissflow's
admin PUT accepts a Select value that isn't a real option, returns 200, and silently never stores
it — a read-back is the only way to know. `fill_and_verify` exists for exactly this reason.

THE OTHER TRAP: a "my items"-style listing's activity-instance id is the initiator's already-
CONSUMED instance. Submitting or rejecting against it fails ("...anymore"). `live_aiid` is the
lookup that refuses that decoy, isolated as a pure function so the trap is exhaustively testable
without a network.

THE TWO-PHASE aiid RULE (proven live 2026-08-07, walking a real item Start -> ... -> Completed):
`detail._current_context[0]._context_activity_instance_id` is the correct source ONLY from the
SECOND submit onward. A Draft item still sitting at Start, never yet submitted, has no such
context at all — the only usable aiid for that FIRST submit is the one `create_item`'s own
response returns (a DIFFERENT field read at a DIFFERENT time from the myitems decoy above, not a
resurrection of it: this module never calls a myitems-style route at all). `usable_aiid` is
`live_aiid` plus that one documented first-hop fallback; `walk` threads the create response's aiid
through as that fallback for the first step only, never a later one.

Everything that talks to Kissflow goes through the `DataPlaneClient` seam below. `LiveDataPlane` is
the real implementation — it delegates to `KfClient`'s existing HTTP transport (`_json`/`_req`)
rather than duplicating it, and deliberately does so by composition, not by editing client.py: this
file is one node of a parallel build, and client.py is shared ground other nodes may be touching.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.infrastructure.kissflow.client import Err, KfClient, KfConfig

Item = dict[str, Any]  # a /process create, detail, submit, or reject response body


class ItemDetailReader(Protocol):
    """The one-action slice of the seam below: read an item's detail.

    The polling helpers (`_detail_and_live_aiid`, `wait_new_aiid`) call `get_detail` and nothing
    else, so this is what they ask for. Demanding the full five-action `DataPlaneClient` made
    them untestable with a fake that implements only what they use — which is exactly the fake a
    focused test should be allowed to write.
    """

    def get_detail(self, flow_id: str, iid: str) -> Item | Err: ...


class DataPlaneClient(ItemDetailReader, Protocol):
    """The seam: every dataplane function below takes one of these instead of a KfClient directly,
    so tests can supply an in-memory fake with no network at all. Route shapes (which are admin,
    which carry a body) are CLAUDE.md > Item data plane, not this Protocol's concern — a caller only
    needs to know the five actions, not their URLs.
    """

    def create_item(self, flow_id: str) -> Item | Err: ...
    def put_fields(self, flow_id: str, iid: str, payload: dict[str, Any]) -> Item | Err: ...
    def submit(self, flow_id: str, iid: str, aiid: str) -> Item | Err: ...
    def reject(self, flow_id: str, iid: str, aiid: str, comment: str) -> Item | Err: ...


class LiveDataPlane:
    """The real DataPlaneClient. Every method is one `KfClient._json` call — no transport logic of
    its own, no duplication of `client.py`. Routes are copied verbatim from CLAUDE.md > Item data
    plane; `test_dataplane.py::test_live_data_plane_builds_every_documented_route` pins them.
    """

    def __init__(self, client: KfClient) -> None:
        self._client = client
        self._cfg: KfConfig = client._cfg  # intentional: wrap, don't duplicate _json

    def _base(self) -> str:
        return f"{self._cfg.base}/process/2/{self._cfg.account}"

    def create_item(self, flow_id: str) -> Item | Err:
        return self._client._json("POST", f"{self._base()}/{flow_id}")

    def put_fields(self, flow_id: str, iid: str, payload: dict[str, Any]) -> Item | Err:
        url = f"{self._base()}/admin/{flow_id}/{iid}"
        return self._client._json("PUT", url, payload)

    def get_detail(self, flow_id: str, iid: str) -> Item | Err:
        """Admin route. The non-admin path 404s — never call it (CLAUDE.md > Item data plane)."""
        url = f"{self._base()}/admin/{flow_id}/{iid}"
        return self._client._json("GET", url)

    def submit(self, flow_id: str, iid: str, aiid: str) -> Item | Err:
        url = f"{self._base()}/{flow_id}/{iid}/{aiid}/submit"
        return self._client._json("POST", url)

    def reject(self, flow_id: str, iid: str, aiid: str, comment: str) -> Item | Err:
        url = f"{self._base()}/{flow_id}/{iid}/{aiid}/reject"
        return self._client._json("POST", url, {"Comment": comment})


def live_aiid(detail: Item) -> str | Err:
    """THE aiid trap, isolated as a pure function. `myitems`' `_activity_instance_id` is the
    initiator's CONSUMED instance — submitting or rejecting against it fails with an "...anymore"
    style error. The only source THIS function will ever read is
    `detail._current_context[0]._context_activity_instance_id`. A detail with no (or empty)
    `_current_context` is refused rather than falling back to anything else — `live_aiid` itself
    has no fallback, by design; it stays the strict, always-correct-from-hop-2-onward check.

    ⚠️ Hop 1 (a Draft item still sitting at Start, never yet submitted) genuinely has no
    `_current_context` at all — that is NOT this function malfunctioning, it is the documented
    two-phase aiid rule (module docstring): the first hop's aiid comes from `create_item`'s own
    response instead. `live_aiid` correctly refuses in that case; a caller that needs to submit the
    very first hop wants `usable_aiid`, not this function directly.
    """
    ctx = detail.get("_current_context")
    if not ctx or not isinstance(ctx, list):
        return Err(
            "verify",
            "detail has no _current_context — this is either the myitems consumed-instance "
            "trap (CLAUDE.md > Item data plane), or a hop-1 Draft item that hasn't been "
            "submitted yet (see usable_aiid for that case): fetch ADMIN detail and read "
            "_current_context[0]._context_activity_instance_id, never a myitems-style aiid",
        )
    first = ctx[0]
    if (
        not isinstance(first, dict)
        or not isinstance(first.get("_context_activity_instance_id"), str)
        or not first["_context_activity_instance_id"]
    ):
        return Err(
            "verify",
            "detail._current_context[0] has no _context_activity_instance_id — cannot "
            "submit or reject without the live aiid",
        )
    return first["_context_activity_instance_id"]


def usable_aiid(detail: Item, create_aiid: str | None = None) -> str | Err:
    """`live_aiid` plus the documented two-phase first-hop fallback (module docstring). Tries the
    live context first, exactly like `live_aiid` — always preferred when present, on ANY hop.
    Falls back to `create_aiid` ONLY when the context is genuinely absent AND a caller supplied
    one; with `create_aiid=None` (the default) this is byte-for-byte `live_aiid`.

    The fallback must be supplied BY THE CALLER, never inferred from "context is missing" alone —
    that is what keeps hop 2+ strict: `walk` passes `create_aiid` only for the very first step, so
    a genuinely missing context on a LATER hop still refuses here exactly as `live_aiid` would,
    rather than silently reusing a stale create-time id. Never touches the myitems decoy — this
    function, like `live_aiid`, only ever reads `_current_context`; `create_aiid` is whatever the
    caller's own `create_item` response returned, a different value read at a different time.
    """
    got = live_aiid(detail)
    if not isinstance(got, Err):
        return got
    if create_aiid is not None:
        return create_aiid
    return got


@dataclass(frozen=True)
class FillReport:
    """Every key of a fill request lands in exactly one bucket after a read-back. This exists
    because a 200 from `put_fields` proves nothing (CLAUDE.md > Item data plane): a Select value
    that isn't a real option PUTs 200 and is silently never stored.
    """

    landed: tuple[str, ...]
    discarded: tuple[str, ...]  # PUT 200'd; read-back shows the value gone (the Select trap)
    mismatched: tuple[str, ...]  # PUT 200'd; read-back shows a value different from what was sent

    def ok(self) -> bool:
        return not self.discarded and not self.mismatched


def fill_and_verify(
    cli: DataPlaneClient,
    *,
    flow_id: str,
    iid: str,
    values: dict[str, object],
) -> FillReport | Err:
    """PUT `values`, then GET admin detail and compare EVERY key against what was sent. Never
    trusts the PUT response alone — see FillReport.

    A value read back as None where something non-None was sent counts as `discarded` (the Select
    trap); anything else that doesn't match counts as `mismatched`; an exact match is `landed`.
    Network failure at either call short-circuits as Err — a failed PUT is never followed by a
    read-back GET, and a failed GET never produces a partial report.
    """
    put = cli.put_fields(flow_id, iid, values)
    if isinstance(put, Err):
        return put
    detail = cli.get_detail(flow_id, iid)
    if isinstance(detail, Err):
        return detail

    landed: list[str] = []
    discarded: list[str] = []
    mismatched: list[str] = []
    for key, sent in values.items():
        got = detail.get(key)
        if got is None and sent is not None:
            discarded.append(key)
        elif got == sent:
            landed.append(key)
        else:
            mismatched.append(key)
    return FillReport(
        landed=tuple(landed), discarded=tuple(discarded), mismatched=tuple(mismatched)
    )


@dataclass(frozen=True)
class StepResult:
    """What one successful `advance` did: the step the item left (from detail, read just before
    submitting), the LIVE aiid it moved with, and the raw submit response."""

    step: str
    aiid: str
    response: Item


def _detail_and_live_aiid(
    cli: ItemDetailReader,
    *,
    flow_id: str,
    iid: str,
    create_aiid: str | None = None,
) -> tuple[Item, str] | Err:
    """detail -> usable_aiid, bundled: `advance` and a reject both need this exact pair, fetched
    fresh every time — the aiid trap means there is no other correct way to get one. `create_aiid`
    is the two-phase rule's optional first-hop fallback (module docstring); omitted (the default)
    this is exactly the old detail -> live_aiid pairing, unchanged for every hop past the first."""
    detail = cli.get_detail(flow_id, iid)
    if isinstance(detail, Err):
        return detail
    aiid = usable_aiid(detail, create_aiid)
    if isinstance(aiid, Err):
        return aiid
    return detail, aiid


def advance(
    cli: DataPlaneClient,
    *,
    flow_id: str,
    iid: str,
    create_aiid: str | None = None,
) -> StepResult | Err:
    """Fetch detail -> derive the USABLE aiid (never a myitems-style one; the live context on any
    hop, or — only when `create_aiid` is supplied and context is genuinely absent — the
    create-response aiid, the two-phase rule's documented first-hop source) -> submit."""
    fetched = _detail_and_live_aiid(cli, flow_id=flow_id, iid=iid, create_aiid=create_aiid)
    if isinstance(fetched, Err):
        return fetched
    detail, aiid = fetched
    resp = cli.submit(flow_id, iid, aiid)
    if isinstance(resp, Err):
        return resp
    step = detail.get("_current_step")
    return StepResult(step=step if isinstance(step, str) else "?", aiid=aiid, response=resp)


# A finished item has no _current_context at all -- live_aiid correctly Errs on it, same as the
# hop-1 Draft case, but for the OPPOSITE reason (nothing left to transition INTO, not nothing yet
# transitioned FROM). wait_new_aiid must tell these apart: only "Completed"/"Rejected" are ever
# confirmed live as terminal (CLAUDE.md Item data plane: reject "sets status Rejected"; the
# two-phase aiid walk table ends "status = Completed") -- no other value is treated as terminal,
# never guessed.
_TERMINAL_STATUSES = frozenset({"Completed", "Rejected"})


def wait_new_aiid(
    cli: ItemDetailReader,
    *,
    flow_id: str,
    iid: str,
    prev_aiid: str,
    tries: int = 8,
    delay: float = 0.9,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str | Err:
    """Bounded poll for the step transition after a submit/reject: keep re-deriving the LIVE aiid
    (via `live_aiid` — same trap-guard `advance`/`fill_and_verify` use) until it differs from
    `prev_aiid`, or the item reaches a TERMINAL status, or give up.

    THE GAP this closes: `walk` has no step-transition wait at all — it submits, then immediately
    moves on to the next step's fill. Kissflow's own activity-instance transition is not always
    visible in the very next read (the live reference implementation, `sim_case.py`, was written
    with a bounded retry precisely because a fresh submit does not always show a rolled-over
    `_current_context` on the FIRST read back). Calling `fill_and_verify` against a still-stale
    aiid's context risks filling the step the item just LEFT, or re-tripping the aiid trap.

    ⚠️ A SECOND gap, found live 2026-08-07 walking a real item to actual completion: a submit that
    finishes the whole workflow leaves the item with NO `_current_context` at all — there is no
    next step to roll over INTO. Before this fix, that read the same as "not rolled over yet" and
    the poll spun until `tries` ran out, reporting a false failure on a submit that had, in fact,
    fully succeeded. Every `get_detail` read here is now checked for a TERMINAL `_status`
    (`_TERMINAL_STATUSES`) BEFORE falling through to the aiid comparison; on a terminal status this
    returns immediately, with the status STRING itself, never an aiid — nothing left to submit
    against, so there is no aiid to return. Every caller in this module (`walk`, the only one) only
    ever checks the return for `isinstance(..., Err)`, never interprets the string payload, so this
    is safe — documented explicitly so a future caller does not assume the return is always a real
    activity-instance id.

    Bounded, never a silent infinite retry: `tries` hard-caps the attempts (mirrors the timing the
    proven reference implementation already uses live — `tries=8, delay=0.9` by default). Any
    OTHER failure along the way — a transport error from `get_detail`, or a not-yet-rolled-over
    `_current_context` on a still-InProgress item (exactly what `live_aiid` itself refuses to
    fabricate a fallback for) — is treated as "not ready yet" and retried; a bounded poll's whole
    point is absorbing that class of transient state. Exhausting `tries` without ever seeing a NEW
    aiid OR a terminal status returns the last failure (or a stuck-aiid message) as an `Err` — it
    never fabricates success, and never returns `prev_aiid` as if that were one.

    Callers integrate this as an OPTIONAL hook between `walk` steps (or drive it directly), rather
    than `walk` gaining an unconditional poll baked in — a caller with no latency in its own fake/
    test transport should not pay for retries it will never need.

    `sleep_fn` is injectable (default `time.sleep`) purely for testability: a test proves the
    retry/backoff loop runs exactly `tries` times, and that it sleeps BETWEEN attempts (never
    before the first, never after the last), with no real wall-clock delay.
    """
    last: Err = Err("verify", f"wait_new_aiid: tries={tries} must be >= 1")
    for attempt in range(tries):
        if attempt > 0:
            sleep_fn(delay)
        detail = cli.get_detail(flow_id, iid)
        if isinstance(detail, Err):
            last = detail
            continue
        status = detail.get("_status")
        if status in _TERMINAL_STATUSES:
            return status  # nothing left to transition into -- the wait is over, successfully
        aiid = live_aiid(detail)
        if isinstance(aiid, Err):
            last = aiid
            continue
        if aiid != prev_aiid:
            return aiid
        last = Err(
            "verify",
            f"wait_new_aiid: aiid still {aiid!r} after {attempt + 1}/{tries} tries "
            f"({(attempt + 1) * delay:.1f}s) — step transition did not happen in time",
        )
    return last


def _root_model_ids(draft: dict[str, Any]) -> set[str]:
    """Model node ids that are the FORM'S OWN root model, not a child table. A child-table Model
    carries a host `Column` back-reference (CLAUDE.md > Tables: `Model{..., Column:<host>}`); the
    root form Model does not. Property-based, so it holds on any app regardless of node ordering.
    """
    return {
        k
        for k, v in draft.items()
        if isinstance(v, dict) and v.get("Kind") == "Model" and not v.get("Column")
    }


def field_name_index(draft: dict[str, Any]) -> dict[str, str]:
    """name -> field id, for every root-model Field in a flow's draft graph.

    Scoped to root-model fields ON PURPOSE (documented limit): a child-table field can share a
    display name with a root field, and a top-level `/process` admin fill only ever addresses
    root-model fields — a table's rows go through a different `Table::<child model id>` key
    (CLAUDE.md > Item data plane). Resolving table-field names here would let a name collide.
    """
    roots = _root_model_ids(draft)
    out: dict[str, str] = {}
    for key, node in draft.items():
        if not isinstance(node, dict) or node.get("Kind") != "Field":
            continue
        if node.get("Model") not in roots:
            continue
        name = node.get("Name")
        if isinstance(name, str) and name:
            fid = node.get("Id")
            out[name] = fid if isinstance(fid, str) and fid else key
    return out


def resolve_value_keys(
    values: dict[str, object],
    field_index: dict[str, str],
    passthrough: frozenset[str] = frozenset(),
) -> dict[str, object] | Err:
    """Translate a fill dict's KEYS (field name OR field id) to field ids, leaving every VALUE
    untouched (a Select value stays the option literal — only the key is resolved). A key already
    shaped like a field id (`Field_...` prefix) or matching a known live field id is kept as-is;
    any other key is looked up as a field NAME. Mixed names and ids in one dict are fine.

    `passthrough` is a set of extra keys allowed through verbatim without being treated as field
    names — e.g. a dataform record's synthetic system `"Name"` key, which is a column id, not a
    display name (default empty preserves the process-fill behavior exactly).

    Fails LOUD on a name that matches no field — naming the unresolved key AND listing every
    available field name, so a caller with only the MCP tool surface (no code, no source) sees the
    real vocabulary instead of a bare `FieldNotFound` from the data plane. Never silently drops it.
    """
    known_ids = set(field_index.values())
    resolved: dict[str, object] = {}
    for key, val in values.items():
        if key in passthrough or key.startswith("Field_") or key in known_ids:
            resolved[key] = val
        elif key in field_index:
            resolved[field_index[key]] = val
        else:
            available = ", ".join(sorted(field_index)) or "(none)"
            return Err(
                "verify",
                f"fill key {key!r} matches no field on this flow — not a field id, and no "
                f"field is named {key!r}. Available field names: {available}",
            )
    return resolved


@dataclass(frozen=True)
class StepPlan:
    """One hop of a walk: fields to set (fill_and_verify'd before anything else), then either
    advance (submit) or, when `reject` is set, reject with `comment`. `name` is the caller's own
    label for this hop, used only for reporting — `walk` never asserts it against the server's own
    `_current_step` string (that would need polling/retry for step-transition latency, which is
    intentionally NOT ported here; see the DEV report for why).
    """

    name: str
    values: dict[str, object] = field(default_factory=dict)
    reject: bool = False
    comment: str = ""


@dataclass(frozen=True)
class WalkReport:
    """Output-invariant audit of one walk: every step in the plan lands in exactly one bucket —
    `advanced`, `rejected`, or (the one it stopped at) `failed`. `filled` is orthogonal: a step
    that advanced or rejected was necessarily filled first, so it appears in both.
    """

    flow_id: str
    iid: str | None  # None only when create_item itself failed
    created: bool
    planned: tuple[str, ...]  # every step name in the plan — lets a reader reconcile the buckets
    filled: tuple[str, ...]
    advanced: tuple[str, ...]
    rejected: tuple[str, ...]
    failed: tuple[str, ...]  # empty, or exactly the one step name the walk stopped at
    error: str | None

    def ok(self) -> bool:
        return self.created and not self.failed


def walk(
    cli: DataPlaneClient,
    *,
    flow_id: str,
    steps: list[StepPlan],
    field_index: dict[str, str] | None = None,
    poll_after_transition: bool = False,
    poll_tries: int = 8,
    poll_delay: float = 0.9,
    poll_sleep_fn: Callable[[float], None] = time.sleep,
) -> WalkReport:
    """create, then per step: fill_and_verify -> advance (or reject when the plan says so).
    Stops at the FIRST failure — including a fill that PUT 200 but didn't verify, which is exactly
    the silent-discard case this module exists to catch (fail loud, never continue past it).

    The TWO-PHASE aiid rule (module docstring) is threaded through here: the create response's own
    aiid is captured once, then offered as `usable_aiid`'s fallback ONLY for the FIRST step in
    `steps` — a Draft item fresh off `create_item` has no `_current_context` yet, so without this a
    walk starting from Draft could never even complete its first hop. Every step after the first
    gets no such fallback (`create_aiid=None`), so a genuinely missing context on a later hop still
    fails loud exactly as before this rule was added — the fallback never masks a real bug past hop
    1, and it never touches the myitems decoy either (this module has no myitems call at all).

    `field_index` (name -> field id, from `field_name_index` on the flow's draft): when supplied,
    each step's `values` KEYS are resolved from field NAMES to field ids before the fill PUT (a key
    already shaped like an id is kept as-is; values are never touched — see `resolve_value_keys`).
    A key that matches no field fails the CURRENT step loud, exactly like a fill that did not
    verify. Omitted (the default, `None`) skips resolution entirely — every offline test that
    already speaks in field ids keeps passing unchanged, and it is the caller's job (server.py) to
    fetch the draft and build the index for a live `forge_simulate_case` run.

    `poll_after_transition` (default False — a caller/fake with no such latency, e.g. every OTHER
    test in this file, pays nothing extra): when True, calls `wait_new_aiid` right after each
    successful advance/reject, closing the gap `walk` otherwise has NO wait for at all. This is
    the integration point Node G's dataplane review flagged: a single `forge_simulate_case` MCP
    call runs the ENTIRE walk in one shot, so the Robot/caller layer has no seam to inject a poll
    BETWEEN internal steps — the hook has to live in `walk` itself. A poll that never sees the
    aiid change (transition genuinely stuck, or too slow for `poll_tries`) fails the CURRENT step
    plan, exactly like any other stage of the loop — never silently proceeds on a stale aiid.
    """
    planned = tuple(p.name for p in steps)
    created = cli.create_item(flow_id)
    if isinstance(created, Err):
        return WalkReport(
            flow_id=flow_id,
            iid=None,
            created=False,
            planned=planned,
            filled=(),
            advanced=(),
            rejected=(),
            failed=(),
            error=f"create: {created.message}",
        )
    iid = created.get("_id")
    if not isinstance(iid, str):
        return WalkReport(
            flow_id=flow_id,
            iid=None,
            created=False,
            planned=planned,
            filled=(),
            advanced=(),
            rejected=(),
            failed=(),
            error=f"create: no _id in response {created!r}",
        )
    create_aiid = created.get("_activity_instance_id")
    if not isinstance(create_aiid, str) or not create_aiid:
        create_aiid = None  # no usable first-hop fallback in the create response; hop 1 then
        # behaves exactly like every later hop (context required, no fallback)

    filled: tuple[str, ...] = ()
    advanced: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()

    for i, plan in enumerate(steps):
        hop_create_aiid = create_aiid if i == 0 else None  # two-phase rule: first hop only
        values = plan.values
        if field_index is not None:
            resolved = resolve_value_keys(plan.values, field_index)
            if isinstance(resolved, Err):
                return WalkReport(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    failed=(plan.name,),
                    error=f"{plan.name}: {resolved.message}",
                )
            values = resolved
        report = fill_and_verify(cli, flow_id=flow_id, iid=iid, values=values)
        if isinstance(report, Err):
            return WalkReport(
                flow_id=flow_id,
                iid=iid,
                created=True,
                planned=planned,
                filled=filled,
                advanced=advanced,
                rejected=rejected,
                failed=(plan.name,),
                error=f"{plan.name}: fill failed: {report.message}",
            )
        if not report.ok():
            return WalkReport(
                flow_id=flow_id,
                iid=iid,
                created=True,
                planned=planned,
                filled=filled,
                advanced=advanced,
                rejected=rejected,
                failed=(plan.name,),
                error=f"{plan.name}: fill not verified — discarded={report.discarded} "
                f"mismatched={report.mismatched}",
            )
        filled += (plan.name,)

        if plan.reject:
            fetched = _detail_and_live_aiid(
                cli, flow_id=flow_id, iid=iid, create_aiid=hop_create_aiid
            )
            if isinstance(fetched, Err):
                return WalkReport(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    failed=(plan.name,),
                    error=f"{plan.name}: {fetched.message}",
                )
            _detail, aiid = fetched
            resp = cli.reject(flow_id, iid, aiid, plan.comment)
            if isinstance(resp, Err):
                return WalkReport(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    failed=(plan.name,),
                    error=f"{plan.name}: reject failed: {resp.message}",
                )
            rejected += (plan.name,)
            if poll_after_transition:
                waited = wait_new_aiid(
                    cli,
                    flow_id=flow_id,
                    iid=iid,
                    prev_aiid=aiid,
                    tries=poll_tries,
                    delay=poll_delay,
                    sleep_fn=poll_sleep_fn,
                )
                if isinstance(waited, Err):
                    return WalkReport(
                        flow_id=flow_id,
                        iid=iid,
                        created=True,
                        planned=planned,
                        filled=filled,
                        advanced=advanced,
                        rejected=rejected,
                        failed=(plan.name,),
                        error=f"{plan.name}: post-reject transition poll failed: {waited.message}",
                    )
            continue

        result = advance(cli, flow_id=flow_id, iid=iid, create_aiid=hop_create_aiid)
        if isinstance(result, Err):
            return WalkReport(
                flow_id=flow_id,
                iid=iid,
                created=True,
                planned=planned,
                filled=filled,
                advanced=advanced,
                rejected=rejected,
                failed=(plan.name,),
                error=f"{plan.name}: advance failed: {result.message}",
            )
        advanced += (plan.name,)
        if poll_after_transition:
            waited = wait_new_aiid(
                cli,
                flow_id=flow_id,
                iid=iid,
                prev_aiid=result.aiid,
                tries=poll_tries,
                delay=poll_delay,
                sleep_fn=poll_sleep_fn,
            )
            if isinstance(waited, Err):
                return WalkReport(
                    flow_id=flow_id,
                    iid=iid,
                    created=True,
                    planned=planned,
                    filled=filled,
                    advanced=advanced,
                    rejected=rejected,
                    failed=(plan.name,),
                    error=f"{plan.name}: post-advance transition poll failed: {waited.message}",
                )

    return WalkReport(
        flow_id=flow_id,
        iid=iid,
        created=True,
        planned=planned,
        filled=filled,
        advanced=advanced,
        rejected=rejected,
        failed=(),
        error=None,
    )
