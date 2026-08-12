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
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from .expr import build_branch_condition, build_goto_gate, remove_condition
from .graph import (
    Matrix,
    _style_wire_value,
    add_field_validation,
    add_goto_task,
    add_sequence_number,
    add_table,
    apply_changes,
    apply_exact_layout,
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

    def list_app_roles(self, app_id: str | None = None) -> list[dict[str, Any]] | Err:
        """Every AppRole in the ACCOUNT (paginated `page_number`/`page_size=100`), optionally
        filtered to the ones scoped to `app_id`. Proven live 2026-08-07: this account-level route
        genuinely lists AppRoles — 356 of them in the probe tenant, 2 scoped to one app under test
        — CORRECTING the older CLAUDE.md belief that "no route lists app roles from scratch" (that
        belief was about a DIFFERENT suffix, `/app_role/.../external/list`, which really does
        return `[]`; this is not that route).

        Each record's `Applications` key is a list of `{"_id": ..., "Type": "Application"}` dicts,
        NOT bare id strings — filtering with a plain `app_id in record["Applications"]` silently
        matches nothing (found live while writing this method); the filter below checks each
        dict's own `_id`.
        """
        c = self._cfg
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            got = self._json("GET", f"{c.base}/app_role/2/{c.account}/list"
                                     f"?page_number={page}&page_size=100")
            if isinstance(got, Err):
                return got
            items = got if isinstance(got, list) else []
            if not items:
                break
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
        if app_id is None:
            return out
        return [r for r in out if isinstance(r, dict) and any(
            isinstance(a, dict) and a.get("_id") == app_id for a in (r.get("Applications") or []))]

    def get_app_role(self, role_id: str) -> dict[str, Any] | Err:
        """One AppRole's own detail, including its `Members` list — which `list_app_roles` never
        carries (verified across every record on that route, not sampled), making this the only
        source for the harvest-worthy `Members` signal. `GroupCount` is nullable here.

        Do NOT assume the list route's key-set: most of its records are
        `['Applications', 'Description', 'Name', 'Preference', 'UserCount', '_application_id',
        '_id']`, but a minority also carry `GroupCount`. Read anything beyond
        `_id`/`Name`/`Applications` with `.get` — an earlier note here generalised a key-set from
        one sample and was wrong."""
        c = self._cfg
        return self._json("GET", f"{c.base}/app_role/2/{c.account}/{role_id}")

    def put_app_role(self, role_id: str, body: dict[str, Any], app_id: str | None = None) -> Any | Err:
        """Write an AppRole's own record — the SAME route `get_app_role` reads. Proven live
        2026-08-12 (#52): `PUT /app_role/2/{acct}/{role_id}?_application_id={app}`. Used for both
        assigning users (⚠️ WRITE key `Users`, asymmetric with the READ key `Members` — a `Members`
        write silently no-ops) and setting `Preference` (DefaultPage/DefaultNavigation)."""
        c = self._cfg
        scope = app_id if app_id is not None else c.app_id
        return self._json("PUT", f"{c.base}/app_role/2/{c.account}/{role_id}?_application_id={scope}",
                          body)

    def get_assignee(self, query: str) -> list[dict[str, Any]] | Err:
        """Search for a real user to hand to `put_app_role`'s `Users` write. Proven live
        2026-08-12 (#52): `GET /user/2/{acct}/assignee?q=<query>` -> a bare array of assignee
        objects `{_id, Kind:"User", Email, Name}`, written onto a role VERBATIM."""
        c = self._cfg
        return self._json("GET", f"{c.base}/user/2/{c.account}/assignee?q={query}")

    def delete_member(self, kind: FlowKind, flow_id: str, role_id: str) -> Any | Err:
        """Remove an AppRole's grant on a flow entirely — the "No access" tier
        (shapes/app_role_grant.json note 0, browser-proven 2026-08-12): a real removal route,
        `DELETE /flow/2/{acct}/{kind}/{flow_id}/member/{role_id}?_application_id={app}`."""
        c = self._cfg
        return self._json(
            "DELETE",
            f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}/member/{role_id}"
            f"?_application_id={c.app_id}",
        )

    def post_member_batch(self, kind: FlowKind, flow_id: str, members: list[dict[str, Any]]) -> Any | Err:
        """CLAUDE.md Permissions: body=[{_id,Name,Kind:"AppRole",Role,Permission}]. `Name` is validated
        against AppRoles that ALREADY exist in the account — `KISSFLOW_ERROR_00051
        UserOrGroupDoesNotExistError` ("The AppRole {Name} does not exist in your account") on any
        name that isn't a real, pre-existing AppRole. The role MUST also be scoped to KF_APP: a role
        that exists in the account but is scoped to a DIFFERENT app is rejected with the SAME 00051
        (proven live 2026-08-08: the 4 oracle roles exist account-wide but are scoped to a different
        app, and member/batch rejects them). So create the role scoped to KF_APP FIRST
        (`create_app_role`), then grant it here."""  # CORRECTED 2026-08-08: the prior "only the
        # builder UI creates AppRoles, no API route" note was FALSE — create_app_role below does it.
        c = self._cfg
        return self._json("POST", f"{c.base}/flow/2/{c.account}/{kind}/{flow_id}/member/batch"
                                  f"?_application_id={c.app_id}", members)

    def create_app_role(self, name: str, app_id: str | None = None) -> str | Err:
        """Create an AppRole in the account, scoped to `app_id` (defaults to KF_APP). PROVEN live
        2026-08-08: `POST /app_role/2/{acct}` body `{"Name": <name>, "_application_id": <app_id>}`
        -> 200 `{"_id": "RoDy...", "Name": <name>}`. CORRECTS the long-held CLAUDE.md belief that
        "no API route creates an AppRole — only the builder UI does" (that was never re-probed after
        an early 404 sweep; the route is `POST /app_role/2/{acct}`, not any of the `/.../app_role`
        suffixes that 404). Without `_application_id` the role is created UNSCOPED and member/batch
        still rejects it (00051) — a role must be scoped to KF_APP to bind onto one of its flows.
        Idempotent ONLY in the sense that the same Name can exist on multiple role ids; callers that
        need a stable id should `list_app_roles(app_id)` + match by Name first and reuse an existing
        one rather than creating a duplicate."""
        c = self._cfg
        scope = app_id if app_id is not None else c.app_id
        got = self._json("POST", f"{c.base}/app_role/2/{c.account}",
                         {"Name": name, "_application_id": scope})
        if isinstance(got, Err):
            return got
        if isinstance(got, dict) and got.get("_id"):
            return str(got["_id"])
        return Err("verify", f"create_app_role({name!r}) returned no _id: {got!r}")

    def delete_app_role(self, role_id: str) -> Any | Err:
        """Delete an AppRole. PROVEN live 2026-08-08: `DELETE /app_role/2/{acct}/{role_id}` -> 200
        `{"status":"success"}`; a follow-up GET 403s `KISSFLOW_ERROR_03069 RoleDoesNotExistsError`,
        confirming real deletion (not a soft 200 like the page-DELETE trap). Use to clean up
        throwaway roles created during probes."""
        c = self._cfg
        return self._json("DELETE", f"{c.base}/app_role/2/{c.account}/{role_id}")

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

    # --- word lists (#13, probed live 2026-08-12 on the dev tenant) -------------------------
    def list_lists(self) -> list[dict[str, Any]] | Err:
        """App-scoped list inventory. `_application_id` is load-bearing — without it this route
        silently returns the WHOLE account's lists (CLAUDE.md Item data plane leakage note)."""
        c = self._cfg
        return self._json("GET", f"{c.base}/flow/2/{c.account}/list"
                                 f"?page_size=100&_application_id={c.app_id}")

    def create_list(self, name: str) -> dict[str, Any] | Err:
        """Create a word-list flow: `POST /flow/2/{acct}/list?_application_id={app}` with
        `{"Name": ...}` -> `{_id, Type:"List", Status:"Live"}` — born LIVE, no publish step.
        Duplicate name 400s `FlowNameAlreadyExists` (same as an application create)."""
        c = self._cfg
        return self._json("POST", f"{c.base}/flow/2/{c.account}/list?_application_id={c.app_id}",
                          {"Name": name})

    def set_list_items(self, list_id: str, items: list[str]) -> Any | Err:
        """SET the list's whole item array: `POST .../list/{id}/items` body
        `{"ListItems": [...]}`. REPLACE semantics, proven by a two-write live probe (2026-08-12):
        a second POST replaces the first array outright, so re-running is idempotent and there is
        no separate delete route to need. A bare array 403s TypeMissMatchError; other dict keys
        400 InvalidSchemaArguments — `ListItems` is the one accepted shape."""
        c = self._cfg
        return self._json("POST", f"{c.base}/flow/2/{c.account}/list/{list_id}/items",
                          {"ListItems": items})

    def create_dataset(self, name: str) -> dict[str, Any] | Err:
        """Create a dataform (flowtype `dataset`). Proven live 2026-08-12 (#50):
        `POST /flow/2/{acct}/dataset?_application_id={app}` body `{"Name": ...}` -> born LIVE,
        `{_id, Type:"Dataset", Status:"Live"}`. NO publish route exists at all for this flowtype —
        the draft IS live (shapes/dataform_dataset_skeleton.json)."""
        c = self._cfg
        return self._json("POST", f"{c.base}/flow/2/{c.account}/dataset?_application_id={c.app_id}",
                          {"Name": name})

    def create_case(self, name: str, item_type: str, prefix: str) -> dict[str, Any] | Err:
        """Create a board/case (flowtype `case`). Proven live 2026-08-12 (#49):
        `POST /flow/2/{acct}/case?_application_id={app}` body `{"Name", "ItemType", "Prefix"}` —
        BOTH `ItemType` ("Board"|"Case") and `Prefix` are MANDATORY (400 MissingRequiredFieldError
        without them; both ItemType values produce a byte-identical graph). Born LIVE, no publish
        step (shapes/board_case_skeleton.json)."""
        c = self._cfg
        return self._json("POST", f"{c.base}/flow/2/{c.account}/case?_application_id={c.app_id}",
                          {"Name": name, "ItemType": item_type, "Prefix": prefix})

    def create_dataset_record(self, flow_id: str, record: dict[str, Any]) -> dict[str, Any] | Err:
        """Create ONE dataform record. Proven live 2026-08-12 (#50):
        `POST /dataset/2/{acct}/{flow_id}` body `{"Name": ..., "<FieldId>": value, ...}` — `Name`
        is a synthetic system column (the record's unique key); a duplicate 409s
        DuplicateKeyException."""
        c = self._cfg
        return self._json("POST", f"{c.base}/dataset/2/{c.account}/{flow_id}"
                                  f"?_application_id={c.app_id}", record)

    def list_dataset_records(self, flow_id: str) -> dict[str, Any] | Err:
        """List a dataform's records + schema. Proven live 2026-08-12 (#50):
        `GET /dataset/2/{acct}/{flow_id}/list?_application_id={app}` -> `{Columns, Data}`."""
        c = self._cfg
        return self._json("GET", f"{c.base}/dataset/2/{c.account}/{flow_id}/list"
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
    field_matrix: Matrix | None = None,
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
        new = set_step_permissions(draft, matrix, field_matrix)
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


def apply_layout(
    client: KfClient,
    flow_id: str,
    layout: dict[str, list[list[tuple[str, int, int]]]],
    descriptions: dict[str, str] | None = None,
    publish: bool = False,
    kind: FlowKind = "process",
) -> ApplyReport | Err:
    """GET draft -> graph.apply_exact_layout (place every field column at its stated grid
    coordinates, rebuilding Rows; Field/Column ids and their Permission/Event back-refs survive) ->
    guarded PUT -> read-back verify the section row count matches the spec -> optional publish.

    `descriptions` optionally sets each section's `Description` in the same write. A field or
    section named in `layout` but absent from the draft is a hard error (the offline
    `apply_exact_layout` raises before any write), so a stale layout spec never silently drops a
    field off the form. Always writes: a re-layout is a real change even with no new fields.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        new = apply_exact_layout(draft, layout, descriptions=descriptions)
    except ValueError as e:
        return Err("verify", f"offline apply_exact_layout rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back

    wanted_sections = tuple(layout)
    published = False
    if publish:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return ApplyReport(
        flow_id=flow_id, added=(), skipped=wanted_sections, verified=wanted_sections,
        missing=(), meta_version=read_back.get(_META_VERSION), published=published,
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


@dataclass(frozen=True)
class ListReport:
    """Output-invariant audit for forge_create_list: every requested item value lands in exactly
    one bucket after the read-back — `verified_items` or `missing_items`."""
    list_id: str
    name: str
    created: bool                        # False when a list of that name already existed (reused)
    items: tuple[str, ...]
    verified_items: tuple[str, ...]
    missing_items: tuple[str, ...]

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "list_id": self.list_id, "name": self.name, "created": self.created,
            "items": list(self.items), "verified_items": list(self.verified_items),
            "missing_items": list(self.missing_items), "isError": bool(self.missing_items),
        }


def apply_word_list(
    client: KfClient,
    name: str,
    items: list[str],
) -> ListReport | Err:
    """Create-or-reuse a word list by NAME, SET its items, read back every value (#13).

    Routes probed live 2026-08-12: create `POST /flow/2/{acct}/list?_application_id={app}`
    (born LIVE, no publish step); items `POST .../list/{id}/items` `{"ListItems":[...]}` with
    REPLACE semantics — so this whole function is idempotent. Resolution by name goes through
    the app-scoped inventory, never an unscoped route (leakage rule). Read-back is the audit:
    a requested value absent from the live item array lands in `missing_items`, never silently.
    """
    inventory = client.list_lists()
    if isinstance(inventory, Err):
        return inventory
    rows = inventory.get("Data", inventory) if isinstance(inventory, dict) else inventory
    existing = {r.get("Name"): r.get("_id") for r in rows if isinstance(r, dict)}

    created = name not in existing
    if created:
        made = client.create_list(name)
        if isinstance(made, Err):
            return made
        list_id = made.get("_id", "")
    else:
        list_id = existing[name]
    if not list_id:
        return Err("verify", f"list {name!r}: no _id resolvable from create/inventory")

    wrote = client.set_list_items(list_id, items)
    if isinstance(wrote, Err):
        return wrote

    live = client.get_list_items(list_id)
    if isinstance(live, Err):
        return live
    live_set = set(live)
    return ListReport(
        list_id=list_id, name=name, created=created, items=tuple(items),
        verified_items=tuple(v for v in items if v in live_set),
        missing_items=tuple(v for v in items if v not in live_set),
    )


def apply_table(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    name: str,
    columns: list[tuple[str, str]] | list[tuple[str, str, dict[str, Any] | None]],
    max_rows: int | None = None,
    allow_import: bool = False,
    publish: bool = False,
    after_section: str | None = None,
) -> TableReport | Err:
    """GET draft -> graph.add_table offline (idempotent: no-op if a table named `name` already
    exists) -> guarded PUT (skipped on the idempotent no-op path) -> read-back verify every child
    column NAME actually landed under that table -> optional publish.

    `after_section` (#10) places the host row directly after that Section's root row in
    `Model::Row` — a banner section stranded away from its table breaks the whole form's render.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)
    wanted_cols = tuple(c[0] for c in columns)

    already = any(isinstance(v, dict) and v.get("Type") == "Model" and v.get("Name") == name
                 for v in draft.values())
    try:
        new = add_table(draft, name, columns, max_rows=max_rows, allow_import=allow_import,
                        after_section=after_section)
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
    step_meta: dict[str, dict[str, Any]] | None = None,
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
                             roles=roles, step_meta=step_meta)
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
    branch_name: str | None = None

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "goto_activity_id": self.goto_activity_id,
            "target_activity": self.target_activity, "field_name": self.field_name,
            "branch_name": self.branch_name, "verified": self.verified,
            "meta_version": self.meta_version,
            "published": self.published, "isError": not self.verified,
        }


def _parallel_branches(draft: Draft) -> dict[str, str] | Err:
    """The flow's single Parallel gateway's branches, as {branch NAME: branch ProcessDef id}
    (Node M, conditional routing). Requires EXACTLY ONE Parallel Activity on the draft — fails
    loud rather than guessing which one a caller meant when there is more than one (CLAUDE.md:
    never guess), and matches `graph.build_workflow`'s own ceiling of a single `parallel` gateway
    per flow. A branch name that is not unique across the gateway's own ProcessDef::Expression
    list (two branches given the SAME Name) is ALSO refused rather than silently keeping only the
    last match — an ambiguous name is exactly the class of mistake this helper exists to catch
    before a live write, not after.
    """
    parallels = [v for v in draft.values() if isinstance(v, dict) and v.get("Kind") == "Activity"
                and v.get("NodeType") == "Parallel"]
    if len(parallels) != 1:
        return Err("verify",
                   f"expected exactly one Parallel gateway on the flow, found {len(parallels)}")
    names: list[str] = []
    out: dict[str, str] = {}
    for pd_id in parallels[0].get("Activity::ProcessDef") or []:
        pd = draft.get(pd_id)
        name = pd.get("Name") if isinstance(pd, dict) else None
        if not isinstance(name, str):
            continue
        names.append(name)
        out[name] = pd_id
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        return Err("verify", f"ambiguous branch name(s) on the Parallel gateway: {dupes}")
    return out


def _describe_owner(draft: Draft, pd_id: str | None) -> str:
    """Human-readable label for a ProcessDef, for an ambiguity error message: its branch Name if
    it's a branch, "the root chain" if it's the root Sequence ProcessDef, or the raw id as a last
    resort (a malformed draft with a ProcessDef missing both)."""
    pd = draft.get(pd_id) if isinstance(pd_id, str) else None
    if isinstance(pd, dict):
        name = pd.get("Name")
        if isinstance(name, str):
            return f"branch {name!r}"
        if pd.get("WorkflowType") == "Sequence":
            return "the root chain"
    return f"ProcessDef {pd_id!r}"


def _resolve_activity_by_name(
    draft: Draft, name: str, *, process_def_id: str | None = None,
) -> str | Err:
    """Resolve an Activity by NAME, raising on ambiguity rather than silently taking the first
    match by dict iteration order (Node M review, 2026-08-07): a step name that repeats across
    branches used to resolve to "whichever one is iterated first," with a clean `verified: True`
    report on a GotoTask built in the WRONG branch — a wrong graph with a clean report is exactly
    the silent-success class this project bans (CLAUDE.md > output-invariant audits).

    `process_def_id`, when given, scopes the search to ONE ProcessDef's own activities (raises if
    that SAME branch somehow carries the name twice — still an ambiguity, just a smaller one);
    omitted, the search spans the whole draft, and an ambiguity across branches — or between a
    branch and the root chain — is exactly the case `apply_goto_gate`'s `branch_name` exists to
    resolve. The error message names every candidate's owning branch (or "the root chain") so the
    caller knows what to pass, never just a bare count.
    """
    candidates = [k for k, v in draft.items()
                 if isinstance(v, dict) and v.get("Kind") == "Activity" and v.get("Name") == name
                 and (process_def_id is None or v.get("ProcessDef") == process_def_id)]
    if not candidates:
        where = f" in {_describe_owner(draft, process_def_id)}" if process_def_id else ""
        return Err("verify", f"no workflow step named {name!r}{where}")
    if len(candidates) > 1:
        owners = sorted({_describe_owner(draft, draft.get(c, {}).get("ProcessDef"))
                         for c in candidates})
        return Err("verify",
                   f"step name {name!r} is ambiguous — it exists in {len(candidates)} places "
                   f"({', '.join(owners)}); pass branch_name to disambiguate which one you mean")
    return candidates[0]


def apply_goto_gate(
    client: KfClient,
    flow_id: str,
    target_activity_name: str,
    field_name: str,
    branch_name: str | None = None,
    publish: bool = False,
    kind: FlowKind = "process",
) -> GotoGateReport | Err:
    """GET draft -> resolve the target workflow step + gating Boolean field BY NAME -> ONE guarded
    write combining graph.add_goto_task (mints the GotoTask edge node — see its docstring, nothing
    else in this pack creates one) + expr.build_goto_gate (attaches the `= false()` loop condition,
    gate-polarity-checked: only a Boolean may gate a loop, CLAUDE.md Gate polarity) -> read-back
    verify the condition landed -> optional publish.

    `branch_name` (Node M, conditional routing), when given, scopes target resolution to ONE
    branch of the flow's single Parallel gateway (`_parallel_branches`) — the target step is
    looked up ONLY among that branch's own activities, and `graph.add_goto_task`'s
    `branch_process_def_id` pins/validates the new GotoTask into that SAME branch's chain (last
    within it, never the root chain or a sibling branch). Required whenever `target_activity_name`
    is not unique across branches — without it, resolution spans the WHOLE draft
    (`_resolve_activity_by_name` with no `process_def_id`), same as before this parameter existed
    for a genuinely unambiguous name. ⚠️ Node M review (2026-08-07): a name that collides across
    branches — or between a branch and the root chain — used to silently resolve to "whichever one
    dict iteration finds first," building a structurally correct-looking GotoTask in the WRONG
    branch with a clean `verified: True` report; `_resolve_activity_by_name` now raises loud,
    naming every candidate's owning branch, instead of ever guessing. Omit `branch_name` only for a
    target you know is genuinely unique.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    branch_pd_id: str | None = None
    if branch_name is not None:
        branches = _parallel_branches(draft)
        if isinstance(branches, Err):
            return branches
        branch_pd_id = branches.get(branch_name)
        if branch_pd_id is None:
            return Err("verify", f"no branch named {branch_name!r} on the Parallel gateway "
                                  f"(real branches: {sorted(branches)})")
        target_id = _resolve_activity_by_name(draft, target_activity_name,
                                              process_def_id=branch_pd_id)
    else:
        target_id = _resolve_activity_by_name(draft, target_activity_name)
    if isinstance(target_id, Err):
        return target_id

    field_id = next((k for k, v in draft.items()
                     if isinstance(v, dict) and v.get("Kind") == "Field"
                     and v.get("Name") == field_name), None)
    if field_id is None:
        return Err("verify", f"no field named {field_name!r}")

    try:
        with_goto, goto_id = add_goto_task(draft, target_activity_id=target_id,
                                           branch_process_def_id=branch_pd_id)
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
        target_activity=target_activity_name, field_name=field_name, branch_name=branch_name,
        verified=verified, meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class BranchConditionReport:
    """Output-invariant audit for forge_set_branch_conditions (Node M, conditional routing): every
    branch name in `branches` lands in `verified` or `missing` after the read-back — never
    silently unaccounted for.

    `uncovered` (Node M review, 2026-08-07) is a SEPARATE, non-error bucket: the deciding field's
    REAL live options (Select-backed only — see `_uncovered_options`) that, after this write, no
    branch on the SAME Parallel gateway claims via a condition on THIS field — including branches
    this call never touched. An item whose value matches none of them does not park and does not
    error: it silently skips the ENTIRE Parallel and completes with no work done (verified live
    2026-08-07 — CLAUDE.md > Conditional routing's own "fail OPEN, not closed" warning, the same
    hazard class Gate polarity already names for a loop, now confirmed for a switch). A caller may
    genuinely want an ending value like that (the CLAUDE.md war story is about an ACCIDENTAL gap,
    not every gap being a bug) — `uncovered` is therefore never folded into `isError`, only stated,
    so it is never silently discovered later.
    """
    flow_id: str
    field_name: str
    branches: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    uncovered: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "field_name": self.field_name,
            "branches": list(self.branches), "verified": list(self.verified),
            "missing": list(self.missing), "uncovered": list(self.uncovered),
            "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing),
        }


def _literals_for_field(draft: Draft, pd_id: str, field_id: str) -> set[str]:
    """Every literal a branch ProcessDef's OWN condition(s) compare `field_id` against — normally
    0 or 1, but read as a set defensively (a hand-edited or pre-existing draft could carry more
    than one Expression on the same ProcessDef). Filters to conditions ON `field_id` specifically —
    a branch conditioned on some OTHER field is not part of this field's coverage picture at all.
    """
    out: set[str] = set()
    pd = draft.get(pd_id) or {}
    for eid in pd.get("ProcessDef::Expression") or []:
        e = draft.get(eid) or {}
        for root_id in e.get("Expression::Node") or []:
            children = [draft.get(c) or {}
                       for c in (draft.get(root_id) or {}).get("Node::Node") or []]
            if not any(c.get("Type") == "Field" and c.get("Field") == field_id for c in children):
                continue
            for c in children:
                if c.get("Type") == "Static" and isinstance(c.get("Value"), str):
                    out.add(c["Value"])
    return out


def _uncovered_options(
    draft: Draft, branch_pd_ids: Iterable[str], field_id: str, options: list[str] | None,
) -> tuple[str, ...]:
    """Real Select options (see `BranchConditionReport.uncovered`) that NO branch among
    `branch_pd_ids` currently conditions on `field_id`. `options=None` (a non-Select or list-less
    deciding field, e.g. Text) has no enumerable option universe to check against — there is no
    general way to prove "some string value has no matching branch" when the value space is
    unbounded — so this returns `()`, meaning "nothing checked," not "fully covered."
    """
    if options is None:
        return ()
    covered: set[str] = set()
    for pd_id in branch_pd_ids:
        covered |= _literals_for_field(draft, pd_id, field_id)
    return tuple(o for o in options if o not in covered)


def apply_branch_conditions(
    client: KfClient,
    flow_id: str,
    field_name: str,
    branch_literals: dict[str, str],
    publish: bool = False,
    kind: FlowKind = "process",
) -> BranchConditionReport | Err:
    """Make an existing Parallel's branches CONDITIONAL (Node M — closes the gap that
    `expr.build_branch_condition` had zero callers from the MCP surface, and `forge_build_workflow`
    could only build an UNCONDITIONAL and-fork).

    GET draft -> resolve the flow's single Parallel gateway's branches BY NAME (`_parallel_branches`
    — exactly one Parallel required) -> resolve the deciding field BY NAME -> when that field is a
    Select backed by a `ReferredList`, fetch its REAL live options and validate every literal in
    `branch_literals` against them BEFORE any write (CLAUDE.md Expressions: "never guess a literal
    — read it"; a Text-typed deciding field has no list to validate against, so its literals are
    written as given — same `options=None` contract `expr.build_branch_condition` itself documents)
    -> for each named branch, offline REMOVE any condition it already has
    (`expr.remove_condition`) and ATTACH the new one (`expr.build_branch_condition`,
    `<field> = "<literal>"`, a ProcessDef-owned Expression) -> ONE guarded PUT -> read-back verify
    each branch's Expression carries the field+literal it was given -> optional publish.

    Only the branches named in `branch_literals` are touched — any other branch on the same
    Parallel keeps whatever condition (or lack of one) it already had. The remove-then-attach pair
    makes this idempotent in the SET sense: re-running with a changed literal replaces that
    branch's condition rather than accumulating a second one (`remove_condition`'s own docstring).
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    branches = _parallel_branches(draft)
    if isinstance(branches, Err):
        return branches
    unknown = sorted(set(branch_literals) - set(branches))
    if unknown:
        return Err("verify", f"no branch(es) named {unknown} on the Parallel gateway "
                              f"(real branches: {sorted(branches)})")

    field_id = next((k for k, v in draft.items()
                     if isinstance(v, dict) and v.get("Kind") == "Field"
                     and v.get("Name") == field_name), None)
    if field_id is None:
        return Err("verify", f"no field named {field_name!r}")

    options: list[str] | None = None
    field_node = draft[field_id]
    if field_node.get("Type") == "Select" and field_node.get("ReferredList"):
        items = client.get_list_items(field_node["ReferredList"])
        if isinstance(items, Err):
            return items
        options = list(items) if isinstance(items, list) else []

    new = draft
    try:
        for branch_name, literal in branch_literals.items():
            pd_id = branches[branch_name]
            for existing_eid in list(new[pd_id].get("ProcessDef::Expression") or []):
                new = remove_condition(new, expression_id=existing_eid)
            new = build_branch_condition(new, process_def_id=pd_id, field_id=field_id,
                                         literal=literal, options=options)
    except ValueError as e:
        return Err("verify", f"offline build_branch_condition rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back

    def _landed(branch_name: str, literal: str) -> bool:
        pd = read_back.get(branches[branch_name]) or {}
        for eid in pd.get("ProcessDef::Expression") or []:
            e = read_back.get(eid) or {}
            for root_id in e.get("Expression::Node") or []:
                children = [read_back.get(c) or {}
                           for c in (read_back.get(root_id) or {}).get("Node::Node") or []]
                has_field = any(c.get("Type") == "Field" and c.get("Field") == field_id
                               for c in children)
                has_literal = any(c.get("Type") == "Static" and c.get("Value") == literal
                                  for c in children)
                if has_field and has_literal:
                    return True
        return False

    wanted = tuple(branch_literals)
    verified = tuple(b for b in wanted if _landed(b, branch_literals[b]))
    missing = tuple(b for b in wanted if b not in verified)
    # against the FULL branch set (not just the ones this call touched) -- a value that some
    # EARLIER call already covered on a different branch must never re-appear here as a false
    # alarm, and a value nothing covers, ever, is exactly what a caller needs to see.
    uncovered = _uncovered_options(read_back, branches.values(), field_id, options)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return BranchConditionReport(
        flow_id=flow_id, field_name=field_name, branches=wanted, verified=verified,
        missing=missing, uncovered=uncovered, meta_version=read_back.get(_META_VERSION),
        published=published,
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
class SequenceNumberReport:
    flow_id: str
    field_name: str
    section: str
    verified: bool
    missing: bool
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "field_name": self.field_name, "section": self.section,
            "verified": self.verified, "missing": self.missing,
            "meta_version": self.meta_version, "published": self.published,
            "isError": self.missing,
        }


def apply_sequence_number(
    client: KfClient,
    flow_id: str,
    field_name: str,
    section_name: str,
    prefix: str,
    padding: str,
    step_activity_name: str,
    start: int = 0,
    end: int = 2,
    publish: bool = False,
    kind: FlowKind = "process",
) -> SequenceNumberReport | Err:
    """GET draft -> graph.add_sequence_number offline (resolves the Step-stamp activity by NAME) ->
    guarded PUT -> read-back verify the SequenceNumber Field + its 3 Property nodes landed ->
    optional publish.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        new = add_sequence_number(draft, field_name, section_name, prefix, padding,
                                  step_activity_name, start=start, end=end)
    except ValueError as e:
        return Err("verify", f"offline add_sequence_number rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    fld = next((v for v in read_back.values()
                if isinstance(v, dict) and v.get("Kind") == "Field"
                and v.get("Type") == "SequenceNumber" and v.get("Name") == field_name), None)
    props_ok = bool(fld and len(fld.get("Field::Property") or []) == 3)
    verified = fld is not None and props_ok

    published = False
    if publish and verified:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return SequenceNumberReport(flow_id=flow_id, field_name=field_name, section=section_name,
                                verified=verified, missing=not verified,
                                meta_version=read_back.get(_META_VERSION), published=published)


@dataclass(frozen=True)
class ValidationReport:
    flow_id: str
    field_name: str
    rules: tuple[tuple[str, str], ...]
    verified: tuple[tuple[str, str], ...]
    missing: tuple[tuple[str, str], ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "field_name": self.field_name,
            "rules": [list(r) for r in self.rules],
            "verified": [list(r) for r in self.verified],
            "missing": [list(r) for r in self.missing],
            "meta_version": self.meta_version, "published": self.published,
            "isError": bool(self.missing),
        }


def apply_field_validation(
    client: KfClient,
    flow_id: str,
    rules: dict[str, list[tuple[str, str]]],
    publish: bool = False,
    kind: FlowKind = "process",
) -> ValidationReport | Err:
    """GET draft -> graph.add_field_validation offline (one Condition per (operator, value) rule,
    reusing the field's existing Criteria) -> guarded PUT -> read-back verify each rule landed ->
    optional publish. `rules` is `{field_name: [(operator, value), ...]}`.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    new = draft
    try:
        for fname, fl_rules in rules.items():
            for operator, value in fl_rules:
                new = add_field_validation(new, fname, operator, value)
    except ValueError as e:
        return Err("verify", f"offline add_field_validation rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    by_name = {v.get("Name"): v for v in read_back.values()
               if isinstance(v, dict) and v.get("Kind") == "Field"}
    flat: tuple[tuple[str, str], ...] = tuple((op, val) for _, rs in rules.items() for op, val in rs)
    verified: list[tuple[str, str]] = []
    for fname, fl_rules in rules.items():
        fld = by_name.get(fname, {})
        live: set[tuple[str, str]] = set()
        for cid in fld.get("FieldValidation::Criteria") or []:
            for condid in (read_back.get(cid, {}).get("Criteria::Condition") or []):
                c = read_back.get(condid, {})
                if isinstance(c.get("Operator"), str):
                    live.add((c["Operator"], str(c.get("RHSValue"))))
        for op, val in fl_rules:
            if (op, val) in live:
                verified.append((op, val))
    missing = tuple(r for r in flat if r not in verified)

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return ValidationReport(flow_id=flow_id, field_name=",".join(rules), rules=flat,
                            verified=tuple(verified), missing=missing,
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
    styles: dict[str, dict[str, Any]],
    publish: bool = False,
    kind: FlowKind = "process",
    root_style: dict[str, Any] | None = None,
    hint_text_position: str | None = None,
) -> StyleReport | Err:
    """GET draft -> graph.set_section_style offline (colour TOKEN REFS only on forms — CLAUDE.md
    warns these are UNVALIDATED by the API and fail silently at render if wrong; callers should
    only ever pass tokens read off the live oracle: Color.Info.300, Color.Secondary.Ten.800,
    Color.Primary.500, Color.Transparent — or one seen in the builder's own dropdown) -> guarded
    PUT -> read-back verify the Style.Value landed -> optional publish.

    `root_style`/`hint_text_position` (#11) address the ROOT Model's own Appearance/Style chain;
    per-section values accept a bare token (wrapped {"ref": ...}) or an explicit
    {"ref"/"value": ...} dict verbatim.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        new = set_section_style(draft, styles, root_style=root_style,
                                hint_text_position=hint_text_position)
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
        return all(value.get(k) == _style_wire_value(k, v)
                   for k, v in wanted.items() if v is not None)

    def _root_landed() -> bool:
        model_id = read_back.get("Root", "")
        app_ids = (read_back.get(model_id) or {}).get("Model::Appearance") or []
        if not app_ids:
            return False
        app = read_back.get(app_ids[0]) or {}
        style_ids = app.get("Appearance::Style") or []
        if not style_ids:
            return False
        value = (read_back.get(style_ids[0]) or {}).get("Value") or {}
        ok = all(value.get(k) == _style_wire_value(k, v)
                 for k, v in (root_style or {}).items() if v is not None)
        if hint_text_position is not None:
            ok = ok and app.get("HintTextPosition") == hint_text_position
        return ok

    wanted_names = tuple(styles) + (("<root>",) if (root_style or hint_text_position) else ())
    verified = tuple(n for n in tuple(styles) if _landed(n))
    if (root_style or hint_text_position) and _root_landed():
        verified += ("<root>",)
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
    visibility_role_claims: list[str] | None = None,
) -> dict[str, Any] | Err:
    """Fetch the LIVE draft, harvest every Select field's REAL list options (CLAUDE.md: 'never
    guess a literal — read it'), and run verify.doctor for real — the read-only diagnostic behind
    forge_doctor.

    A list whose items fetch fails is recorded in `list_fetch_errors` (never silently dropped from
    the audit) and simply excluded from `list_options`, so any branch literal that depended on it
    reports as `unvalidated` rather than falsely `ok`.

    `visibility_role_claims` (from the plan's doctor op — see compile's `_op_doctor`) FAILs the
    audit per claim: role-scoped visibility is API-impossible (#6, ADR-0004).
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
        report = doctor(draft, list_options=list_options,
                        visibility_role_claims=visibility_role_claims or ())
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
    role_ids: tuple[str, ...] = ()       # the ACTUAL AppRole `_id`s granted -- needed by a caller
                                          # that wants to wire one as a workflow step's assignee
                                          # (e.g. build_workflow's `roles=`). Only populated by the
                                          # account-level path (`_apply_own_app_roles`); the
                                          # sibling-harvest path's `harvested`/`verified`/`missing`
                                          # already carry the harvested member's `Role` TYPE string
                                          # (e.g. "DataAdmin"), a different thing, unchanged here.
    resolved: tuple[tuple[str, str], ...] = ()  # (display_name, a00_scoped_role_id) -- the
                                          # name->id mapping apply_member_roles resolved, so a
                                          # caller can remap a step->name table onto step->a00_id for
                                          # build_workflow's `roles=`/step assignees. Empty on the
                                          # sibling-harvest path (which carries ids in role_ids).

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "target_flow_id": self.target_flow_id, "source_flow_id": self.source_flow_id,
            "harvested": list(self.harvested), "applied": list(self.applied),
            "verified": list(self.verified), "missing": list(self.missing), "note": self.note,
            "role_ids": list(self.role_ids),
            "resolved": {name: rid for name, rid in self.resolved},
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


# Grant proven live 2026-08-07 (throwaway flow, two-arm control): `Permission: []` 200s the
# member/batch call itself, but the initiator still can't submit their own draft (403
# KISSFLOW_ERROR_050302 "You don't have permission to submit this item anymore"). Only
# `Permission: ["InitiateItems"]` actually lets the initiator advance their own item.
# `_ACCOUNT_GRANT_ROLE` is PROCESS-flow-specific — CLAUDE.md Members first notes list flows want
# `Admin`/`Member` instead of `DataAdmin`; unverified for those kinds, don't reuse blind.
_ACCOUNT_GRANT_ROLE = "DataAdmin"
_ACCOUNT_GRANT_PERMISSION = ("InitiateItems",)


def _apply_own_app_roles(client: KfClient, target_flow_id: str, kind: FlowKind) -> MemberReport | Err:
    """Fallback used when NO sibling flow has members to harvest from: grant the APP'S OWN
    AppRoles, discovered at the ACCOUNT level (`KfClient.list_app_roles`). CLAUDE.md Members first
    used to claim no route lists app roles from scratch — CORRECTED 2026-08-07, that belief was
    about a different suffix (`/app_role/.../external/list`, which really is empty); the
    account-level `/app_role/2/{acct}/list` route lists every AppRole, filterable to the ones
    scoped to this app.

    Same read-verify-write shape as every other apply_* here: grant -> read back `get_members` ->
    every AppRole `_id` we posted lands in `verified` or `missing`, never silently unaccounted for.
    """
    app_id = client._cfg.app_id
    roles = client.list_app_roles(app_id)
    if isinstance(roles, Err):
        return roles
    usable = [r for r in roles if isinstance(r, dict) and r.get("_id") and r.get("Name")]
    if not usable:
        return MemberReport(
            target_flow_id=target_flow_id, source_flow_id=None, harvested=(), applied=(),
            verified=(), missing=(),
            note=f"no existing flow with members found in KF_APP to harvest from, AND the "
                 f"account-level AppRole list has no role scoped to app {app_id!r} either — a "
                 f"human must create at least one AppRole for this app in the builder UI first",
        )

    members = [
        {"_id": r["_id"], "Name": r["Name"], "Kind": "AppRole",
         "Role": _ACCOUNT_GRANT_ROLE, "Permission": list(_ACCOUNT_GRANT_PERMISSION)}
        for r in usable
    ]
    role_ids = tuple(m["_id"] for m in members)
    names = tuple(m["Name"] for m in members)

    posted = client.post_member_batch(kind, target_flow_id, members)
    if isinstance(posted, Err):
        return posted

    read_back = client.get_members(kind, target_flow_id)
    if isinstance(read_back, Err):
        return read_back
    live_ids = {str(m.get("_id")) for m in read_back if isinstance(m, dict)}
    verified = tuple(r for r in role_ids if r in live_ids)
    missing = tuple(r for r in role_ids if r not in live_ids)

    return MemberReport(
        target_flow_id=target_flow_id, source_flow_id=None, harvested=names, applied=role_ids,
        verified=verified, missing=missing, role_ids=role_ids,
        note=f"granted {len(members)} AppRole(s) discovered at the account level for app "
             f"{app_id!r} (no sibling flow had members to harvest) — Role={_ACCOUNT_GRANT_ROLE!r} "
             f"Permission={list(_ACCOUNT_GRANT_PERMISSION)!r}: {', '.join(names)}",
    )


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
    source is given and none can be discovered either (no sibling flow in KF_APP has a member to
    harvest from), this FALLS BACK to granting the app's own AppRoles discovered at the account
    level (`_apply_own_app_roles`) rather than just reporting an empty harvest — proven live
    2026-08-07 that this account-level route exists and works end to end. Only when THAT also
    finds nothing (no AppRole is scoped to this app at all) is the "genuinely nothing to harvest
    yet" empty report used — a caller must be able to tell that apart from a real failure, never
    silently treat one as the other.
    """
    if source_flow_id is None:
        discovered = discover_member_source(client, kind, target_flow_id)
        if isinstance(discovered, Err):
            return discovered
        source_flow_id = discovered

    if source_flow_id is None:
        return _apply_own_app_roles(client, target_flow_id, kind=kind)

    raw = client.get_members(kind, source_flow_id)
    if isinstance(raw, Err):
        return raw

    normalized = [n for r in raw if (n := _normalize_member(r)) is not None]
    harvested = tuple(str(n.get("Role")) for n in normalized)
    # role_ids: the harvested AppRole `_id`s -- _normalize_member already keeps `_id` (one of the
    # 5 documented member/batch keys), so this is populated on BOTH paths apply_member_batch can
    # take, not just the account-level fallback (_apply_own_app_roles). A caller (e.g. a workflow
    # step assignee) must be able to rely on `role_ids` regardless of which path granted them.
    role_ids = tuple(str(n["_id"]) for n in normalized if n.get("_id"))
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
        applied=harvested, verified=verified, missing=missing, role_ids=role_ids, note=None,
    )


def apply_member_roles(
    client: KfClient,
    target_flow_id: str,
    roles: dict[str, str],
    kind: FlowKind = "process",
) -> MemberReport | Err:
    """Grant AppRoles onto `target_flow_id`, CREATING each role scoped to KF_APP first if it does
    not already exist there. `roles` is `{role_id: display_name}` keyed by role id — BUT the real
    contract is name-driven: a role is matched/created by its display NAME and scoped to KF_APP.

    PROVEN live 2026-08-08: member/batch rejects any role NOT scoped to KF_APP with
    KISSFLOW_ERROR_00051 (even an account-wide role scoped to a different app), so simply re-granting
    a foreign role id is impossible. The route that unblocked this: `POST /app_role/2/{acct}`
    creates an AppRole scoped to KF_APP (CLAUDE.md's old "only the builder UI creates roles" was
    FALSE — corrected here). So this fn: for each name, reuse an existing KF_APP-scoped role with
    that name if one exists (idempotent), else create one, then grant all via member/batch.

    Grant is Role=DataAdmin, Permission=["InitiateItems"] (proven live 2026-08-07 as the grant that
    lets an initiator submit their own draft). `role_ids` in the report carries the KF_APP-scoped
    ids actually granted, so build_workflow can wire them as step assignees.
    """
    # Index existing KF_APP-scoped roles by Name for idempotent reuse.
    existing = client.list_app_roles(client._cfg.app_id)
    if isinstance(existing, Err):
        return existing
    by_name: dict[str, str] = {r.get("Name"): r.get("_id") for r in existing
                               if isinstance(r, dict) and r.get("Name") and r.get("_id")}

    resolved: dict[str, str] = {}  # role_id -> display name (all scoped to KF_APP)
    created: list[str] = []
    for _rid, name in roles.items():
        if name in by_name:
            resolved[by_name[name]] = name
            continue
        new_id = client.create_app_role(name)  # scoped to KF_APP by default
        if isinstance(new_id, Err):
            return new_id
        resolved[new_id] = name
        created.append(f"{name}={new_id}")

    members = [
        {"_id": rid, "Name": name, "Kind": "AppRole",
         "Role": _ACCOUNT_GRANT_ROLE, "Permission": list(_ACCOUNT_GRANT_PERMISSION)}
        for rid, name in resolved.items()
    ]
    role_ids = tuple(m["_id"] for m in members)
    names = tuple(m["Name"] for m in members)

    posted = client.post_member_batch(kind, target_flow_id, members)
    if isinstance(posted, Err):
        return posted

    # Read-back via list_app_roles (the flow /member roster lists USERS, not roles — CLAUDE.md
    # Members — so verify against the account role list instead: the role must exist scoped to
    # KF_APP, which is the load-bearing condition for a step assignee to bind).
    read_back = client.list_app_roles(client._cfg.app_id)
    if isinstance(read_back, Err):
        return read_back
    live_ids = {str(r.get("_id")) for r in read_back if isinstance(r, dict)}
    verified = tuple(r for r in role_ids if r in live_ids)
    missing = tuple(r for r in role_ids if r not in live_ids)

    note = f"granted {len(members)} KF_APP-scoped AppRole(s): {', '.join(names)}"
    if created:
        note += f"; created {len(created)} ({', '.join(created)})"
    return MemberReport(
        target_flow_id=target_flow_id, source_flow_id=None, harvested=names, applied=role_ids,
        verified=verified, missing=missing, role_ids=role_ids,
        resolved=tuple((name, rid) for rid, name in resolved.items()), note=note,
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


# =====================================================================================
# issue #55 surface additions below. Same shape as every apply_* above: GET/resolve -> offline
# mutate where applicable -> guarded PUT -> READ-BACK verify -> explicit output-invariant audit.
# =====================================================================================


def _role_write_body(detail: dict[str, Any]) -> dict[str, Any]:
    """Non-underscore keys off a `GET /app_role/.../{role_id}` detail, ready to PUT straight back.

    The write endpoint reuses the SAME record shape the read endpoint returns, but with one
    asymmetric key (proven live 2026-08-12, #52): it reads back under `Members` but must be
    WRITTEN under `Users` — a body that carries `Members` instead 200s and silently no-ops.
    `Members` is dropped from the body here and its entries carried over verbatim under `Users`,
    so a caller writing e.g. only `Preference` never accidentally wipes existing membership.
    """
    body = {k: v for k, v in detail.items() if not k.startswith("_")}
    members = body.pop("Members", None) or []
    body["Users"] = list(members)
    return body


@dataclass(frozen=True)
class RoleUsersReport:
    """Output-invariant audit for forge_add_role_users (#52): every candidate user lands in
    `added`, `already_present`, or `not_found` — never silently unaccounted for. `not_found`
    covers BOTH a `user_query` that matched zero real assignees and a candidate that was written
    but failed to verify on read-back (a real write failure, not folded into `already_present`)."""
    role_id: str
    added: tuple[str, ...]
    already_present: tuple[str, ...]
    not_found: tuple[str, ...]
    user_count: int | None

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id, "added": list(self.added),
            "already_present": list(self.already_present), "not_found": list(self.not_found),
            "user_count": self.user_count, "isError": bool(self.not_found),
        }


def apply_add_role_users(
    client: KfClient,
    role_id: str,
    user_query: str | None = None,
    user_ids: list[dict[str, Any]] | None = None,
    app_id: str | None = None,
) -> RoleUsersReport | Err:
    """Grant one or more users onto an AppRole (#52's assignee-lookup + asymmetric role-write).

    GET the role detail -> resolve candidate assignee objects (by `user_query` via
    `KfClient.get_assignee`, and/or `user_ids` — full assignee dicts `{_id, Kind, Email, Name}` a
    caller already resolved earlier, passed through verbatim) -> merge them onto the role's
    EXISTING `Members` (never drop current membership) -> ONE `put_app_role` write under the
    WRITE key `Users` -> read back and verify by `Members`/`UserCount`.

    Requires at least one of `user_query`/`user_ids`. A `user_query` with zero assignee matches
    is not a tool error on its own — it lands in `not_found`, the same "state it, never silently
    drop it" discipline as every other audit in this pack.
    """
    if user_query is None and not user_ids:
        return Err("verify", "apply_add_role_users: give user_query or user_ids")

    detail = client.get_app_role(role_id)
    if isinstance(detail, Err):
        return detail

    candidates: list[dict[str, Any]] = list(user_ids or [])
    not_found: list[str] = []
    if user_query is not None:
        found = client.get_assignee(user_query)
        if isinstance(found, Err):
            return found
        matched = [c for c in found if isinstance(c, dict) and c.get("_id")]
        if matched:
            candidates.extend(matched)
        else:
            not_found.append(user_query)

    existing_members = list(detail.get("Members") or [])
    existing_ids = {str(m.get("_id")) for m in existing_members if isinstance(m, dict)}
    already = tuple(str(c["_id"]) for c in candidates if str(c.get("_id")) in existing_ids)
    new_ones = [c for c in candidates if str(c.get("_id")) not in existing_ids]

    if not new_ones:
        return RoleUsersReport(role_id=role_id, added=(), already_present=already,
                               not_found=tuple(not_found), user_count=detail.get("UserCount"))

    body = _role_write_body(detail)
    body["Users"] = existing_members + new_ones

    written = client.put_app_role(role_id, body, app_id)
    if isinstance(written, Err):
        return written

    read_back = client.get_app_role(role_id)
    if isinstance(read_back, Err):
        return read_back
    live_ids = {str(m.get("_id")) for m in (read_back.get("Members") or []) if isinstance(m, dict)}
    added = tuple(str(c["_id"]) for c in new_ones if str(c["_id"]) in live_ids)
    unverified = tuple(str(c["_id"]) for c in new_ones if str(c["_id"]) not in live_ids)

    return RoleUsersReport(
        role_id=role_id, added=added, already_present=already,
        not_found=tuple(not_found) + unverified, user_count=read_back.get("UserCount"),
    )


# Tier -> (Role, Permission[]) wire map, FLOW-TYPE-DEPENDENT (shapes/app_role_grant.json note 0,
# browser-proven 2026-08-12). `None` means "No access" — a real removal route
# (`delete_member`), not a member/batch grant with an empty Permission (which is itself a
# genuine tier, "Initiate" on a process — CLAUDE.md's own war story about `Permission: []`
# 200ing while the initiator still can't submit is about a DIFFERENT gap, "InitiateItems"
# missing, not the SAME thing as "No access").
_TIER_MAP: dict[FlowKind, dict[str, tuple[str, tuple[str, ...]] | None]] = {
    "process": {
        "No access": None,
        "Initiate": ("Member", ()),
        "Manage": ("DataAdmin", ("InitiateItems",)),
    },
    "case": {
        "No access": None,
        "Read-only": ("Viewer", ()),
        "Initiate": ("Initiator", ()),
        "Edit": ("Member", ()),
        "Manage": ("Admin", ()),
    },
}


@dataclass(frozen=True)
class TierReport:
    flow_id: str
    kind: str
    role_id: str
    tier: str
    verified: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "kind": self.kind, "role_id": self.role_id,
            "tier": self.tier, "verified": self.verified, "isError": not self.verified,
        }


def apply_grant_tier(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    role_id: str,
    tier: str,
) -> TierReport | Err:
    """Grant an AppRole a named permission TIER on a flow (shapes/app_role_grant.json note 0):
    "No access" (a real removal — `DELETE .../member/{role_id}`, not a Permission:[] grant) up
    through "Manage", the FLOW-TYPE-DEPENDENT tier ladder (process: No access|Initiate|Manage;
    case adds Read-only|Edit). Unknown `(kind, tier)` combinations are refused loudly, naming the
    valid set, rather than guessing the nearest tier or role string.

    "No access" is verified by the role's ABSENCE from `get_members`'s read-back; every other
    tier is verified by the exact (Role, Permission[]) pair landing there.
    """
    by_tier = _TIER_MAP.get(kind)
    if by_tier is None:
        return Err("verify", f"forge_grant_tier: unknown kind {kind!r} — valid: {sorted(_TIER_MAP)}")
    if tier not in by_tier:
        return Err("verify", f"forge_grant_tier: unknown tier {tier!r} for kind {kind!r} — "
                             f"valid: {sorted(by_tier)}")

    mapped = by_tier[tier]
    if mapped is None:
        removed = client.delete_member(kind, flow_id, role_id)
        if isinstance(removed, Err):
            return removed
        read_back = client.get_members(kind, flow_id)
        if isinstance(read_back, Err):
            return read_back
        verified = not any(isinstance(m, dict) and str(m.get("_id")) == role_id for m in read_back)
        return TierReport(flow_id=flow_id, kind=kind, role_id=role_id, tier=tier, verified=verified)

    role_name, permission = mapped
    role_detail = client.get_app_role(role_id)
    if isinstance(role_detail, Err):
        return role_detail
    name = role_detail.get("Name")
    if not isinstance(name, str):
        return Err("verify", f"apply_grant_tier: role {role_id!r} has no resolvable Name")

    member = {"_id": role_id, "Name": name, "Kind": "AppRole", "Role": role_name,
             "Permission": list(permission)}
    posted = client.post_member_batch(kind, flow_id, [member])
    if isinstance(posted, Err):
        return posted

    read_back = client.get_members(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    verified = any(
        isinstance(m, dict) and str(m.get("_id")) == role_id and m.get("Role") == role_name
        and sorted(m.get("Permission") or []) == sorted(permission)
        for m in read_back
    )
    return TierReport(flow_id=flow_id, kind=kind, role_id=role_id, tier=tier, verified=verified)


_BORN_LIVE_KINDS = ("list", "dataset", "case")


@dataclass(frozen=True)
class FlowCreateReport:
    kind: str
    flow_id: str
    name: str
    status: str | None
    born_live: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "flow_id": self.flow_id, "name": self.name,
            "status": self.status, "born_live": self.born_live, "isError": not self.flow_id,
        }


def create_flow_any(
    client: KfClient,
    kind: str,
    name: str,
    extra: dict[str, Any] | None = None,
) -> FlowCreateReport | Err:
    """Unified create for every flowtype this engine can build from zero: process|form (start
    Draft, need a build sequence — see forge_create_process / kf_create_process), list|dataset
    (born LIVE, no publish step), case (born LIVE — REQUIRES `extra["item_type"]` +
    `extra["prefix"]`, refused loudly without them: `POST .../case` 400s MissingRequiredFieldError
    on either omission, shapes/board_case_skeleton.json).

    A thin dispatcher, not a new write path: every branch below calls the SAME KfClient method
    the kind-specific tools already use (`create_flow`, `apply_word_list`'s own `create_list`,
    `create_dataset`, `create_case`).
    """
    extra = extra or {}
    if kind in ("process", "form"):
        fid = client.create_flow(kind, name)  # type: ignore[arg-type]
        if isinstance(fid, Err):
            return fid
        return FlowCreateReport(kind=kind, flow_id=fid, name=name, status="Draft", born_live=False)

    if kind == "list":
        got = client.create_list(name)
        if isinstance(got, Err):
            return got
        return FlowCreateReport(kind=kind, flow_id=got.get("_id", ""), name=name,
                                status=got.get("Status"), born_live=True)

    if kind == "dataset":
        got = client.create_dataset(name)
        if isinstance(got, Err):
            return got
        return FlowCreateReport(kind=kind, flow_id=got.get("_id", ""), name=name,
                                status=got.get("Status"), born_live=True)

    if kind == "case":
        item_type = extra.get("item_type")
        prefix = extra.get("prefix")
        if not item_type or not prefix:
            return Err("verify",
                      "create_flow_any(kind='case') requires extra={'item_type': 'Board'|'Case', "
                      "'prefix': <2-4 char string>} — both are mandatory on the write API "
                      "(400 MissingRequiredFieldError without them)")
        got = client.create_case(name, item_type, prefix)
        if isinstance(got, Err):
            return got
        return FlowCreateReport(kind=kind, flow_id=got.get("_id", ""), name=name,
                                status=got.get("Status"), born_live=True)

    return Err("verify", f"create_flow_any: unknown kind {kind!r} — "
                         f"valid: process, form, list, dataset, case")
