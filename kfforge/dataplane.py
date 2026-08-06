"""The item data plane: the documented (non-builder) `/process` API — create an item, fill it with
a verified read-back, submit/reject it, and walk it end to end. CLAUDE.md > Item data plane is the
authoritative capture of every route and trap here; this module is the executable form of it.

THE TRAP this whole module exists to defend against: an HTTP 200 is not verification. Kissflow's
admin PUT accepts a Select value that isn't a real option, returns 200, and silently never stores
it — a read-back is the only way to know. `fill_and_verify` exists for exactly this reason.

THE OTHER TRAP: a "my items"-style listing's activity-instance id is the initiator's already-
CONSUMED instance. Submitting or rejecting against it fails ("...anymore"). The only LIVE
activity-instance id lives inside `detail._current_context[0]._context_activity_instance_id` —
`live_aiid` is that lookup, isolated as a pure function so both traps are exhaustively testable
without a network.

Everything that talks to Kissflow goes through the `DataPlaneClient` seam below. `LiveDataPlane` is
the real implementation — it delegates to `KfClient`'s existing HTTP transport (`_json`/`_req`)
rather than duplicating it, and deliberately does so by composition, not by editing client.py: this
file is one node of a parallel build, and client.py is shared ground other nodes may be touching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .client import Err, KfClient, KfConfig

Item = dict[str, Any]  # a /process create, detail, submit, or reject response body


class DataPlaneClient(Protocol):
    """The seam: every dataplane function below takes one of these instead of a KfClient directly,
    so tests can supply an in-memory fake with no network at all. Route shapes (which are admin,
    which carry a body) are CLAUDE.md > Item data plane, not this Protocol's concern — a caller only
    needs to know the five actions, not their URLs.
    """

    def create_item(self, flow_id: str) -> Item | Err: ...
    def put_fields(self, flow_id: str, iid: str, payload: dict[str, Any]) -> Item | Err: ...
    def get_detail(self, flow_id: str, iid: str) -> Item | Err: ...  # admin route
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
    style error. The only correct source is `detail._current_context[0]._context_activity_instance_id`.
    A detail with no (or empty) `_current_context` is refused rather than falling back to anything
    else — there IS no safe fallback, only the myitems decoy, which is the trap itself.
    """
    ctx = detail.get("_current_context")
    if not ctx or not isinstance(ctx, list):
        return Err("verify",
                   "detail has no _current_context — this is the myitems consumed-instance trap "
                   "(CLAUDE.md > Item data plane): fetch ADMIN detail and read "
                   "_current_context[0]._context_activity_instance_id, never a myitems-style aiid")
    first = ctx[0]
    if not isinstance(first, dict) or not isinstance(first.get("_context_activity_instance_id"), str) \
            or not first["_context_activity_instance_id"]:
        return Err("verify",
                   "detail._current_context[0] has no _context_activity_instance_id — cannot "
                   "submit or reject without the live aiid")
    return first["_context_activity_instance_id"]


@dataclass(frozen=True)
class FillReport:
    """Every key of a fill request lands in exactly one bucket after a read-back. This exists
    because a 200 from `put_fields` proves nothing (CLAUDE.md > Item data plane): a Select value
    that isn't a real option PUTs 200 and is silently never stored.
    """
    landed: tuple[str, ...]
    discarded: tuple[str, ...]   # PUT 200'd; read-back shows the value gone (the Select trap)
    mismatched: tuple[str, ...]  # PUT 200'd; read-back shows a value different from what was sent

    def ok(self) -> bool:
        return not self.discarded and not self.mismatched


def fill_and_verify(
    cli: DataPlaneClient, *, flow_id: str, iid: str, values: dict[str, object],
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
    return FillReport(landed=tuple(landed), discarded=tuple(discarded), mismatched=tuple(mismatched))


@dataclass(frozen=True)
class StepResult:
    """What one successful `advance` did: the step the item left (from detail, read just before
    submitting), the LIVE aiid it moved with, and the raw submit response."""
    step: str
    aiid: str
    response: Item


def _detail_and_live_aiid(
    cli: DataPlaneClient, *, flow_id: str, iid: str,
) -> tuple[Item, str] | Err:
    """detail -> live_aiid, bundled: `advance` and a reject both need this exact pair, fetched
    fresh every time — the aiid trap means there is no other correct way to get one."""
    detail = cli.get_detail(flow_id, iid)
    if isinstance(detail, Err):
        return detail
    aiid = live_aiid(detail)
    if isinstance(aiid, Err):
        return aiid
    return detail, aiid


def advance(cli: DataPlaneClient, *, flow_id: str, iid: str) -> StepResult | Err:
    """Fetch detail -> derive the LIVE aiid (never a myitems-style one) -> submit."""
    fetched = _detail_and_live_aiid(cli, flow_id=flow_id, iid=iid)
    if isinstance(fetched, Err):
        return fetched
    detail, aiid = fetched
    resp = cli.submit(flow_id, iid, aiid)
    if isinstance(resp, Err):
        return resp
    step = detail.get("_current_step")
    return StepResult(step=step if isinstance(step, str) else "?", aiid=aiid, response=resp)


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
    iid: str | None            # None only when create_item itself failed
    created: bool
    planned: tuple[str, ...]   # every step name in the plan — lets a reader reconcile the buckets
    filled: tuple[str, ...]
    advanced: tuple[str, ...]
    rejected: tuple[str, ...]
    failed: tuple[str, ...]    # empty, or exactly the one step name the walk stopped at
    error: str | None

    def ok(self) -> bool:
        return self.created and not self.failed


def walk(cli: DataPlaneClient, *, flow_id: str, steps: list[StepPlan]) -> WalkReport:
    """create, then per step: fill_and_verify -> advance (or reject when the plan says so).
    Stops at the FIRST failure — including a fill that PUT 200 but didn't verify, which is exactly
    the silent-discard case this module exists to catch (fail loud, never continue past it).
    """
    planned = tuple(p.name for p in steps)
    created = cli.create_item(flow_id)
    if isinstance(created, Err):
        return WalkReport(flow_id=flow_id, iid=None, created=False, planned=planned, filled=(), advanced=(),
                          rejected=(), failed=(), error=f"create: {created.message}")
    iid = created.get("_id")
    if not isinstance(iid, str):
        return WalkReport(flow_id=flow_id, iid=None, created=False, planned=planned, filled=(), advanced=(),
                          rejected=(), failed=(), error=f"create: no _id in response {created!r}")

    filled: tuple[str, ...] = ()
    advanced: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()

    for plan in steps:
        report = fill_and_verify(cli, flow_id=flow_id, iid=iid, values=plan.values)
        if isinstance(report, Err):
            return WalkReport(flow_id=flow_id, iid=iid, created=True, planned=planned, filled=filled,
                              advanced=advanced, rejected=rejected, failed=(plan.name,),
                              error=f"{plan.name}: fill failed: {report.message}")
        if not report.ok():
            return WalkReport(flow_id=flow_id, iid=iid, created=True, planned=planned, filled=filled,
                              advanced=advanced, rejected=rejected, failed=(plan.name,),
                              error=f"{plan.name}: fill not verified — discarded={report.discarded} "
                                    f"mismatched={report.mismatched}")
        filled += (plan.name,)

        if plan.reject:
            fetched = _detail_and_live_aiid(cli, flow_id=flow_id, iid=iid)
            if isinstance(fetched, Err):
                return WalkReport(flow_id=flow_id, iid=iid, created=True, planned=planned, filled=filled,
                                  advanced=advanced, rejected=rejected, failed=(plan.name,),
                                  error=f"{plan.name}: {fetched.message}")
            _detail, aiid = fetched
            resp = cli.reject(flow_id, iid, aiid, plan.comment)
            if isinstance(resp, Err):
                return WalkReport(flow_id=flow_id, iid=iid, created=True, planned=planned, filled=filled,
                                  advanced=advanced, rejected=rejected, failed=(plan.name,),
                                  error=f"{plan.name}: reject failed: {resp.message}")
            rejected += (plan.name,)
            continue

        result = advance(cli, flow_id=flow_id, iid=iid)
        if isinstance(result, Err):
            return WalkReport(flow_id=flow_id, iid=iid, created=True, planned=planned, filled=filled,
                              advanced=advanced, rejected=rejected, failed=(plan.name,),
                              error=f"{plan.name}: advance failed: {result.message}")
        advanced += (plan.name,)

    return WalkReport(flow_id=flow_id, iid=iid, created=True, planned=planned, filled=filled, advanced=advanced,
                      rejected=rejected, failed=(), error=None)
