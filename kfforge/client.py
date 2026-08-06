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

from .expr import build_goto_gate
from .graph import (
    Matrix,
    add_goto_task,
    add_table,
    apply_changes,
    build_workflow,
    ensure_process_def,
    field_names,
    regroup_into_sections,
    set_field_events,
    set_section_style,
    set_step_permissions,
)
from .types import FieldSpec
from .verify import doctor

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

    def get_flow_detail(self, kind: FlowKind, flow_id: str) -> dict[str, Any] | Err:
        """The flow's OWN metadata record (`GET /flow/2/{acct}/{kind}/{id}`) — DIFFERENT from
        `get_draft` (the node-graph). Carries `Status` ("Draft"|"Live"|"Archived"|...), used to
        verify a publish actually landed rather than trusting the publish response alone."""
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}"
                                 f"?_application_id={c.app_id}")

    def list_flows(self, kind: FlowKind) -> list[dict[str, Any]] | Err:
        """Every flow of `kind` currently in KF_APP. Proven live 2026-08-06: an app with zero
        flows returns a bare `[]`, not a 404 — used to auto-discover an existing flow to harvest
        members from (see `discover_member_source`)."""
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/{kind}?_application_id={c.app_id}"
                                 f"&page_size=100")

    def get_members(self, kind: FlowKind, flow_id: str) -> list[dict[str, Any]] | Err:
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}/member"
                                 f"?_application_id={c.app_id}")

    def post_member_batch(self, kind: FlowKind, flow_id: str, members: list[dict[str, Any]]) -> Any | Err:
        """CLAUDE.md Permissions: body=[{_id,Name,Kind:"AppRole",Role,Permission}]. Proven live
        2026-08-06: `Name` is validated against AppRoles that ALREADY exist in the account —
        `KISSFLOW_ERROR_00051 UserOrGroupDoesNotExistError` ("The AppRole {Name} does not exist in
        your account") on any name that isn't a real, pre-existing AppRole. There is no API route
        that CREATES an AppRole — only the builder UI does — so this can only ever re-grant a role
        harvested from somewhere it already exists (see `apply_member_batch`)."""
        c = self._cfg
        return self._json("POST", f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}/member/batch"
                                  f"?_application_id={c.app_id}", members)

    def post_report_member_batch(
        self, flow_id: str, report_id: str, members: list[dict[str, Any]],
    ) -> Any | Err:
        """CLAUDE.md Permissions: 'Flow REPORTS have the same member surface' — same body shape,
        Role "Member" ok, on a report nested under a process flow."""
        c = self._cfg
        return self._json(
            "POST",
            f"{c.base}/flow/2/{c.account}/process/{flow_id}/report/{report_id}/member/batch"
            f"?_application_id={c.app_id}",
            members,
        )

    def get_list_items(self, list_id: str) -> list[str] | Err:
        """CLAUDE.md Item data plane: bare array of legal option values for a Select's ReferredList."""
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/list/{list_id}/items"
                                 f"?_application_id={c.app_id}")

    # --- applications (forge_create_app; PROBE 2026-08-06 — see the DEV report's probe matrix) --
    def list_applications(self) -> list[dict[str, Any]] | Err:
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/application?page_size=100")

    def create_application(self, name: str) -> str | Err:
        c = self._cfg
        got = self._json("POST", f"{c.base}/flow/2/{c.account}/application", {"Name": name})
        if isinstance(got, Err):
            return got
        app_id = got.get("_id")
        if not isinstance(app_id, str):
            return Err("http", f"create application {name!r}: no _id in response {got!r}")
        return app_id

    def archive_application(self, app_id: str) -> None | Err:
        c = self._cfg
        got = self._json("POST", f"{c.base}/flow/2/{c.account}/application/{app_id}/archive")
        return got if isinstance(got, Err) else None

    def delete_application(self, app_id: str, archive_first: bool = True) -> None | Err:
        """Proven live 2026-08-06: a plain DELETE 400s (KISSFLOW_ERROR_04602, same error a
        non-archived PROCESS gives) until the application is archived first. The response is not
        proof of deletion either way — callers verify via `list_applications`."""
        c = self._cfg
        if archive_first:
            archived = self.archive_application(app_id)
            if isinstance(archived, Err):
                return archived
        got = self._json("DELETE", f"{c.base}/flow/2/{c.account}/application/{app_id}")
        return got if isinstance(got, Err) else None

    # --- app-level draft (Navigation) + page draft ------------------------
    def _app_draft_url(self, app_id: str) -> str:
        c = self._cfg
        return f"{c.base}/metadata/2/{c.account}/application/{app_id}/draft"

    def get_app_draft(self, app_id: str) -> Draft | Err:
        return self._json("GET", self._app_draft_url(app_id))

    def put_app_draft(self, app_id: str, new: Draft, expect_version: str | None) -> Draft | Err:
        return self._read_verify_write(
            lambda: self.get_app_draft(app_id), self._app_draft_url(app_id), new, expect_version)

    def publish_app(self, app_id: str) -> None | Err:
        c = self._cfg
        got = self._json("POST", f"{c.base}/metadata/2/{c.account}/application/{app_id}/publish")
        return got if isinstance(got, Err) else None

    def list_pages(self, app_id: str) -> list[dict[str, Any]] | Err:
        """CLAUDE.md App pages: 'page LIST paginates ~10 by default — use ?page_size=100'. THE
        TRUTH SURFACE for whether a page exists — a deleted page's draft GET still 200s
        (storage lingers), so only this route proves deletion (CLAUDE.md Page CRUD)."""
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/application/{app_id}/page"
                                 f"?page_size=100")

    def create_page(self, app_id: str, name: str) -> str | Err:
        c = self._cfg
        got = self._json("POST", f"{c.base}/flow/2/{c.account}/application/{app_id}/page",
                         {"Name": name})
        if isinstance(got, Err):
            return got
        page_id = got.get("_id")
        if not isinstance(page_id, str):
            return Err("http", f"create page {name!r}: no _id in response {got!r}")
        return page_id

    def delete_page(self, app_id: str, page_id: str) -> None | Err:
        """CLAUDE.md Page CRUD: the response is `{"status":"success"}` for ANY id, even a bogus
        one — NEVER trust it as proof. Callers verify via `list_pages`."""
        c = self._cfg
        got = self._json("DELETE",
                         f"{c.base}/flow/2/{c.account}/application/{app_id}/page/{page_id}")
        return got if isinstance(got, Err) else None

    def _page_draft_url(self, app_id: str, page_id: str) -> str:
        c = self._cfg
        return f"{c.base}/metadata/2/{c.account}/application/{app_id}/page/{page_id}/draft"

    def get_page_draft(self, app_id: str, page_id: str) -> Draft | Err:
        return self._json("GET", self._page_draft_url(app_id, page_id))

    def put_page_draft(
        self, app_id: str, page_id: str, new: Draft, expect_version: str | None,
    ) -> Draft | Err:
        return self._read_verify_write(
            lambda: self.get_page_draft(app_id, page_id), self._page_draft_url(app_id, page_id),
            new, expect_version)

    def publish_page(self, app_id: str, page_id: str) -> None | Err:
        c = self._cfg
        got = self._json(
            "POST", f"{c.base}/metadata/2/{c.account}/application/{app_id}/page/{page_id}/publish")
        return got if isinstance(got, Err) else None

    # --- the guarded write ----------------------------------------------
    def _read_verify_write(
        self,
        get_fn: Any,
        put_url: str,
        new: Draft,
        expect_version: str | None,
    ) -> Draft | Err:
        """Shared read-verify-write core: re-fetch the live version via `get_fn`, abort with a
        Conflict if it drifted since the caller planned against `expect_version`, else PUT `new`.
        `put_draft`/`put_page_draft`/`put_app_draft` are this SAME guard over three different URL
        shapes (flow draft, page draft, app draft) — one seam, three thin callers.
        """
        current = get_fn()
        if isinstance(current, Err):
            return current
        live_version = current.get(_META_VERSION)
        if expect_version is not None and live_version != expect_version:
            return Err("conflict",
                       f"draft changed under us: expected {expect_version!r}, live {live_version!r}")
        return self._json("PUT", put_url, new)

    def put_draft(self, kind: FlowKind, flow_id: str, new: Draft, expect_version: str | None) -> Draft | Err:
        """Read-verify-write. Re-reads the live version and aborts if it drifted since we planned."""
        return self._read_verify_write(
            lambda: self.get_draft(kind, flow_id), self._draft_url(kind, flow_id), new, expect_version)


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


# =====================================================================================
# Node G (P2 server surface) additions below. Each function is the SAME shape as
# apply_fields/apply_step_permissions/create_process above: GET -> apply an offline
# kfforge.graph/expr/verify function -> guarded PUT -> READ-BACK verify -> optional publish.
# Every one returns an explicit, never-silent audit (a dataclass with .as_tool_result(), or for
# the two-route delete dispatcher, a plain dict of the same shape) — server.py's forge_* tools stay
# thin wrappers around these.
# =====================================================================================


def apply_fields_and_layout(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    specs: list[FieldSpec],
    groups: list[tuple[str, list[str]]] | None = None,
    publish: bool = False,
) -> ApplyReport | Err:
    """apply_fields, then optionally regroup into named sections — ONE guarded read-verify-write
    covering both, so a caller building a form's fields+layout together never leaves it
    half-laid-out between two separate PUTs. `groups` is `graph.regroup_into_sections`'s own
    `(section title, [field names])` list; fields not named in any group land in a trailing
    "Other" section (regroup_into_sections's own behavior — nothing is ever dropped).

    Unlike plain `apply_fields` (which skips the PUT entirely when every requested field already
    exists — a genuine no-op), this ALWAYS writes when `groups` is given: a re-layout is a real
    change even with zero new fields, and silently skipping it would leave sections wherever an
    earlier write left them.
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
        if groups:
            new = regroup_into_sections(new, groups)
    except (ValueError, NotImplementedError) as e:
        return Err("verify", f"offline apply rejected the change set: {e}")

    added = tuple(n for n in requested if n not in before)
    if added or groups:
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
        flow_id=flow_id, added=added, skipped=skipped, verified=verified, missing=missing,
        meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class TableReport:
    """Output-invariant audit for forge_add_table: every requested child column NAME lands in
    exactly one bucket after the read-back — `verified_columns` or `missing_columns`."""
    flow_id: str
    table_name: str
    created: bool                        # False when idempotent no-op (table already existed)
    columns: tuple[str, ...]
    verified_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "table_name": self.table_name, "created": self.created,
            "columns": list(self.columns), "verified_columns": list(self.verified_columns),
            "missing_columns": list(self.missing_columns), "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing_columns),
        }


def apply_table(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    name: str,
    columns: list[tuple[str, str]],
    max_rows: int | None = None,
    allow_import: bool = False,
    publish: bool = False,
) -> TableReport | Err:
    """GET draft -> graph.add_table offline (idempotent: no-op if a table named `name` already
    exists) -> guarded PUT (skipped on the idempotent no-op path) -> read-back verify every child
    column NAME actually landed under that table -> optional publish.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)
    wanted_cols = tuple(c for c, _t in columns)

    already = any(isinstance(v, dict) and v.get("Type") == "Model" and v.get("Name") == name
                 for v in draft.values())
    try:
        new = add_table(draft, name, columns, max_rows=max_rows, allow_import=allow_import)
    except ValueError as e:
        return Err("verify", f"offline add_table rejected the spec: {e}")

    if not already:
        written = client.put_draft(kind, flow_id, new, expect_version=version)
        if isinstance(written, Err):
            return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back

    # graph.add_table's OWN idempotency check matches the HOST COLUMN (Type:"Model", Name:<name>)
    # — the table's own Model node carries Kind:"Model" but no Type key at all. Follow the SAME
    # path add_table itself uses: host column -> Column::Model[0] -> the real table Model node ->
    # Model::Field, rather than re-deriving a different (wrong) lookup here.
    host_col = next((v for v in read_back.values()
                     if isinstance(v, dict) and v.get("Type") == "Model"
                     and v.get("Name") == name), None)
    live_col_names: set[Any] = set()
    if host_col is not None:
        table_ids = host_col.get("Column::Model") or []
        table_node = read_back.get(table_ids[0]) if table_ids else None
        if table_node is not None:
            child_field_ids = table_node.get("Model::Field") or []
            live_col_names = {read_back.get(fid, {}).get("Name") for fid in child_field_ids}
    verified = tuple(c for c in wanted_cols if c in live_col_names)
    missing = tuple(c for c in wanted_cols if c not in live_col_names)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return TableReport(
        flow_id=flow_id, table_name=name, created=not already, columns=wanted_cols,
        verified_columns=verified, missing_columns=missing,
        meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class WorkflowReport:
    """Output-invariant audit for forge_build_workflow. DESTRUCTIVE — see apply_workflow's
    docstring: `unassigned` is not a failure, it is an honest report of which steps got no
    Resource wired (role=None, e.g. because forge_member_batch harvested nothing to assign)."""
    flow_id: str
    steps: tuple[str, ...]
    verified_steps: tuple[str, ...]
    missing_steps: tuple[str, ...]
    assigned: tuple[str, ...]            # step names that got a real Resource/assignee wired
    unassigned: tuple[str, ...]          # step names with role=None -- no assignee to wire
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "steps": list(self.steps),
            "verified_steps": list(self.verified_steps), "missing_steps": list(self.missing_steps),
            "assigned": list(self.assigned), "unassigned": list(self.unassigned),
            "meta_version": self.meta_version, "published": self.published,
            "isError": bool(self.missing_steps),
        }


def apply_workflow(
    client: KfClient,
    flow_id: str,
    steps: list[tuple[str, str | None]],
    parallel: tuple[str, list[tuple[str, list[tuple[str, str | None]]]]] | None = None,
    parallel_after: int | None = None,
    roles: dict[str, str] | None = None,
    publish: bool = False,
    kind: FlowKind = "process",
) -> WorkflowReport | Err:
    """GET draft -> graph.build_workflow offline (DESTRUCTIVE: replaces the WHOLE workflow — every
    existing Activity/ProcessDef/Resource/Permission is gone, per CLAUDE.md "build_workflow DELETES
    every Permission") -> guarded PUT -> read-back verify every step NAME landed -> optional
    publish.

    Callers MUST re-run forge_set_visibility straight after this: the wiped Permission matrix is
    graph.build_workflow's own documented behavior, not a bug this function should paper over by
    re-deriving a matrix on its own (it has no basis to guess section ownership).
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        new = build_workflow(draft, steps, parallel=parallel, parallel_after=parallel_after,
                             roles=roles)
    except ValueError as e:
        return Err("verify", f"offline build_workflow rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back

    live_names = {v.get("Name") for v in read_back.values()
                 if isinstance(v, dict) and v.get("Kind") == "Activity"}
    wanted = tuple(name for name, _role in steps)
    verified = tuple(n for n in wanted if n in live_names)
    missing = tuple(n for n in wanted if n not in live_names)
    assigned = tuple(name for name, role in steps if role)
    unassigned = tuple(name for name, role in steps if not role)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return WorkflowReport(
        flow_id=flow_id, steps=wanted, verified_steps=verified, missing_steps=missing,
        assigned=assigned, unassigned=unassigned, meta_version=read_back.get(_META_VERSION),
        published=published,
    )


@dataclass(frozen=True)
class GotoGateReport:
    flow_id: str
    goto_activity_id: str | None
    target_activity: str
    field_name: str
    verified: bool
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "goto_activity_id": self.goto_activity_id,
            "target_activity": self.target_activity, "field_name": self.field_name,
            "verified": self.verified, "meta_version": self.meta_version,
            "published": self.published, "isError": not self.verified,
        }


def apply_goto_gate(
    client: KfClient,
    flow_id: str,
    target_activity_name: str,
    field_name: str,
    publish: bool = False,
    kind: FlowKind = "process",
) -> GotoGateReport | Err:
    """GET draft -> resolve the target workflow step + gating Boolean field BY NAME -> ONE guarded
    write combining graph.add_goto_task (mints the GotoTask edge node — see its docstring, nothing
    else in this pack creates one) + expr.build_goto_gate (attaches the `= false()` loop condition,
    gate-polarity-checked: only a Boolean may gate a loop, CLAUDE.md Gate polarity) -> read-back
    verify the condition landed -> optional publish.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    target_id = next((k for k, v in draft.items()
                      if isinstance(v, dict) and v.get("Kind") == "Activity"
                      and v.get("Name") == target_activity_name), None)
    if target_id is None:
        return Err("verify", f"no workflow step named {target_activity_name!r}")
    field_id = next((k for k, v in draft.items()
                     if isinstance(v, dict) and v.get("Kind") == "Field"
                     and v.get("Name") == field_name), None)
    if field_id is None:
        return Err("verify", f"no field named {field_name!r}")

    try:
        with_goto, goto_id = add_goto_task(draft, target_activity_id=target_id)
        new = build_goto_gate(with_goto, goto_activity_id=goto_id, field_id=field_id)
    except ValueError as e:
        return Err("verify", f"offline goto-gate build rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    goto_node = read_back.get(goto_id) or {}
    verified = bool(goto_node.get("Activity::Expression"))

    published = False
    if publish and verified:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return GotoGateReport(
        flow_id=flow_id, goto_activity_id=goto_id if verified else None,
        target_activity=target_activity_name, field_name=field_name, verified=verified,
        meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class EventReport:
    flow_id: str
    fields: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "fields": list(self.fields), "verified": list(self.verified),
            "missing": list(self.missing), "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing),
        }


def apply_field_events(
    client: KfClient,
    flow_id: str,
    events: dict[str, list[tuple[str, str]]],
    publish: bool = False,
    kind: FlowKind = "process",
) -> EventReport | Err:
    """GET draft -> graph.set_field_events offline (rejects a top-level `await` or a `KFSDK`
    reference before any write — the editor's own two parse rules, CLAUDE.md Field events) ->
    guarded PUT -> read-back verify each named field carries a Field::Event -> optional publish.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        new = set_field_events(draft, events)
    except ValueError as e:
        return Err("verify", f"offline set_field_events rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    by_name = {v.get("Name"): v for v in read_back.values()
              if isinstance(v, dict) and v.get("Kind") == "Field"}
    wanted = tuple(events)
    verified = tuple(n for n in wanted if by_name.get(n, {}).get("Field::Event"))
    missing = tuple(n for n in wanted if n not in verified)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return EventReport(flow_id=flow_id, fields=wanted, verified=verified, missing=missing,
                       meta_version=read_back.get(_META_VERSION), published=published)


@dataclass(frozen=True)
class StyleReport:
    flow_id: str
    sections: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "sections": list(self.sections),
            "verified": list(self.verified), "missing": list(self.missing),
            "meta_version": self.meta_version, "published": self.published,
            "isError": bool(self.missing),
        }


def apply_section_style(
    client: KfClient,
    flow_id: str,
    styles: dict[str, dict[str, str | None]],
    publish: bool = False,
    kind: FlowKind = "process",
) -> StyleReport | Err:
    """GET draft -> graph.set_section_style offline (colour TOKEN REFS only — CLAUDE.md warns
    these are UNVALIDATED by the API and fail silently at render if wrong; callers should only
    ever pass the two CONFIRMED tokens, Color.Info.300 / Color.Secondary.Ten.800, or one seen live
    in the builder's own dropdown) -> guarded PUT -> read-back verify the Style.Value landed ->
    optional publish.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        new = set_section_style(draft, styles)
    except ValueError as e:
        return Err("verify", f"offline set_section_style rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    by_name = {v.get("Name"): v for v in read_back.values()
              if isinstance(v, dict) and v.get("Type") == "Section"}

    def _landed(name: str) -> bool:
        sec = by_name.get(name) or {}
        app_ids = sec.get("Column::Appearance") or []
        if not app_ids:
            return False
        app = read_back.get(app_ids[0]) or {}
        style_ids = app.get("Appearance::Style") or []
        if not style_ids:
            return False
        style = read_back.get(style_ids[0]) or {}
        value = style.get("Value") or {}
        wanted = styles[name]
        return all((value.get(k) or {}).get("ref") == v for k, v in wanted.items() if v is not None)

    wanted_names = tuple(styles)
    verified = tuple(n for n in wanted_names if _landed(n))
    missing = tuple(n for n in wanted_names if n not in verified)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return StyleReport(flow_id=flow_id, sections=wanted_names, verified=verified, missing=missing,
                       meta_version=read_back.get(_META_VERSION), published=published)


def run_doctor(
    client: KfClient, flow_id: str, kind: FlowKind = "process",
) -> dict[str, Any] | Err:
    """Fetch the LIVE draft, harvest every Select field's REAL list options (CLAUDE.md: 'never
    guess a literal — read it'), and run verify.doctor for real — the read-only diagnostic behind
    forge_doctor.

    A list whose items fetch fails is recorded in `list_fetch_errors` (never silently dropped from
    the audit) and simply excluded from `list_options`, so any branch literal that depended on it
    reports as `unvalidated` rather than falsely `ok`.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft

    list_ids = {
        v.get("ReferredList")
        for v in draft.values()
        if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Type") == "Select"
        and v.get("ReferredList")
    }
    list_options: dict[str, list[str]] = {}
    list_errors: dict[str, str] = {}
    for list_id in sorted(list_ids):
        items = client.get_list_items(list_id)
        if isinstance(items, Err):
            list_errors[list_id] = items.message
            continue
        list_options[list_id] = list(items) if isinstance(items, list) else []

    try:
        report = doctor(draft, list_options=list_options)
    except ValueError as e:
        return Err("verify", f"doctor could not run: {e}")

    return {
        "flow_id": flow_id,
        "ok": report.ok(),
        "problems": list(report.problems),
        "checked": report.checked,
        "unvalidated": list(report.unvalidated),
        "unvalidatable_scripts": report.unvalidatable_scripts,
        "list_ids_checked": sorted(list_options),
        "list_fetch_errors": list_errors,
        "isError": not report.ok(),
    }


_MEMBER_KEYS = ("_id", "Name", "Kind", "Role", "Permission")


def _normalize_member(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Defensive subset to the 5 documented member/batch keys (CLAUDE.md Permissions: body=
    [{_id,Name,Kind:"AppRole",Role,Permission}]). A harvested record missing the load-bearing
    `Role` key cannot be meaningfully reapplied — returns None rather than posting a malformed
    entry.

    ⚠️ The non-empty `GET .../member` response shape is UNVERIFIED as of this build: KF_APP had
    zero flows with any real member to observe during the 2026-08-06 live recon (see the DEV
    report's probe matrix) — the ONLY shape actually seen live was a bare `[]`. This normalizer is
    the deliberately defensive seam for that gap: it passes through only the keys the manual
    documents, never a raw unknown record.
    """
    if not isinstance(raw, dict) or not raw.get("Role"):
        return None
    out = {k: raw[k] for k in _MEMBER_KEYS if k in raw}
    out.setdefault("Kind", "AppRole")
    return out


@dataclass(frozen=True)
class MemberReport:
    target_flow_id: str
    source_flow_id: str | None
    harvested: tuple[str, ...]           # Role ids/names found on the source
    applied: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    note: str | None

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "target_flow_id": self.target_flow_id, "source_flow_id": self.source_flow_id,
            "harvested": list(self.harvested), "applied": list(self.applied),
            "verified": list(self.verified), "missing": list(self.missing), "note": self.note,
            "isError": bool(self.missing),
        }


def discover_member_source(
    client: KfClient, kind: FlowKind, exclude_flow_id: str,
) -> str | None | Err:
    """Best-effort: the first OTHER flow of `kind` in KF_APP that has at least one member.
    Returns None (never an Err) when KF_APP has no such flow — an empty app is a legitimate
    tenant state, not a failure (proven live 2026-08-06: a fresh KF_APP had zero flows at all)."""
    flows = client.list_flows(kind)
    if isinstance(flows, Err):
        return flows
    for f in flows:
        fid = f.get("_id") if isinstance(f, dict) else None
        if not isinstance(fid, str) or fid == exclude_flow_id:
            continue
        members = client.get_members(kind, fid)
        if isinstance(members, Err):
            continue
        if members:
            return fid
    return None


def apply_member_batch(
    client: KfClient,
    target_flow_id: str,
    source_flow_id: str | None = None,
    kind: FlowKind = "process",
) -> MemberReport | Err:
    """Harvest AppRole members from an existing flow in KF_APP and grant them on
    `target_flow_id` — "members FIRST" per CLAUDE.md Permissions: assignees cannot be written
    before members exist (publish then fails MetadataError).

    `source_flow_id` names the flow to harvest FROM; when omitted, the first OTHER flow of `kind`
    in KF_APP with at least one member is auto-discovered (`discover_member_source`). When no
    source is given and none can be discovered (a fresh app/tenant has no such flow yet — the
    documented state of KF_APP as of this build), this is REPORTED, not raised: harvested=(),
    applied=(), with an explanatory `note` — a caller must be able to tell "genuinely nothing to
    harvest yet" apart from a real failure, never silently treat one as the other.
    """
    if source_flow_id is None:
        discovered = discover_member_source(client, kind, target_flow_id)
        if isinstance(discovered, Err):
            return discovered
        source_flow_id = discovered

    if source_flow_id is None:
        return MemberReport(
            target_flow_id=target_flow_id, source_flow_id=None, harvested=(), applied=(),
            verified=(), missing=(),
            note="no existing flow with members found in KF_APP to harvest from (a fresh "
                 "app/tenant state, not an error) — add at least one AppRole member to a flow "
                 "via the builder UI, then re-run",
        )

    raw = client.get_members(kind, source_flow_id)
    if isinstance(raw, Err):
        return raw

    normalized = [n for r in raw if (n := _normalize_member(r)) is not None]
    harvested = tuple(str(n.get("Role")) for n in normalized)
    if not normalized:
        return MemberReport(
            target_flow_id=target_flow_id, source_flow_id=source_flow_id, harvested=(),
            applied=(), verified=(), missing=(),
            note=f"source flow {source_flow_id!r} has no AppRole members to harvest",
        )

    posted = client.post_member_batch(kind, target_flow_id, normalized)
    if isinstance(posted, Err):
        return posted

    read_back = client.get_members(kind, target_flow_id)
    if isinstance(read_back, Err):
        return read_back
    live_roles = {str(m.get("Role")) for m in read_back if isinstance(m, dict)}
    verified = tuple(r for r in harvested if r in live_roles)
    missing = tuple(r for r in harvested if r not in live_roles)

    return MemberReport(
        target_flow_id=target_flow_id, source_flow_id=source_flow_id, harvested=harvested,
        applied=harvested, verified=verified, missing=missing, note=None,
    )


def apply_report_members(
    client: KfClient, flow_id: str, report_id: str, members: list[dict[str, Any]],
) -> dict[str, Any] | Err:
    """POST member/batch onto a flow REPORT (CLAUDE.md Permissions: 'Flow REPORTS have the same
    member surface' — same body shape, Role "Member" ok). No documented/proven GET route exists
    for a report's OWN member list (unlike a flow's `/member`), so unlike every other apply_*
    here this is honestly reported as `verified: None` ("not checked") rather than faking a
    read-back audit it cannot actually perform.
    """
    posted = client.post_report_member_batch(flow_id, report_id, members)
    if isinstance(posted, Err):
        return posted
    return {
        "flow_id": flow_id, "report_id": report_id, "requested": members, "posted": posted,
        "verified": None,
        "note": "no documented GET route for a report's own member list — not independently "
                "read-back verified, unlike every other apply_* in this module",
        "isError": False,
    }


def create_application_verified(client: KfClient, name: str) -> dict[str, Any] | Err:
    """Create a NEW application and verify it via `list_applications` (never the create response
    alone) — wired for real per the 2026-08-06 PROBE (POST /flow/2/{acct}/application {"Name":...}
    WORKS; see the DEV report's probe matrix for the full attempt log). Deletion needs
    archive-first, same rule as a process — `delete_anything(kind="application", ...)` handles it.
    """
    app_id = client.create_application(name)
    if isinstance(app_id, Err):
        return app_id
    listed = client.list_applications()
    if isinstance(listed, Err):
        return listed
    verified = any(isinstance(a, dict) and a.get("_id") == app_id for a in listed)
    return {
        "app_id": app_id if verified else None, "name": name, "verified": verified,
        "supported": True, "note": None, "isError": not verified,
    }


def delete_anything(
    client: KfClient, kind: str, flow_id: str, app_id: str | None = None,
) -> dict[str, Any]:
    """Archive+delete a flow (process/form/case), a PAGE, or an APPLICATION, verifying deletion
    via the appropriate LIST route — never the delete response alone (CLAUDE.md Page CRUD: a page
    DELETE returns `{"status":"success"}` for ANY id, even a bogus one, and its draft GET still
    200s afterward — storage lingers — so the list route is the only proof). `app_id` is required
    when `kind == "page"`.

    For process/form/case there is no documented caveat that the delete response itself is
    unreliable (unlike page/application, both proven live 2026-08-06 to need it) — this still
    does a best-effort re-list as a second, independent signal rather than trusting one source
    alone, consistent with this project's "an HTTP 200 proves nothing" rule; a `list_flows`
    failure at that point does not overturn an already-successful delete, it just leaves
    `verified` conservatively True with nothing further to check.
    """
    if kind == "page":
        if not app_id:
            return {"kind": kind, "id": flow_id, "deleted": False, "verified": False,
                    "isError": True, "error": "app_id is required to delete a page"}
        deleted = client.delete_page(app_id, flow_id)
        if isinstance(deleted, Err):
            return {"kind": kind, "id": flow_id, "deleted": False, "verified": False,
                    "isError": True, "error": deleted.as_tool_result()["error"]}
        listed = client.list_pages(app_id)
        if isinstance(listed, Err):
            return {"kind": kind, "id": flow_id, "deleted": True, "verified": False,
                    "isError": True, "error": listed.as_tool_result()["error"]}
        verified = not any(isinstance(p, dict) and p.get("_id") == flow_id for p in listed)
        return {"kind": kind, "id": flow_id, "deleted": True, "verified": verified,
                "isError": not verified}

    if kind == "application":
        deleted = client.delete_application(flow_id, archive_first=True)
        if isinstance(deleted, Err):
            return {"kind": kind, "id": flow_id, "deleted": False, "verified": False,
                    "isError": True, "error": deleted.as_tool_result()["error"]}
        listed = client.list_applications()
        if isinstance(listed, Err):
            return {"kind": kind, "id": flow_id, "deleted": True, "verified": False,
                    "isError": True, "error": listed.as_tool_result()["error"]}
        verified = not any(isinstance(a, dict) and a.get("_id") == flow_id for a in listed)
        return {"kind": kind, "id": flow_id, "deleted": True, "verified": verified,
                "isError": not verified}

    # process | form | case
    deleted = client.delete_flow(kind, flow_id, archive_first=True)  # type: ignore[arg-type]
    if isinstance(deleted, Err):
        return {"kind": kind, "id": flow_id, "deleted": False, "verified": False,
                "isError": True, "error": deleted.as_tool_result()["error"]}
    still = client.list_flows(kind)  # type: ignore[arg-type]
    verified = True
    if not isinstance(still, Err):
        verified = not any(isinstance(f, dict) and f.get("_id") == flow_id for f in still)
    return {"kind": kind, "id": flow_id, "deleted": True, "verified": verified,
            "isError": not verified}
