"""Live Kissflow builder client — the write path (§2 sign-off obtained 2026-08-03, DEV ONLY).

⚠️ Talks to Kissflow's UNDOCUMENTED internal /flow + /metadata builder API. AUP §1.10 applies;
this module is authorized for the DEV tenant only and refuses anything else by construction:

  * `KfConfig.from_env` reads ONLY `KF_DEV_*` vars — prod creds are never even loaded.
  * a `raise` (not an assert — survives `python -O`) rejects any domain without "dev-".
  * `put_draft` is read-verify-write: it re-reads `_meta_version` immediately before writing and
    aborts with a Conflict if the draft moved under us (FINDINGS.md refuted If-Match/ETag).

Endpoints confirmed live in spikes/spike_live_form.py + the 2026-08-03 read sweep (FINDINGS.md).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from .graph import (
    Matrix,
    apply_changes,
    ensure_process_def,
    field_names,
    set_step_permissions,
)
from .types import FieldSpec

Draft = dict[str, Any]
FlowKind = Literal["form", "process", "case"]

TIMEOUT_S = 30
_META_VERSION = "_meta_version"


@dataclass(frozen=True)
class Err:
    """Explicit error return — no exceptions across the tool boundary (fail loud, but as data)."""
    kind: Literal["http", "conflict", "verify", "config"]
    message: str
    status: int | None = None

    def as_tool_result(self) -> dict[str, Any]:
        return {"isError": True, "error": f"{self.kind}: {self.message}", "status": self.status}


@dataclass(frozen=True)
class KfConfig:
    key_id: str
    key_secret: str
    account: str
    domain: str
    app_id: str

    @staticmethod
    def from_env() -> KfConfig | Err:
        try:
            domain = os.environ["KF_DEV_DOMAIN"]
            cfg = KfConfig(
                key_id=os.environ["KF_DEV_ACCESS_KEY_ID"],
                key_secret=os.environ["KF_DEV_ACCESS_KEY_SECRET"],
                account=os.environ["KF_DEV_ACCOUNT_ID"],
                domain=domain,
                app_id=os.environ.get("KF_APP", ""),
            )
        except KeyError as e:
            return Err("config", f"missing env var {e.args[0]}")
        if "dev-" not in domain:
            return Err("config", f"refusing non-dev domain {domain!r}")
        if not cfg.app_id:
            return Err("config", "KF_APP is required — no default app; set it explicitly")
        return cfg

    @property
    def base(self) -> str:
        return f"https://{self.domain}"

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Access-Key-Id": self.key_id,
            "X-Access-Key-Secret": self.key_secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }


@dataclass(frozen=True)
class ApplyReport:
    """What a live apply actually did — every field lands in exactly one bucket (output audit)."""
    flow_id: str
    added: tuple[str, ...]
    skipped: tuple[str, ...]      # already present -> idempotent no-op
    verified: tuple[str, ...]     # confirmed present by post-write read-back
    missing: tuple[str, ...]      # requested, written, but ABSENT on read-back -> loud failure
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "added": list(self.added),
            "skipped": list(self.skipped),
            "verified": list(self.verified),
            "missing": list(self.missing),
            "meta_version": self.meta_version,
            "published": self.published,
            "isError": bool(self.missing),
        }


class KfClient:
    """Thin verb wrapper over the builder API. One method per confirmed endpoint."""

    def __init__(self, cfg: KfConfig) -> None:
        self._cfg = cfg

    # --- transport -------------------------------------------------------
    def _req(self, method: str, url: str, data: Any | None = None) -> tuple[int, str]:
        body = json.dumps(data).encode() if data is not None else None
        r = urllib.request.Request(url, data=body, headers=self._cfg.headers, method=method)
        try:
            # scheme is a literal https from KfConfig.base, dev-guarded at construction
            with urllib.request.urlopen(r, timeout=TIMEOUT_S) as resp:  # nosec B310
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except urllib.error.URLError as e:  # never swallow: surface transport failure as a status
            return 0, f"transport error: {e.reason}"

    def _json(self, method: str, url: str, data: Any | None = None) -> Any | Err:
        status, body = self._req(method, url, data)
        if status != 200:
            return Err("http", f"{method} {url} -> {body[:300]}", status)
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return Err("http", f"{method} {url} -> non-JSON body {body[:200]!r}", status)

    # --- endpoints -------------------------------------------------------
    def _draft_url(self, kind: FlowKind, flow_id: str) -> str:
        c = self._cfg
        return f"{c.base}/metadata/2/{c.account}/{kind}/{flow_id}/draft?_application_id={c.app_id}"

    def get_draft(self, kind: FlowKind, flow_id: str) -> Draft | Err:
        return self._json("GET", self._draft_url(kind, flow_id))

    def create_flow(self, kind: FlowKind, name: str) -> str | Err:
        c = self._cfg
        got = self._json("POST", f"{c.base}/flow/2/{c.account}/{kind}?_application_id={c.app_id}",
                         {"Name": name})
        if isinstance(got, Err):
            return got
        flow_id = got.get("_id")
        if not isinstance(flow_id, str):
            return Err("http", f"create {kind} {name!r}: no _id in response {got!r}")
        return flow_id

    def archive_flow(self, kind: FlowKind, flow_id: str) -> None | Err:
        """A process MUST be archived before it can be deleted (400 KISSFLOW_ERROR_04602 otherwise)."""
        c = self._cfg
        got = self._json("POST", f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}/archive"
                                 f"?_application_id={c.app_id}")
        return got if isinstance(got, Err) else None

    def delete_flow(self, kind: FlowKind, flow_id: str, archive_first: bool = True) -> None | Err:
        c = self._cfg
        if archive_first and kind == "process":
            archived = self.archive_flow(kind, flow_id)
            if isinstance(archived, Err):
                return archived
        got = self._json("DELETE",
                         f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}?_application_id={c.app_id}")
        return got if isinstance(got, Err) else None

    def publish(self, kind: FlowKind, flow_id: str) -> None | Err:
        c = self._cfg
        got = self._json("POST", f"{c.base}/metadata/2/{c.account}/{kind}/{flow_id}/publish"
                                 f"?_application_id={c.app_id}")
        return got if isinstance(got, Err) else None

    # --- the guarded write ----------------------------------------------
    def put_draft(self, kind: FlowKind, flow_id: str, new: Draft, expect_version: str | None) -> Draft | Err:
        """Read-verify-write. Re-reads the live version and aborts if it drifted since we planned."""
        current = self.get_draft(kind, flow_id)
        if isinstance(current, Err):
            return current
        live_version = current.get(_META_VERSION)
        if expect_version is not None and live_version != expect_version:
            return Err("conflict",
                       f"draft changed under us: expected {expect_version!r}, live {live_version!r}")
        return self._json("PUT", self._draft_url(kind, flow_id), new)


def create_process(
    client: KfClient,
    name: str,
    steps: tuple[str, ...],
    specs: list[FieldSpec],
    publish: bool = False,
) -> ApplyReport | Err:
    """Create a PROCESS from zero: shell -> ProcessDef scaffold -> fields -> verify -> publish.

    The scaffold is mandatory, not decoration: a bare process draft is rejected with HTTP 500 until
    it has a ProcessDef (FINDINGS.md). On any failure after the shell exists, the half-built process
    is archived+deleted so a failed run leaves no junk behind in the tenant.
    """
    flow_id = client.create_flow("process", name)
    if isinstance(flow_id, Err):
        return flow_id

    def _abandon(err: Err) -> Err:
        client.delete_flow("process", flow_id)  # type: ignore[arg-type]
        return err

    draft = client.get_draft("process", flow_id)
    if isinstance(draft, Err):
        return _abandon(draft)

    try:
        scaffolded = ensure_process_def(draft, steps)
    except ValueError as e:
        return _abandon(Err("verify", str(e)))

    written = client.put_draft("process", flow_id, scaffolded, expect_version=draft.get(_META_VERSION))
    if isinstance(written, Err):
        return _abandon(written)

    report = apply_fields(client, "process", flow_id, specs, publish=publish)
    return _abandon(report) if isinstance(report, Err) else report


def _permission_pairs(draft: Draft) -> dict[tuple[str, str], str]:
    """(column id, activity id) -> visibility, for every Permission node in a graph."""
    return {
        (n["Column"], n["Activity"]): n.get("Permission", "")
        for n in draft.values()
        if isinstance(n, dict) and n.get("Kind") == "Permission"
    }


def apply_step_permissions(
    client: KfClient,
    flow_id: str,
    matrix: Matrix,
    publish: bool = False,
    kind: FlowKind = "process",
) -> ApplyReport | Err:
    """Rebuild a process's per-step visibility matrix live. GET -> apply offline -> guarded PUT
    -> read-back audit -> optional publish.

    The audit unit is one (column, activity) PAIR, not a field: every pair we intended to write is
    reported as verified or `missing`, so a partially-applied matrix can never read as success.
    `skipped` counts pairs that already carried the exact visibility we wanted (idempotent re-run).
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft

    before = _permission_pairs(draft)
    version = draft.get(_META_VERSION)

    try:
        new = set_step_permissions(draft, matrix)
    except ValueError as e:
        return Err("verify", f"offline apply rejected the matrix: {e}")

    wanted = _permission_pairs(new)
    skipped = tuple(sorted(f"{c}@{a}" for (c, a), v in wanted.items() if before.get((c, a)) == v))
    added = tuple(sorted(f"{c}@{a}" for (c, a), v in wanted.items() if before.get((c, a)) != v))

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    live = _permission_pairs(read_back)
    verified = tuple(sorted(f"{c}@{a}" for (c, a), v in wanted.items() if live.get((c, a)) == v))
    missing = tuple(sorted(f"{c}@{a}" for (c, a), v in wanted.items() if live.get((c, a)) != v))

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return ApplyReport(
        flow_id=flow_id,
        added=added,
        skipped=skipped,
        verified=verified,
        missing=missing,
        meta_version=read_back.get(_META_VERSION),
        published=published,
    )


def apply_fields(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    specs: list[FieldSpec],
    publish: bool = False,
) -> ApplyReport | Err:
    """GET draft -> apply offline -> guarded PUT -> READ-BACK verify -> optional publish.

    Idempotent: names already on the flow are skipped, never duplicated. The read-back is the
    output invariant audit — a requested field that is not present afterwards is reported as
    `missing`, never silently dropped.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft

    before = field_names(draft)
    version = draft.get(_META_VERSION)
    requested = [s.name for s in specs]
    skipped = tuple(n for n in requested if n in before)

    try:
        new = apply_changes(draft, specs)
    except (ValueError, NotImplementedError) as e:
        return Err("verify", f"offline apply rejected the change set: {e}")

    added = tuple(n for n in requested if n not in before)
    if added:
        written = client.put_draft(kind, flow_id, new, expect_version=version)
        if isinstance(written, Err):
            return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    live_names = field_names(read_back)
    verified = tuple(n for n in requested if n in live_names)
    missing = tuple(n for n in requested if n not in live_names)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return ApplyReport(
        flow_id=flow_id,
        added=added,
        skipped=skipped,
        verified=verified,
        missing=missing,
        meta_version=read_back.get(_META_VERSION),
        published=published,
    )
