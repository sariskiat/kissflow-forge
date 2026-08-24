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
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal

from .expr import build_branch_condition, build_goto_gate, remove_condition
from .graph import (
    NO_PERMISSION_NODETYPES,
    Matrix,
    _kind,
    _style_wire_value,
    add_field_validation,
    add_goto_task,
    add_sequence_number,
    add_table,
    apply_changes,
    apply_exact_layout,
    build_workflow,
    clone_template_shell,
    delete_closure,
    delete_nodes,
    ensure_process_def,
    field_delete_blockers,
    field_names,
    merge_groups,
    regroup_into_sections,
    rename_fields,
    section_layout,
    set_conditional_visibility,
    set_field_computed,
    set_field_events,
    set_required,
    set_section_style,
    set_step_permissions,
    transplant_template,
    validate_layout_spans,
)
from .types import (
    NO_EVENT_FIELD_TYPES,
    TRIGGER_LIVE_CONFIRMED,
    FieldSpec,
    FieldType,
    Visibility,
    trigger_for,
)
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
    def from_env(app_id_override: str | None = None) -> KfConfig | Err:
        # app_id_override (the per-call `app_id` every app-scoped tool accepts) wins over the
        # KF_APP env. There is no "select an app" tool and deliberately so — a server-side current
        # app would be shared state, and this surface is stateless by design (server.py header).
        # Empty app_id is allowed here on purpose — the "an app must be chosen" guard now lives at
        # the _client() chokepoint (server.py) so a tool carrying its own app_id, plus the
        # list/use-app tools, can run before any app is selected. See CLAUDE.md Members/Pages.
        try:
            domain = os.environ["KF_DEV_DOMAIN"]
            cfg = KfConfig(
                key_id=os.environ["KF_DEV_ACCESS_KEY_ID"],
                key_secret=os.environ["KF_DEV_ACCESS_KEY_SECRET"],
                account=os.environ["KF_DEV_ACCOUNT_ID"],
                domain=domain,
                app_id=(app_id_override or os.environ.get("KF_APP", "")),
            )
        except KeyError as e:
            return Err("config", f"missing env var {e.args[0]}")
        if "dev-" not in domain:
            return Err("config", f"refusing non-dev domain {domain!r}")
        return cfg

    @staticmethod
    def from_user(key_id: str, key_secret: str, app_id_override: str | None = None) -> KfConfig | Err:
        """Same config, but the ACCESS-KEY PAIR comes from the calling user (kfforge.auth carries
        it in over OAuth) instead of the process env. Domain and account stay env-side on purpose:
        the caller picks their own Kissflow identity, never the tenant, so the `dev-` refusal
        below is exactly as unskippable as it is in `from_env`."""
        try:
            domain = os.environ["KF_DEV_DOMAIN"]
            cfg = KfConfig(
                key_id=key_id,
                key_secret=key_secret,
                account=os.environ["KF_DEV_ACCOUNT_ID"],
                domain=domain,
                app_id=(app_id_override or os.environ.get("KF_APP", "")),
            )
        except KeyError as e:
            return Err("config", f"missing env var {e.args[0]}")
        if "dev-" not in domain:
            return Err("config", f"refusing non-dev domain {domain!r}")
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
    """What a live apply actually did — every field lands in exactly one bucket (output audit).

    Two axes, each a PARTITION of the requested records:
      * what we planned to do  — added | skipped | changed_ignored
      * what the read-back saw — verified | missing | changed_ignored

    `changed_ignored` is terminal on BOTH axes and is the only bucket that is neither a plan nor a
    read-back statement: the record exists live, so it is not `missing`, and it was not written,
    so it is not `verified` — the caller asked for something that did not happen. It used to be
    counted under `skipped` AND `verified` at once, which is how a silently-dropped type change
    read as a clean success (F2). See `_changed_ignored`.

    `collateral` is the OTHER half of the same honesty: what this write DESTROYED or MOVED that
    the caller never named. `remediation` is the machine-readable list of tool names the caller
    now owes because of it — never a rollback, just the damage made visible (A4).
    """
    flow_id: str
    added: tuple[str, ...]
    skipped: tuple[str, ...]      # already present AND identical -> idempotent no-op
    verified: tuple[str, ...]     # confirmed present by post-write read-back
    missing: tuple[str, ...]      # requested, written, but ABSENT on read-back -> loud failure
    changed_ignored: tuple[str, ...]  # present by name but DIFFERENT -> the change never happened
    collateral: tuple[str, ...]   # what this write destroyed/moved that the caller never named
    remediation: tuple[str, ...]  # tool names the caller now owes because of `collateral`
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "added": list(self.added),
            "skipped": list(self.skipped),
            "verified": list(self.verified),
            "missing": list(self.missing),
            "changed_ignored": list(self.changed_ignored),
            "collateral": list(self.collateral),
            "remediation": list(self.remediation),
            "meta_version": self.meta_version,
            "published": self.published,
            "isError": bool(self.missing or self.changed_ignored),
        }


class KfClient:
    """Thin verb wrapper over the builder API. One method per confirmed endpoint."""

    def __init__(self, cfg: KfConfig) -> None:
        self._cfg = cfg

    def scoped_to_app(self, app_id: str) -> "KfClient":
        """Re-scope the SAME caller identity (same access-key pair, same dev-guarded domain) to a
        different application. `KfConfig` is frozen, so this mints a new config rather than
        mutating the one in hand."""
        return KfClient(replace(self._cfg, app_id=app_id))

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
        # Scope match on EITHER signal: the `Applications[]` list OR the top-level `_application_id`
        # scalar (both are documented list-record keys). A role freshly created via `create_app_role`
        # (POST with `_application_id`) carries the scalar but may not populate `Applications[]` —
        # checking only the list dropped it, which made apply_member_roles create a DUPLICATE role
        # on re-run and read the just-granted role back as falsely `missing` (Cowork bug report
        # 2026-08-13; the scalar-only hypothesis is inferred from the symptom, live-recheck owed).
        return [r for r in out if isinstance(r, dict) and (
            r.get("_application_id") == app_id
            or any(isinstance(a, dict) and a.get("_id") == app_id
                   for a in (r.get("Applications") or [])))]

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
        # PERCENT-ENCODE the query. It is free caller text — a person's name — and this engine is
        # driven in Thai (kfforge.intake.questions is a Thai interview script), so a non-ASCII
        # query is the NORMAL case here, not an edge one. Interpolated raw, urllib.request encodes
        # the URL as ASCII and a Thai name dies with UnicodeEncodeError, which crosses the tool
        # boundary as an EXCEPTION rather than as data (doctrine: fail loud, but as `Err`). A
        # space or `&` in a name was equally broken, just more quietly — it truncated the query.
        # `safe=""` so `&`, `=`, `/` and `?` inside a name are escaped too, not treated as syntax.
        return self._json("GET", f"{c.base}/user/2/{c.account}/assignee"
                                 f"?q={urllib.parse.quote(query, safe='')}")

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

    def copilot_send(self, app_id: str, message: str) -> Any | Err:
        """Send a message to the in-builder AI copilot. Proven HEADLESS 2026-08-12 (the engine's
        own API token works, no browser/cookie/csrf needed):
        `POST /metadata/2/{acct}/ai/application/{app}/copilot/send?_application_id={app}` body
        `{"UserMessage": "..."}` -> `{status:success}` — an ACK, proves nothing about whether
        anything actually landed (THE RULE: never trust the reply, only a graph read-back)."""
        c = self._cfg
        return self._json(
            "POST",
            f"{c.base}/metadata/2/{c.account}/ai/application/{app_id}/copilot/send"
            f"?_application_id={app_id}",
            {"UserMessage": message},
        )

    def copilot_conversations(self, app_id: str) -> list[dict[str, Any]] | Err:
        """Read the copilot thread for `app_id`. Proven live 2026-08-12:
        `GET /metadata/2/{acct}/ai/application/{app}/copilot/conversations?_application_id={app}`
        -> newest-first array; pair `UserMessage`<->`SystemMessage` by `ConversationId`. Threads
        are server-side per-app and memory is FUZZY (a send occasionally fails to register)."""
        c = self._cfg
        return self._json(
            "GET",
            f"{c.base}/metadata/2/{c.account}/ai/application/{app_id}/copilot/conversations"
            f"?_application_id={app_id}",
        )

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

    def update_dataset_record(self, flow_id: str, record_id: str,
                              record: dict[str, Any]) -> dict[str, Any] | Err:
        """Partial-update ONE dataform record by its `_id`. Per-record route found in a prior
        probe (residuals_r1): `PUT /dataset/2/{acct}/{flow_id}?_id={rec}` body `{"<FieldId>": value,
        ...}` — a partial patch (only the keys sent change). Caller resolves field NAMES to ids
        before this call (see apply_dataset_records)."""
        c = self._cfg
        return self._json("PUT", f"{c.base}/dataset/2/{c.account}/{flow_id}"
                                 f"?_application_id={c.app_id}&_id={record_id}", record)

    def delete_dataset_record(self, flow_id: str, record_id: str,
                              name: str) -> dict[str, Any] | Err:
        """Delete ONE dataform record by its `_id`. Per-record route found in a prior probe
        (residuals_r1): `DELETE /dataset/2/{acct}/{flow_id}?_id={rec}` — the body MUST carry the
        record's synthetic system `{"Name": ...}` key (mandatory on this route)."""
        c = self._cfg
        return self._json("DELETE", f"{c.base}/dataset/2/{c.account}/{flow_id}"
                                    f"?_application_id={c.app_id}&_id={record_id}", {"Name": name})

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


@dataclass(frozen=True)
class ScaffoldInventory:
    """What a freshly scaffolded process ACTUALLY contains, read back off the live draft.

    `from_template=True` is the DEFAULT, and it silently injects a whole identity shell: on the
    2026-08-19 live run, four sections ("In-Kissflow Template", "Public Form Template", "Request
    Info", "System") and three Required fields ("Manager Display Name", "Requestor Employee Id
    Alt", "Department") the caller never asked for. The report was all empty tuples, so an
    `owners` map written against the caller's own design could not name sections it did not know
    existed — the visibility matrix was incomplete from the first write, and doctor only said so
    two steps later ("section 'System' is never editable at any live step", "field 'Department'
    is Required but never editable — that step cannot be submitted").
    """
    sections: tuple[str, ...]
    required_fields: tuple[str, ...]
    steps: tuple[str, ...]


def scaffold_inventory(draft: Draft) -> ScaffoldInventory:
    """Sections, Required root fields and workflow step names on `draft`. Pure, read-only.

    Sections are `Column{Type:"Section"}` by NAME — the exact population `forge_set_visibility`'s
    `owners` map has to cover. A table-host `Column{Type:"Model"}` is deliberately excluded: it is
    not a section a caller can own (CLAUDE.md > Tables). Steps exclude the nodes that render no
    form and take no Permission, so the list is exactly the set of names an `owners` VALUE may
    use — StartEvent and EndEvent included, since `Start` is a legal (and, for the first section,
    mandatory) owner. All three buckets are sorted: this is a set to cover, not a sequence to
    walk, and a stable order is what makes it diffable between runs.
    """
    sections = tuple(sorted(
        n for v in _kind(draft, "Column").values()
        if v.get("Type") == "Section" and isinstance(n := v.get("Name"), str) and n
    ))
    required = tuple(sorted(n for n, node in _root_field_nodes(draft).items()
                            if n and node.get("Required")))
    steps = tuple(sorted(
        n for a in _kind(draft, "Activity").values()
        if a.get("NodeType") not in NO_PERMISSION_NODETYPES
        and isinstance(n := a.get("Name"), str) and n
    ))
    return ScaffoldInventory(sections=sections, required_fields=required, steps=steps)


@dataclass(frozen=True)
class ProcessCreateReport(ApplyReport):
    """`ApplyReport` plus a statement of what the SCAFFOLD brought in that the caller never asked
    for (S4a). Every bucket of the base report is unchanged and still covers the caller's own
    `specs`; these three are about the OTHER content that is now on the flow.

    `template_read_error` exists so an unreadable read-back can never masquerade as an empty
    template: the buckets are honestly `()` and the error says why, rather than reporting a shell
    that brought in nothing.
    """
    from_template: bool = False
    template_sections: tuple[str, ...] = ()
    template_required_fields: tuple[str, ...] = ()
    template_steps: tuple[str, ...] = ()
    template_read_error: str | None = None

    def as_tool_result(self) -> dict[str, Any]:
        out = super().as_tool_result()
        out.update({
            "from_template": self.from_template,
            "template_sections": list(self.template_sections),
            "template_required_fields": list(self.template_required_fields),
            "template_steps": list(self.template_steps),
            "template_read_error": self.template_read_error,
        })
        if self.template_read_error:
            out["note"] = (f"could not read the scaffold back to inventory it: "
                           f"{self.template_read_error} — the three template_* buckets are empty "
                           f"because nothing was READ, not because the shell brought nothing in")
        elif self.from_template:
            out["note"] = (
                f"the process template shell brought in {len(self.template_sections)} section(s) "
                f"and {len(self.template_required_fields)} Required field(s) you did not ask for. "
                f"forge_set_visibility's `owners` must cover EVERY section listed above or that "
                f"section is editable at no step; a Required field that is never editable makes "
                f"its step permanently unsubmittable. Pass from_template=False for a bare shell."
            )
        return out


def create_process(
    client: KfClient,
    name: str,
    steps: tuple[str, ...],
    specs: list[FieldSpec],
    publish: bool = False,
    from_template: bool = True,
    template_path: str | None = None,
) -> ApplyReport | Err:
    """Create a PROCESS from zero: shell -> scaffold -> fields -> verify -> publish.

    `from_template=True` (the default, issue #59 — "every process starts from a structure-clone")
    scaffolds by CLONING the process-template identity shell (clone_template_shell:
    shapes/process_template_identity_shell.json, or KF_PROCESS_TEMPLATE / `template_path`) instead
    of the bare ensure_process_def skeleton — the identity/initiate field block, section/row/column
    layout, style chain, a "Manager Approve" UserTask, and Button::Row, all pre-built. `steps` is
    ignored in this path: the shell defines its own single step; rebuild the real workflow with
    build_workflow afterward if a different step set is needed. `from_template=False` falls back to
    the original bare scaffold, honoring `steps` as before.

    Either way the scaffold is mandatory, not decoration: a bare process draft is rejected with
    HTTP 500 until it has a ProcessDef (FINDINGS.md). On any failure after the shell exists, the
    half-built process is archived+deleted so a failed run leaves no junk behind in the tenant.

    The report STATES what the scaffold put on the flow — every section name, every Required
    field name, every step name — read back off the live draft, never off the template file
    (THE RULE: judge the read-back). See `ProcessCreateReport` for the live trap that motivates it.
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
        if from_template:
            scaffolded = clone_template_shell(draft, template_path)
        else:
            scaffolded = ensure_process_def(draft, steps)
    except ValueError as e:
        return _abandon(Err("verify", str(e)))

    written = client.put_draft("process", flow_id, scaffolded, expect_version=draft.get(_META_VERSION))
    if isinstance(written, Err):
        return _abandon(written)

    report = apply_fields(client, "process", flow_id, specs, publish=publish)
    if isinstance(report, Err):
        return _abandon(report)

    # One more READ, deliberately: `apply_fields` already read the draft back, but it reports only
    # the caller's own field specs and does not surface the graph. The scaffold's own content is
    # exactly what the caller cannot see and has to cover next, so it is read from the live flow
    # rather than derived from the template file that was sent.
    final = client.get_draft("process", flow_id)
    if isinstance(final, Err):
        inventory, read_error = ScaffoldInventory((), (), ()), final.message
    else:
        inventory, read_error = scaffold_inventory(final), None

    return ProcessCreateReport(
        flow_id=report.flow_id, added=report.added, skipped=report.skipped,
        verified=report.verified, missing=report.missing,
        changed_ignored=report.changed_ignored, collateral=report.collateral,
        remediation=report.remediation, meta_version=report.meta_version,
        published=report.published,
        from_template=from_template,
        template_sections=inventory.sections,
        template_required_fields=inventory.required_fields,
        template_steps=inventory.steps,
        template_read_error=read_error,
    )


def _permission_nodes(draft: Draft) -> list[tuple[str, dict[str, Any]]]:
    """(node id, node) for every Permission node in a graph, well-formed or not."""
    return [(k, v) for k, v in draft.items()
            if isinstance(v, dict) and v.get("Kind") == "Permission"]


def _permission_pairs(draft: Draft) -> dict[tuple[str, str], str]:
    """(column id, activity id) -> visibility, for every WELL-FORMED Permission node in a graph.

    A Permission node missing `Column` or `Activity` is not a pair and is SKIPPED, never a
    KeyError. This runs inside `apply_workflow`'s damage count — before any write — so an
    unguarded subscript here escapes forge_build_workflow as a bare traceback rather than as
    data, which is the one thing no function in this module is allowed to do. What is skipped is
    not swallowed: `_malformed_permissions` counts the same nodes by id, and every caller reports
    them, so a Permission node still lands in exactly one bucket.
    """
    return {
        (n["Column"], n["Activity"]): n.get("Permission", "")
        for _k, n in _permission_nodes(draft)
        if isinstance(n.get("Column"), str) and isinstance(n.get("Activity"), str)
    }


def _malformed_permissions(draft: Draft) -> tuple[str, ...]:
    """Node ids of every Permission that `_permission_pairs` could not read as a (column, step)
    pair — no `Column`, no `Activity`, or one of them not a string.

    Nothing in this engine mints one; a draft carrying one came from the builder UI, a template,
    or a half-applied write, and it is exactly the shape that used to KeyError the pair walk.
    Reported as collateral rather than refused: it is a pre-existing deviation the caller did not
    cause, and `verify.doctor` — not a write path — is where a draft is judged.
    """
    return tuple(sorted(
        k for k, n in _permission_nodes(draft)
        if not (isinstance(n.get("Column"), str) and isinstance(n.get("Activity"), str))
    ))


def _sequence_step_stamps(draft: Draft) -> dict[str, str | None]:
    """SequenceNumber field NAME -> the NAME of the activity its `Step` stamp points at.

    `None` means the stamp is DANGLING (the activity id it holds is not a node in this draft) —
    which is #18, THE deterministic publish-500: `Property{Name:"Step", Value:<activity id>}` is
    a SCALAR reference the list-only dangling sweep never touches. Reported by name, not by id,
    because a workflow rebuild changes every activity id — comparing ids across a rebuild would
    call every stamp "moved" whether it moved or not.
    """
    act_names = {k: v.get("Name") for k, v in draft.items()
                 if isinstance(v, dict) and v.get("Kind") == "Activity"}
    out: dict[str, str | None] = {}
    for node in draft.values():
        if not (isinstance(node, dict) and node.get("Kind") == "Field"
                and node.get("Type") == "SequenceNumber"):
            continue
        for pid in node.get("Field::Property") or []:
            prop = draft.get(pid) or {}
            if prop.get("Name") == "Step":
                out[node.get("Name", "")] = act_names.get(prop.get("Value"))
    return out


def _section_field_names(draft: Draft, section_name: str) -> tuple[str, ...]:
    """The field NAMES currently laid out in one section, in the section's own row/column order.

    Deliberately the SAME walk `graph.apply_exact_layout` does (`Column::Row` -> `Row::Column`)
    rather than draft insertion order, because it is that walk which decides what counts as a
    leftover — read it any other way and the collateral report describes a different set of
    fields than the one the rebuild actually moves. An unknown section name is `()`, not a raise:
    `apply_exact_layout` owns that refusal and states it better.
    """
    name_of_col = {n["Column"]: n.get("Name", "")
                   for n in draft.values()
                   if isinstance(n, dict) and n.get("Kind") == "Field"
                   and isinstance(n.get("Column"), str)}
    sid = next((k for k, v in draft.items()
                if isinstance(v, dict) and v.get("Kind") == "Column"
                and v.get("Type") == "Section" and v.get("Name") == section_name), None)
    if sid is None:
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for rid in draft[sid].get("Column::Row") or []:
        for cid in (draft.get(rid) or {}).get("Row::Column") or []:
            if cid in name_of_col and cid not in seen:
                seen.add(cid)
                out.append(name_of_col[cid])
    return tuple(out)


def _field_placements(draft: Draft) -> dict[str, tuple[str, int, int, int]]:
    """field NAME -> (section title, row index within that section, Start, End) — where the field
    actually sits on the 6-unit form grid.

    The fact base for the layout collateral `regroup_into_sections` owes its callers. That
    transform is a REBUILD, not a patch: it drops every Row above the Field/Column layer and
    re-tiles every section at a uniform `FIELD_SPAN`, in `merge_groups`' order. So a custom grid
    an earlier `forge_apply_layout` wrote — `[[0-3, 3-6], [0-6], [0-6]]` — comes back
    `[[0-2, 2-4, 4-6], [0-2, 2-4]]`: nothing is lost (the Field and Column nodes, their ids and
    their Permission/Event back-refs all survive), but every pre-existing field MOVED, and the
    form the user sees is not the one they laid out.

    Recurses through nested wrapper Columns (a template's Grid, or whatever the builder invents
    next) the way `graph.current_groups` does, and reports the LEAF column's own Start/End — a
    template-cloned field really does move when the regroup flattens its Grid away, and reporting
    the wrapper's coordinates would hide exactly that. The row index stays the SECTION's own row,
    the wrapper's, so two fields inside one Grid can share a row index at different depths; that
    is an approximation only INSIDE a wrapper, and it never hides a move (flattening changes the
    leaf Start/End too). A field in no section at all is absent from the map rather than given a
    fake placement, and a name is recorded once — its first placement in section order.
    """
    name_of_col = {n["Column"]: n.get("Name", "")
                   for n in draft.values()
                   if isinstance(n, dict) and n.get("Kind") == "Field"
                   and isinstance(n.get("Column"), str)}

    def _leaves(row_ids: list[str], title: str, ri: int, out: dict[str, tuple[str, int, int, int]]) -> None:
        for rid in row_ids:
            for cid in (draft.get(rid) or {}).get("Row::Column") or []:
                col = draft.get(cid) or {}
                if cid in name_of_col:
                    out.setdefault(name_of_col[cid],
                                   (title, ri, int(col.get("Start", 0)), int(col.get("End", 0))))
                elif col.get("Column::Row"):
                    _leaves(list(col["Column::Row"]), title, ri, out)

    out: dict[str, tuple[str, int, int, int]] = {}
    for sec in draft.values():
        if not (isinstance(sec, dict) and sec.get("Kind") == "Column"
                and sec.get("Type") == "Section"):
            continue
        title = sec.get("Name", "")
        for ri, rid in enumerate(sec.get("Column::Row") or []):
            _leaves([rid], title, ri, out)
    return out


def _layout_collateral(before: Draft, after: Draft, exclude: Iterable[str] = ()) -> tuple[str, ...]:
    """Every field whose grid placement CHANGED across a write, named with both coordinates.

    Counted on the real read-back against the pre-write draft, never on the offline graph — a
    count taken from what we hoped to write would prove nothing (same rule `apply_workflow`'s
    `permissions_deleted` follows). `exclude` is the names this call ADDED: a field that did not
    exist before did not move, and calling it collateral would drown the real signal.

    A field that was placed before and is in NO section afterwards is reported too — that is a
    field dropped off the form entirely, which no bucket here would otherwise carry.
    """
    was = _field_placements(before)
    now = _field_placements(after)
    skip = set(exclude)
    out: list[str] = []
    for name in sorted(was):
        if name in skip or was[name] == now.get(name):
            continue
        if name not in now:
            out.append(f"{name!r} was laid out in section {was[name][0]!r} and is now in no "
                       "section at all — the rebuild dropped it off the form")
            continue
        (ws, wr, wa, wb), (ns, nr, na, nb) = was[name], now[name]
        out.append(f"{name!r} moved: {ws!r} row {wr} cols {wa}-{wb} -> {ns!r} row {nr} "
                   f"cols {na}-{nb} — regroup_into_sections re-tiles every section at a uniform "
                   "width, so any custom grid an earlier forge_apply_layout wrote is gone")
    return tuple(out)


def _field_nodes_by_name(draft: Draft) -> dict[str, list[dict[str, Any]]]:
    """field NAME -> every live Field node carrying it. A LIST, not one node: names are not
    unique across a form and its child tables (CLAUDE.md Tables), and `graph.apply_changes`
    matches against `field_names(draft)`, which is exactly this key set."""
    out: dict[str, list[dict[str, Any]]] = {}
    for node in draft.values():
        if isinstance(node, dict) and node.get("Kind") == "Field":
            out.setdefault(node.get("Name", ""), []).append(node)
    return out


def _spec_diff(spec: FieldSpec, node: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """(attribute, requested, live) for every way `spec` disagrees with one live Field node.

    Compares ONLY what a caller actually stated: Type and Required always (both are on every
    FieldSpec), `ReferredList` and each `options` key only when the caller named them. A blind
    key-by-key diff would flag every Number field, because `graph._TYPE_DEFAULTS` writes keys
    (`Decimalpoint`, `DefaultValue`) no FieldSpec ever mentions.
    """
    diffs: list[tuple[str, Any, Any]] = []
    want_type = FieldType(spec.type).value
    if node.get("Type") != want_type:
        diffs.append(("Type", want_type, node.get("Type")))
    if bool(node.get("Required", False)) != bool(spec.required):
        diffs.append(("Required", bool(spec.required), bool(node.get("Required", False))))
    if spec.referred_list is not None and node.get("ReferredList") != spec.referred_list:
        diffs.append(("ReferredList", spec.referred_list, node.get("ReferredList")))
    for key, value in (spec.options or {}).items():
        if key in _RELOCATED_OPTION_KEYS:
            continue  # see _RELOCATED_OPTION_KEYS — not on the Field node by design
        if node.get(key) != value:
            diffs.append((key, value, node.get(key)))
    return diffs


# `options` keys the offline builder deliberately moves OFF the Field node onto a sibling in the
# field's configuration cluster. Diffing them against the Field node reads `None` on a field that
# was written exactly as asked, so a re-apply — which CLAUDE.md and every apply_* docstring
# promise is idempotent — would report the field as changed-and-ignored and advise deleting it.
# `LHSModel` is the proven case: graph.apply_changes pops it off the Field and writes it to the
# User field's mandatory `QueryDefinition` sibling (graph.py, "it belongs on the QueryDefinition,
# so it must NOT stay on the Field node"). Add a key here only with the graph-side pop to cite.
_RELOCATED_OPTION_KEYS = frozenset({"LHSModel"})


@dataclass(frozen=True)
class _IgnoredChanges:
    """The F2 fact base: which requested specs the create-only apply path silently drops."""
    entries: tuple[str, ...]      # one loud sentence per record, for the report bucket
    names: frozenset[str]         # the same records by NAME, so the other buckets can exclude them
    remediation: tuple[str, ...]  # tool names that CAN make the requested change happen


def _changed_ignored(draft: Draft, specs: list[FieldSpec]) -> _IgnoredChanges:
    """The F2 bucket: every requested spec that matched a live field BY NAME but asked for
    something different from what is actually there.

    `graph.apply_changes` only ever CREATES — a spec whose name already exists is skipped
    outright, and a spec carrying a `field_id` raises NotImplementedError. So requesting a
    different Type or Required flag for an EXISTING name is a silent no-op that used to be
    counted under `skipped` and `verified` at once, reporting success for a change that never
    happened. Naming it here is doctrine: the record was landing in the wrong bucket.

    A name matching several Field nodes (a form field and a table child can share one) counts as
    satisfied when ANY of them already matches the spec — that is the same "already present"
    apply_changes itself sees — and otherwise reports every live candidate, so the caller can
    tell which node it actually collided with.
    """
    live = _field_nodes_by_name(draft)
    entries: list[str] = []
    names: list[str] = []
    remediation: list[str] = []
    for spec in specs:
        nodes = live.get(spec.name)
        if not nodes:
            continue                                   # a real create — apply_changes will add it
        per_node = [_spec_diff(spec, n) for n in nodes]
        if any(not d for d in per_node):
            continue                                   # one live node already matches -> skipped
        attrs = {a for diffs in per_node for a, _w, _l in diffs}
        want = ", ".join(f"{a}={w!r}" for a, w, _l in per_node[0])
        seen = ", ".join(
            " ".join(f"{a}={live_v!r}" for a, _w, live_v in diffs) for diffs in per_node
        )
        entries.append(f"{spec.name}: requested {want}, live {seen} — NOT applied "
                       "(apply_changes only creates; an existing name is never edited)")
        names.append(spec.name)
        # what the caller can actually DO about it: a Required flag has its own live op, a Type
        # change has none — the field has to go and come back.
        if attrs == {"Required"}:
            remediation.append("forge_set_required")
        else:
            remediation.extend(("forge_delete_fields", "forge_apply_fields"))
    return _IgnoredChanges(tuple(entries), frozenset(names), tuple(dict.fromkeys(remediation)))


@dataclass(frozen=True)
class _PairNames:
    """Id -> human NAME resolution for one draft's (column, activity) permission pairs.

    The audit unit of `apply_step_permissions` is `Column_13Hw6YCM9B@Activity_3c29a1abe0`, which
    is unreadable to the agent that has to act on it — 222 such strings, listed twice, were
    measured at ~15k tokens for ONE call that conveyed "222 pairs written, 0 missing". Names cost
    one extra walk of a draft this function already holds.
    """
    field_of_column: dict[str, str]
    section_of_column: dict[str, str]
    step_of_activity: dict[str, str]

    def column(self, cid: str) -> str:
        return self.field_of_column.get(cid, cid)

    def section(self, cid: str) -> str:
        return self.section_of_column.get(cid, "(no section)")

    def step(self, aid: str) -> str:
        return self.step_of_activity.get(aid, aid)

    def pair(self, cid: str, aid: str) -> str:
        """`Intake / Ticket No @ Ticket arrives` — the section, the field, the step. Falls back to
        the raw id for anything that does not resolve, so nothing is ever silently unnameable."""
        return f"{self.section(cid)} / {self.column(cid)} @ {self.step(aid)}"


def _pair_names(draft: Draft) -> _PairNames:
    """Resolve every column and activity id in `draft` to the name a human uses for it. Pure."""
    layout = section_layout(draft)
    cols = _kind(draft, "Column")
    field_of_column: dict[str, str] = {}
    for f in _kind(draft, "Field").values():
        cid, fname = f.get("Column"), f.get("Name")
        if isinstance(cid, str) and isinstance(fname, str):
            field_of_column[cid] = fname
    # a SECTION column is itself a legal Permission target (CLAUDE.md Visibility: "Column may be a
    # SECTION column") and carries its own Name — a field column carries None, hence the walk above
    for cid, col in cols.items():
        if cid not in field_of_column and isinstance(col.get("Name"), str):
            field_of_column[cid] = col["Name"]
    section_of_column = {cid: s for cid in cols if (s := layout.owner_section(cid)) is not None}
    step_of_activity = {aid: n for aid, a in _kind(draft, "Activity").items()
                        if isinstance(n := a.get("Name"), str)}
    return _PairNames(field_of_column, section_of_column, step_of_activity)


def _uncovered_sections(draft: Draft, matrix: Matrix, field_matrix: Matrix | None) -> tuple[str, ...]:
    """Every section on the form that this matrix leaves editable at NO step (S4b).

    The trap this exists for, hit live: `forge_create_process(from_template=True)` — the DEFAULT —
    injects four sections the caller never asked for, so an `owners` map written against the
    caller's own design cannot name them. progressive_matrix maps an unnamed section to ReadOnly
    everywhere, which writes cleanly and publishes, and the gap only surfaces two steps later as
    doctor's "section 'System' is never editable at any live step". Stating it here surfaces it on
    the FIRST call.

    Deliberately NOT folded into `isError` — a caller may legitimately leave a section alone. This
    mirrors `forge_set_branch_conditions`' `uncovered` (the fail-open switch hazard): stated so it
    is never discovered later, never an error on its own.

    Two exclusions, both to keep it free of false positives:
      * a section covered by a FIELD-level override — `field_matrix` expresses editability per
        field, so a section that only HIDES is fully intentional and is not uncovered;
      * a section that governs no permissionable column at all (an empty banner Section above a
        table, a table-host Model column) — there is nothing there to cover.
    """
    layout = section_layout(draft)
    editable_cols: set[str] = set()
    for fname, row in (field_matrix or {}).items():
        for f in _kind(draft, "Field").values():
            if f.get("Name") == fname and isinstance(f.get("Column"), str) \
                    and any(Visibility(v) is Visibility.EDITABLE for v in row.values()):
                editable_cols.add(f["Column"])
    covered_by_field = {s for cid in editable_cols if (s := layout.owner_section(cid)) is not None}

    out: list[str] = []
    for name, row in matrix.items():
        if any(Visibility(v) is Visibility.EDITABLE for v in row.values()):
            continue
        if name in covered_by_field:
            continue
        sid = layout.section_id_of_name.get(name)
        governed = [c for c in layout.members.get(sid or "", ())
                    if c not in layout.no_permission_columns
                    and c not in layout.table_host_columns
                    and c not in layout.table_child_columns]
        if not governed:
            continue
        out.append(name)
    return tuple(sorted(out))


@dataclass(frozen=True)
class StepPermissionReport(ApplyReport):
    """`ApplyReport` with the (column, activity) pair audit kept WHOLE and its PRESENTATION bounded.

    The audit is unchanged and must stay that way (doctrine 2): every pair still lands in exactly
    one of added / skipped / verified / missing, and those tuples are still complete on the
    dataclass. What changed is `as_tool_result`: one live `forge_set_visibility` call over 37
    columns x 6 activities emitted all 222 pairs TWICE (once under `added`, once under `verified`),
    every entry an opaque `Column_13Hw6YCM9B@Activity_3c29a1abe0` with no field or step name
    anywhere — ~15k tokens to convey "222 pairs written, 0 missing".

    The default payload states COUNTS plus the names that actually matter:
      * `missing` in FULL, resolved to names — it is the failure bucket and is never summarised;
      * `by_section` / `by_step` — one line each, so a caller can see WHERE the work landed;
      * `uncovered_sections` — S4b, see `_uncovered_sections`;
      * `summarised` + `note` — exactly how many entries the counts stand in for, so nothing is
        ever silently withheld ("no silent caps"), and the parameter that returns them.
    Pass `include_pairs=True` (forge_set_visibility / kf_set_step_visibility take it through) and
    the full lists come back under `pairs`, named, alongside everything above.
    """
    by_section: tuple[str, ...] = ()
    by_step: tuple[str, ...] = ()
    uncovered_sections: tuple[str, ...] = ()
    missing_named: tuple[str, ...] = ()
    added_named: tuple[str, ...] = ()
    skipped_named: tuple[str, ...] = ()
    verified_named: tuple[str, ...] = ()
    include_pairs: bool = False

    def as_tool_result(self) -> dict[str, Any]:
        summarised = len(self.added) + len(self.skipped) + len(self.verified) + len(self.collateral)
        out: dict[str, Any] = {
            "flow_id": self.flow_id,
            "pair_counts": {
                "added": len(self.added), "skipped": len(self.skipped),
                "verified": len(self.verified), "missing": len(self.missing),
                "collateral": len(self.collateral),
            },
            "missing": list(self.missing_named),
            "by_section": list(self.by_section),
            "by_step": list(self.by_step),
            "uncovered_sections": list(self.uncovered_sections),
            "remediation": list(self.remediation),
            "summarised": 0 if self.include_pairs else summarised,
            "meta_version": self.meta_version,
            "published": self.published,
            "isError": bool(self.missing),
        }
        if self.include_pairs:
            out["pairs"] = {
                "added": list(self.added_named), "skipped": list(self.skipped_named),
                "verified": list(self.verified_named), "missing": list(self.missing_named),
            }
            out["collateral"] = list(self.collateral)
            out["note"] = (f"{summarised} pair entries listed in full (include_pairs=True). "
                           f"`missing` is always listed in full either way.")
        else:
            out["note"] = (
                f"{summarised} pair entries summarised into `pair_counts` / `by_section` / "
                f"`by_step` — nothing was dropped; re-run with include_pairs=true for the full "
                f"(column, activity) list. `missing` is ALWAYS listed in full and is empty here."
                if not self.missing else
                f"{summarised} written/skipped/verified/collateral entries summarised into "
                f"`pair_counts` / `by_section` / `by_step`; the {len(self.missing)} FAILED pairs "
                f"are listed in full above. Re-run with include_pairs=true for everything."
            )
        return out


def _permission_rollup(pairs: Iterable[tuple[str, str]], names: _PairNames,
                       verified: set[tuple[str, str]], missing: set[tuple[str, str]],
                       by: str) -> tuple[str, ...]:
    """One summary line per section (`by="section"`) or per step (`by="step"`) over `pairs`.

    Counts are derived FROM the same pair sets the audit uses, never tracked alongside them, so
    the rollup can never disagree with `pair_counts` (the same rule `BuildPlan.summary` follows).
    """
    buckets: dict[str, list[int]] = {}
    for cid, aid in pairs:
        key = names.section(cid) if by == "section" else names.step(aid)
        row = buckets.setdefault(key, [0, 0, 0])
        row[0] += 1
        row[1] += (cid, aid) in verified
        row[2] += (cid, aid) in missing
    return tuple(f"{key}: {n} pair(s) written, {ok} verified, {bad} missing"
                 for key, (n, ok, bad) in sorted(buckets.items()))


@dataclass(frozen=True)
class _StepPermissionDeltas:
    added: tuple[str, ...]
    skipped: tuple[str, ...]
    added_named: tuple[str, ...]
    skipped_named: tuple[str, ...]


@dataclass(frozen=True)
class _StepPermissionAudit:
    verified_pairs: set[tuple[str, str]]
    missing_pairs: set[tuple[str, str]]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    missing_named: tuple[str, ...]
    verified_named: tuple[str, ...]


def _format_pairs(pairs: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(sorted(f"{c}@{a}" for c, a in pairs))


def _format_named_pairs(names: _PairNames, pairs: Iterable[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(sorted(names.pair(c, a) for c, a in pairs))


def _prepare_step_permissions(
    draft: Draft,
    matrix: Matrix,
    field_matrix: Matrix | None,
) -> Draft | Err:
    try:
        return set_step_permissions(draft, matrix, field_matrix)
    except ValueError as e:
        return Err("verify", f"offline apply rejected the matrix: {e}")


def _fetch_and_prepare_step_permissions(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    matrix: Matrix,
    field_matrix: Matrix | None,
) -> tuple[Draft, Draft] | Err:
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    new = _prepare_step_permissions(draft, matrix, field_matrix)
    if isinstance(new, Err):
        return new
    return draft, new


def _put_and_read_back_draft(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    new: Draft,
    version: Any,
) -> Draft | Err:
    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written
    return client.get_draft(kind, flow_id)


def _malformed_permission_collateral(draft: Draft) -> tuple[str, ...]:
    return tuple(
        f"deleted malformed Permission {nid} (no readable Column/Activity pair) — it was never "
        "in the before-matrix and no rebuilt pair replaces it"
        for nid in _malformed_permissions(draft)
    )


def _step_permission_collateral(
    draft: Draft,
    before: dict[tuple[str, str], str],
    wanted: dict[tuple[str, str], str],
    names: _PairNames,
) -> tuple[str, ...]:
    dropped: list[str] = []
    for (c, a), v in before.items():
        if (c, a) not in wanted:
            dropped.append(
                f"deleted Permission {c}@{a} ({names.pair(c, a)}) (was {v!r}) — the rebuild covers this "
                "pair no longer"
            )
    return tuple(sorted(dropped)) + _malformed_permission_collateral(draft)


def _step_permission_deltas(
    before: dict[tuple[str, str], str],
    wanted: dict[tuple[str, str], str],
    names: _PairNames,
) -> _StepPermissionDeltas:
    added_pairs: list[tuple[str, str]] = []
    skipped_pairs: list[tuple[str, str]] = []
    for pair, v in wanted.items():
        if before.get(pair) == v:
            skipped_pairs.append(pair)
        else:
            added_pairs.append(pair)
    return _StepPermissionDeltas(
        added=_format_pairs(added_pairs),
        skipped=_format_pairs(skipped_pairs),
        added_named=_format_named_pairs(names, added_pairs),
        skipped_named=_format_named_pairs(names, skipped_pairs),
    )


def _audit_step_permissions(
    wanted: dict[tuple[str, str], str],
    live: dict[tuple[str, str], str],
    names: _PairNames,
) -> _StepPermissionAudit:
    verified_pairs: set[tuple[str, str]] = set()
    missing_pairs: set[tuple[str, str]] = set()
    for pair, v in wanted.items():
        if live.get(pair) == v:
            verified_pairs.add(pair)
        else:
            missing_pairs.add(pair)
    return _StepPermissionAudit(
        verified_pairs=verified_pairs,
        missing_pairs=missing_pairs,
        verified=_format_pairs(verified_pairs),
        missing=_format_pairs(missing_pairs),
        missing_named=_format_named_pairs(names, missing_pairs),
        verified_named=_format_named_pairs(names, verified_pairs),
    )


def _publish_flow(client: KfClient, kind: FlowKind, flow_id: str) -> bool | Err:
    pub = client.publish(kind, flow_id)
    if isinstance(pub, Err):
        return pub
    return True


def _publish_if_clean(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    publish: bool,
    missing: tuple[str, ...],
) -> bool | Err:
    if publish and not missing:
        return _publish_flow(client, kind, flow_id)
    return False


def _assemble_step_permission_report(
    flow_id: str,
    draft: Draft,
    read_back: Draft,
    matrix: Matrix,
    field_matrix: Matrix | None,
    names: _PairNames,
    wanted: dict[tuple[str, str], str],
    audit: _StepPermissionAudit,
    published: bool,
    include_pairs: bool,
) -> StepPermissionReport:
    before = _permission_pairs(draft)
    deltas = _step_permission_deltas(before, wanted, names)
    collateral = _step_permission_collateral(draft, before, wanted, names)
    remediation = ("forge_set_visibility",) if collateral else ()
    return StepPermissionReport(
        flow_id=flow_id,
        added=deltas.added,
        skipped=deltas.skipped,
        verified=audit.verified,
        missing=audit.missing,
        changed_ignored=(),
        collateral=collateral,
        remediation=remediation,
        meta_version=read_back.get(_META_VERSION),
        published=published,
        by_section=_permission_rollup(wanted, names, audit.verified_pairs, audit.missing_pairs, "section"),
        by_step=_permission_rollup(wanted, names, audit.verified_pairs, audit.missing_pairs, "step"),
        uncovered_sections=_uncovered_sections(draft, matrix, field_matrix),
        missing_named=audit.missing_named,
        added_named=deltas.added_named,
        skipped_named=deltas.skipped_named,
        verified_named=audit.verified_named,
        include_pairs=include_pairs,
    )


def _publish_and_assemble_step_permissions(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    draft: Draft,
    read_back: Draft,
    matrix: Matrix,
    field_matrix: Matrix | None,
    names: _PairNames,
    wanted: dict[tuple[str, str], str],
    audit: _StepPermissionAudit,
    publish: bool,
    include_pairs: bool,
) -> StepPermissionReport | Err:
    published = _publish_if_clean(client, kind, flow_id, publish, audit.missing)
    if isinstance(published, Err):
        return published
    return _assemble_step_permission_report(
        flow_id=flow_id,
        draft=draft,
        read_back=read_back,
        matrix=matrix,
        field_matrix=field_matrix,
        names=names,
        wanted=wanted,
        audit=audit,
        published=published,
        include_pairs=include_pairs,
    )


def apply_step_permissions(
    client: KfClient,
    flow_id: str,
    matrix: Matrix,
    publish: bool = False,
    kind: FlowKind = "process",
    field_matrix: Matrix | None = None,
    include_pairs: bool = False,
) -> StepPermissionReport | Err:
    """Rebuild a process's per-step visibility matrix live. GET -> apply offline -> guarded PUT
    -> read-back audit -> optional publish.

    The audit unit is one (column, activity) PAIR, not a field: every pair we intended to write is
    reported as verified or `missing`, so a partially-applied matrix can never read as success.
    `skipped` counts pairs that already carried the exact visibility we wanted (idempotent re-run).

    DESTRUCTIVE (A4): `graph.set_step_permissions` DELETES every existing Permission node before
    it writes — it rebuilds the matrix, it does not merge into it. A pair that was live before and
    is not in the new matrix is therefore gone, and used to be absent from every counted bucket.
    It is now reported in `collateral`, with its old visibility, so a matrix that quietly stopped
    covering a column is visible in the audit instead of being discovered at render time.

    The RESULT is bounded, the AUDIT is not: `include_pairs=False` (the default) returns counts,
    per-section/per-step rollups, every `missing` pair in full, and a `summarised` count of what
    the rollups stand in for. See `StepPermissionReport` for why, and what `include_pairs=True`
    adds back.
    """
    prep = _fetch_and_prepare_step_permissions(client, kind, flow_id, matrix, field_matrix)
    if isinstance(prep, Err):
        return prep
    draft, new = prep
    wanted = _permission_pairs(new)
    read_back = _put_and_read_back_draft(client, kind, flow_id, new, draft.get(_META_VERSION))
    if isinstance(read_back, Err):
        return read_back

    names = _pair_names(draft)
    live = _permission_pairs(read_back)
    audit = _audit_step_permissions(wanted, live, names)

    return _publish_and_assemble_step_permissions(
        client=client,
        kind=kind,
        flow_id=flow_id,
        draft=draft,
        read_back=read_back,
        matrix=matrix,
        field_matrix=field_matrix,
        names=names,
        wanted=wanted,
        audit=audit,
        publish=publish,
        include_pairs=include_pairs,
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

    A name that already exists but whose spec DIFFERS (a different Type, Required flag,
    ReferredList or stated option) is not idempotent and is not a success: `graph.apply_changes`
    only creates, so nothing happens at all. Those land in `changed_ignored`, which sets
    `isError` — see `_changed_ignored`.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft

    before = field_names(draft)
    version = draft.get(_META_VERSION)
    requested = [s.name for s in specs]
    ignored = _changed_ignored(draft, specs)
    skipped = tuple(n for n in requested if n in before and n not in ignored.names)

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
    verified = tuple(n for n in requested if n in live_names and n not in ignored.names)
    missing = tuple(n for n in requested if n not in live_names)

    published = False
    if publish and not (missing or ignored.entries):
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
        changed_ignored=ignored.entries,
        collateral=(),
        remediation=ignored.remediation,
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


def _transform_fields_and_layout(
    draft: Draft,
    specs: list[FieldSpec],
    groups: list[tuple[str, list[str]]] | None,
) -> Draft | Err:
    try:
        new = apply_changes(draft, specs)
        if groups:
            return regroup_into_sections(new, merge_groups(new, groups))
        return new
    except (ValueError, NotImplementedError) as e:
        return Err("verify", f"offline apply rejected the change set: {e}")


def _write_fields_and_layout_draft(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    draft: Draft,
    new: Draft,
    added: tuple[str, ...],
    groups: list[tuple[str, list[str]]] | None,
) -> Draft | None | Err:
    if not (added or groups):
        return None
    return client.put_draft(kind, flow_id, new, expect_version=draft.get(_META_VERSION))


def _partition_names(
    names: list[str],
    present: set[str],
    excluded: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    in_bucket: list[str] = []
    out_bucket: list[str] = []
    for n in names:
        if n not in present:
            out_bucket.append(n)
        elif n not in excluded:
            in_bucket.append(n)
    return tuple(in_bucket), tuple(out_bucket)


def _publish_fields_and_layout(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    publish: bool,
    can_publish: bool,
) -> bool | Err:
    if not (publish and can_publish):
        return False
    pub = client.publish(kind, flow_id)
    return pub if isinstance(pub, Err) else True


def _build_apply_fields_report(
    flow_id: str,
    draft: Draft,
    read_back: Draft,
    ignored: _IgnoredChanges,
    added: tuple[str, ...],
    skipped: tuple[str, ...],
    verified: tuple[str, ...],
    missing: tuple[str, ...],
    published: bool,
) -> ApplyReport:
    collateral = _layout_collateral(draft, read_back, exclude=added)
    remediation = ignored.remediation + (("forge_apply_layout",) if collateral else ())
    return ApplyReport(
        flow_id=flow_id,
        added=added,
        skipped=skipped,
        verified=verified,
        missing=missing,
        changed_ignored=ignored.entries,
        collateral=collateral,
        remediation=remediation,
        meta_version=read_back.get(_META_VERSION),
        published=published,
    )


def _prepare_fields_and_layout(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    specs: list[FieldSpec],
    groups: list[tuple[str, list[str]]] | None,
) -> tuple[Draft, Draft] | Err:
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    new = _transform_fields_and_layout(draft, specs, groups)
    if isinstance(new, Err):
        return new
    return draft, new


def _sync_fields_and_layout(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    draft: Draft,
    new: Draft,
    added: tuple[str, ...],
    groups: list[tuple[str, list[str]]] | None,
) -> Draft | Err:
    written = _write_fields_and_layout_draft(
        client, kind, flow_id, draft, new, added, groups
    )
    if isinstance(written, Err):
        return written
    return client.get_draft(kind, flow_id)


def _finalize_fields_and_layout(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    draft: Draft,
    read_back: Draft,
    specs: list[FieldSpec],
    ignored: _IgnoredChanges,
    added: tuple[str, ...],
    skipped: tuple[str, ...],
    publish: bool,
) -> ApplyReport | Err:
    live_names = field_names(read_back)
    req_names = [s.name for s in specs]
    verified, missing = _partition_names(req_names, live_names, ignored.names)
    can_pub = not (missing or ignored.entries)
    published = _publish_fields_and_layout(client, kind, flow_id, publish, can_pub)
    if isinstance(published, Err):
        return published
    return _build_apply_fields_report(
        flow_id, draft, read_back, ignored, added, skipped, verified, missing, published
    )


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
    half-laid-out between two separate PUTs. `groups` is a PARTIAL `(section title, [field
    names])` list: it is overlaid onto the draft's CURRENT section membership via
    `graph.merge_groups` before the rebuild, so a field the caller doesn't name keeps its
    current section instead of collapsing into `regroup_into_sections`'s own "Other" catch-all —
    the common "add one field to an existing section" call used to dump every OTHER field already
    in that section (all of them, on a template-cloned process) into "Other".

    Unlike plain `apply_fields` (which skips the PUT entirely when every requested field already
    exists — a genuine no-op), this ALWAYS writes when `groups` is given: a re-layout is a real
    change even with zero new fields, and silently skipping it would leave sections wherever an
    earlier write left them.

    Collateral (A4): the regroup is a REBUILD — it re-tiles every section at a uniform width, so a
    custom grid an earlier `forge_apply_layout` wrote is destroyed by a call that only meant to add
    one field. Every pre-existing field whose placement actually moved is named in `collateral`,
    measured on the read-back against the pre-write draft (`_layout_collateral`), with
    `forge_apply_layout` in `remediation`.
    """
    prep = _prepare_fields_and_layout(client, kind, flow_id, specs, groups)
    if isinstance(prep, Err):
        return prep
    draft, new = prep
    ignored = _changed_ignored(draft, specs)
    req_names = [s.name for s in specs]
    skipped, added = _partition_names(req_names, field_names(draft), ignored.names)
    read_back = _sync_fields_and_layout(
        client, kind, flow_id, draft, new, added, groups
    )
    if isinstance(read_back, Err):
        return read_back
    return _finalize_fields_and_layout(
        client, kind, flow_id, draft, read_back, specs, ignored, added, skipped, publish
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

    Collateral (A4): `apply_exact_layout` REBUILDS every named section's rows, so a field already
    in one of those sections that the spec does not name is MOVED — re-tiled into trailing rows
    after the stated ones. Nothing is lost (Field/Column ids and their Permission/Event back-refs
    survive, which is why this is not `missing`), but the form the user sees changes, and a
    partial spec is the documented, encouraged usage. Every such field is now named in
    `collateral` instead of moving silently.

    The span/crowding/duplicate refusals are PURE — they read the spec and nothing else — so they
    run BEFORE the GET: a caller with an impossible layout is refused without paying for a live
    round trip. `apply_exact_layout` still re-runs them on the far side, so the pure transform
    stays independently safe for any other caller.
    """
    try:
        validate_layout_spans(layout)
    except ValueError as e:
        return Err("verify", f"offline apply_exact_layout rejected the spec: {e}")

    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    collateral = tuple(
        f"{title!r}: {fname!r} was not named in the layout — re-tiled into a trailing row "
        "after the stated rows"
        for title, rows_spec in layout.items()
        for fname in _section_field_names(draft, title)
        if fname not in {f for row in rows_spec for f, _s, _e in row}
    )

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
        missing=(), changed_ignored=(), collateral=collateral,
        remediation=("forge_apply_layout",) if collateral else (),
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


def _is_table_host(node: Any, name: str) -> bool:
    if not isinstance(node, dict):
        return False
    return node.get("Type") == "Model" and node.get("Name") == name


def _find_table_host(draft: Draft, name: str) -> dict[str, Any] | None:
    for node in draft.values():
        if _is_table_host(node, name):
            return node
    return None


def _table_model_node(draft: Draft, host_col: dict[str, Any]) -> dict[str, Any] | None:
    table_ids = host_col.get("Column::Model", [])
    if not table_ids:
        return None
    node = draft.get(table_ids[0])
    if isinstance(node, dict):
        return node
    return None


def _table_child_field_names(draft: Draft, table_node: dict[str, Any]) -> set[str]:
    field_ids = table_node.get("Model::Field", [])
    names: set[str] = set()
    for fid in field_ids:
        field = draft.get(fid)
        if isinstance(field, dict):
            name = field.get("Name")
            if name is not None:
                names.add(name)
    return names


def _table_live_columns(draft: Draft, name: str) -> set[str]:
    host = _find_table_host(draft, name)
    if host is None:
        return set()
    table_node = _table_model_node(draft, host)
    if table_node is None:
        return set()
    return _table_child_field_names(draft, table_node)


def _audit_table_columns(
    wanted: tuple[str, ...],
    live: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    verified: list[str] = []
    missing: list[str] = []
    for col in wanted:
        if col in live:
            verified.append(col)
        else:
            missing.append(col)
    return tuple(verified), tuple(missing)


def _prepare_table_draft(
    draft: Draft,
    name: str,
    columns: list[tuple[str, str]] | list[tuple[str, str, dict[str, Any] | None]],
    max_rows: int | None,
    allow_import: bool,
    after_section: str | None,
) -> tuple[Draft, bool] | Err:
    already = _find_table_host(draft, name) is not None
    try:
        new_draft = add_table(
            draft, name, columns, max_rows=max_rows, allow_import=allow_import,
            after_section=after_section,
        )
    except ValueError as e:
        return Err("verify", f"offline add_table rejected the spec: {e}")
    return new_draft, already


def _sync_table_changes(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    draft: Draft,
    name: str,
    columns: list[tuple[str, str]] | list[tuple[str, str, dict[str, Any] | None]],
    max_rows: int | None,
    allow_import: bool,
    after_section: str | None,
) -> tuple[bool, Err | None]:
    prep = _prepare_table_draft(draft, name, columns, max_rows, allow_import, after_section)
    if isinstance(prep, Err):
        return False, prep
    new_draft, already = prep
    if already:
        return False, None
    written = client.put_draft(kind, flow_id, new_draft, expect_version=draft.get(_META_VERSION))
    if isinstance(written, Err):
        return False, written
    return True, None


def _publish_table(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    publish: bool,
    missing: tuple[str, ...],
) -> tuple[bool, Err | None]:
    if not publish or missing:
        return False, None
    pub = client.publish(kind, flow_id)
    if isinstance(pub, Err):
        return False, pub
    return True, None


def _verify_and_publish_table(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    name: str,
    columns: list[tuple[str, str]] | list[tuple[str, str, dict[str, Any] | None]],
    created: bool,
    publish: bool,
) -> TableReport | Err:
    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back

    wanted_cols = tuple(c[0] for c in columns)
    live_cols = _table_live_columns(read_back, name)
    verified, missing = _audit_table_columns(wanted_cols, live_cols)

    published, pub_err = _publish_table(client, kind, flow_id, publish, missing)
    if pub_err is not None:
        return pub_err

    return TableReport(
        flow_id=flow_id, table_name=name, created=created, columns=wanted_cols,
        verified_columns=verified, missing_columns=missing,
        meta_version=read_back.get(_META_VERSION), published=published,
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

    created, sync_err = _sync_table_changes(
        client, kind, flow_id, draft, name, columns, max_rows, allow_import, after_section
    )
    if sync_err is not None:
        return sync_err

    return _verify_and_publish_table(client, kind, flow_id, name, columns, created, publish)


@dataclass(frozen=True)
class WorkflowReport:
    """Output-invariant audit for forge_build_workflow. DESTRUCTIVE — see apply_workflow's
    docstring: `unassigned` is not a failure, it is an honest report of which steps got no
    Resource wired (role=None, e.g. because forge_member_batch harvested nothing to assign).

    `permissions_deleted` / `collateral` / `remediation` are the A4 half: this tool destroys
    things it was never asked to touch (a live rebuild measured 234 Permission nodes -> 0), and a
    report that says nothing about that is how a wiped visibility matrix reaches production. They
    are NOT folded into `isError` — the destruction is documented, intended behavior; what was
    missing is the audit trail, not a rollback.
    """
    flow_id: str
    steps: tuple[str, ...]
    verified_steps: tuple[str, ...]
    missing_steps: tuple[str, ...]
    assigned: tuple[str, ...]            # step names that got a real Resource/assignee wired
    unassigned: tuple[str, ...]          # step names with role=None -- no assignee to wire
    permissions_deleted: int             # Permission nodes the rebuild destroyed (was live, now gone)
    collateral: tuple[str, ...]          # everything else this rebuild destroyed or relocated
    remediation: tuple[str, ...]         # tool names the caller now OWES because of the above
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "steps": list(self.steps),
            "verified_steps": list(self.verified_steps), "missing_steps": list(self.missing_steps),
            "assigned": list(self.assigned), "unassigned": list(self.unassigned),
            "permissions_deleted": self.permissions_deleted,
            "collateral": list(self.collateral), "remediation": list(self.remediation),
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

    What it CAN do, and now does, is state the damage (A4). The report carries
    `permissions_deleted` counted before-vs-after on the REAL read-back (not on the offline
    graph — a count taken from what we hoped to write would prove nothing), every relocated
    SequenceNumber Step stamp, and a machine-readable `remediation` list naming the tools the
    caller now owes. No rollback is attempted; a rebuild is not undoable, and pretending
    otherwise would be worse than saying so.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)
    permissions_before = len(_permission_pairs(draft))
    malformed_before = _malformed_permissions(draft)
    stamps_before = _sequence_step_stamps(draft)

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

    # THE RULE: the damage is counted on what came BACK, never on what we sent.
    permissions_deleted = permissions_before - len(_permission_pairs(read_back))
    stamps_after = _sequence_step_stamps(read_back)
    relocated = tuple(
        f"SequenceNumber {fname!r}: Step stamp relocated from step {was!r} to "
        f"{stamps_after.get(fname)!r} — build_workflow repoints a stranded stamp by NAME, "
        "falling back to StartEvent (#18: a dangling stamp is THE deterministic publish-500)"
        for fname, was in stamps_before.items() if stamps_after.get(fname) != was
    )
    collateral: list[str] = []
    remediation: list[str] = []
    if permissions_deleted > 0:
        collateral.append(
            f"{permissions_deleted} Permission node(s) deleted — build_workflow replaces every "
            "Activity, so the WHOLE per-step visibility matrix is gone (CLAUDE.md Workflow, "
            "Visibility)")
        remediation.append("forge_set_visibility")
    if relocated:
        collateral.extend(relocated)
        remediation.append("forge_add_sequence_number")
    if malformed_before:
        # These never counted as pairs, so `permissions_deleted` cannot describe them — and the
        # rebuild destroyed them all the same. Named, not counted into the pair total, so the two
        # numbers stay honest and no Permission node lands in zero buckets.
        collateral.append(
            f"{len(malformed_before)} malformed Permission node(s) deleted, outside the "
            f"{permissions_deleted} counted pair(s) (no readable Column/Activity): "
            f"{', '.join(malformed_before)}")
        if "forge_set_visibility" not in remediation:
            remediation.append("forge_set_visibility")

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return WorkflowReport(
        flow_id=flow_id, steps=wanted, verified_steps=verified, missing_steps=missing,
        assigned=assigned, unassigned=unassigned,
        permissions_deleted=max(permissions_deleted, 0), collateral=tuple(collateral),
        remediation=tuple(remediation), meta_version=read_back.get(_META_VERSION),
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
    triggers: tuple[str, ...]      # "<field> (<Type>) -> <trigger>" — what actually got written
    derived: tuple[str, ...]       # field names whose trigger this call derived (caller omitted it)
    unverified: tuple[str, ...]    # triggers whose (type -> trigger) pair is NOT live-confirmed
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "fields": list(self.fields), "verified": list(self.verified),
            "missing": list(self.missing), "triggers": list(self.triggers),
            "derived": list(self.derived), "unverified": list(self.unverified),
            "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing),
        }


@dataclass(frozen=True)
class _EventPlan:
    """What `_resolve_event_triggers` worked out, before a single byte is written."""
    events: dict[str, list[tuple[str, str]]]   # ready for graph.set_field_events — no None left
    triggers: tuple[str, ...]
    derived: tuple[str, ...]
    unverified: tuple[str, ...]


def _resolve_event_triggers(
    draft: Draft, events: dict[str, list[tuple[str | None, str]]],
) -> _EventPlan:
    """Resolve every event's trigger against the SOURCE field's real type in the LIVE draft.

    CLAUDE.md Field events: **the trigger is a FUNCTION of the source field's type** — Select
    fires `onClick`, Date and Number fire `onSelect`, Text/Textarea fire `onChange`. A hand-picked
    wrong trigger writes fine, publishes fine, and simply never fires, so it is invisible to every
    check this engine has (THE RULE, in its purest form). `types.trigger_for` is the one table.

    Three refusals, all raised BEFORE any write, all naming what they saw:
      * the source field's type takes no event at all (`types.NO_EVENT_FIELD_TYPES` — the builder
        offers no Event tab, so there is no trigger string to find);
      * the caller stated a trigger that DISAGREES with the derived one — both are named;
      * the type is real but outside `trigger_for`'s table AND the caller stated nothing, so
        there is nothing to derive from and nothing to guess with (doctrine: never invent a wire
        value that is not captured).

    A field name absent from the draft is deliberately NOT refused here: `set_field_events` owns
    that message, and duplicating it would only make the two drift.
    """
    by_name = {v.get("Name"): v for v in draft.values()
               if isinstance(v, dict) and v.get("Kind") == "Field"}
    resolved: dict[str, list[tuple[str, str]]] = {}
    triggers: list[str] = []
    derived: list[str] = []
    unverified: list[str] = []

    for fname, specs in events.items():
        node = by_name.get(fname)
        if node is None:
            # not this function's refusal to make — `set_field_events` says "no field named X"
            # better than anything derived from a type we could not read. Pass through verbatim,
            # unless there is nothing to pass through, in which case say exactly that.
            if any(t in (None, "") for t, _s in specs):
                raise ValueError(f"cannot derive a trigger for {fname!r}: no field of that name "
                                 "is on this flow")
            resolved[fname] = [(t, sc) for t, sc in specs if t]
            continue
        raw = node.get("Type")
        want: str | None = None
        if isinstance(raw, str):
            if raw in NO_EVENT_FIELD_TYPES:
                raise ValueError(
                    f"{fname!r} is a {raw} field: it can never carry an event — the builder "
                    f"offers no Event tab for it, so no trigger string exists (CLAUDE.md Field "
                    f"events). This engine refuses {len(NO_EVENT_FIELD_TYPES)}: "
                    f"{sorted(NO_EVENT_FIELD_TYPES)}. CLAUDE.md names a SIXTH event-less type on "
                    "the platform, Rich text, which is deliberately absent from that set: its "
                    "wire shape is uncaptured and its inferred shape is Textarea+AllowFormatting, "
                    "indistinguishable from a plain Textarea, which legitimately fires onChange "
                    "(types.NO_EVENT_FIELD_TYPES)")
            try:
                ftype = FieldType(raw)
            except ValueError:
                ftype = None                      # a real type this engine has no mapping for
            if ftype is not None:
                want = trigger_for(ftype).value
                if ftype not in TRIGGER_LIVE_CONFIRMED:
                    unverified.append(
                        f"{fname} ({raw}) -> {want}: family-inferred from the field type, NOT "
                        "live-confirmed on a published flow (CLAUDE.md Field events)")

        out: list[tuple[str, str]] = []
        for given, script in specs:
            given = given or None                 # "" from a wire caller means "derive it"
            if want is None:
                if given is None:
                    raise ValueError(
                        f"{fname!r} is of type {raw!r}, which is not in `types.trigger_for` — "
                        "this engine has no captured trigger for it and will not guess one; "
                        "state the trigger explicitly, or capture it off the builder first")
                unverified.append(
                    f"{fname} ({raw}) -> {given}: taken from the caller — {raw!r} is outside "
                    "`types.trigger_for`, so nothing here could confirm or contradict it")
                out.append((given, script))
                triggers.append(f"{fname} ({raw}) -> {given}")
                continue
            if given is None:
                derived.append(fname)
            elif given != want:
                raise ValueError(
                    f"{fname!r} is a {raw} field: it fires {want!r}, but the spec asks for "
                    f"{given!r} — a wrong trigger writes fine, publishes fine, and simply never "
                    "fires (CLAUDE.md Field events). Omit it and it is derived for you")
            out.append((want, script))
            triggers.append(f"{fname} ({raw}) -> {want}")
        resolved[fname] = out

    return _EventPlan(resolved, tuple(triggers), tuple(dict.fromkeys(derived)),
                      tuple(dict.fromkeys(unverified)))


def apply_field_events(
    client: KfClient,
    flow_id: str,
    events: dict[str, list[tuple[str | None, str]]],
    publish: bool = False,
    kind: FlowKind = "process",
) -> EventReport | Err:
    """GET draft -> DERIVE each source field's trigger from its live type (`_resolve_event_triggers`
    — the trigger is a FUNCTION of the source type, CLAUDE.md Field events) -> graph.set_field_events
    offline (rejects a top-level `await` or a `KFSDK` reference before any write — the editor's own
    two parse rules) -> guarded PUT -> read-back verify each named field carries a Field::Event ->
    optional publish.

    A trigger of `None` (or `""`) means DERIVE IT, which is the recommended call: the draft is
    already in hand, so there is no reason to make a caller guess. A stated trigger that
    disagrees with the derived one is refused outright rather than written — that combination is
    invisible afterwards, because the event lands, publishes, and never fires.

    The report carries the uncertainty rather than hiding it: `unverified` names every
    (type -> trigger) pair that is family-inferred rather than live-confirmed (User->onSelect and
    Boolean->onClick, per CLAUDE.md), so a caller reading the audit knows which triggers still owe
    a live capture.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        plan = _resolve_event_triggers(draft, events)
    except ValueError as e:
        return Err("verify", f"field-event trigger check refused the spec: {e}")

    try:
        new = set_field_events(draft, plan.events)
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
                       triggers=plan.triggers, derived=plan.derived, unverified=plan.unverified,
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


def _is_sequence_field(v: Any, name: str) -> bool:
    return (
        isinstance(v, dict)
        and v.get("Kind") == "Field"
        and v.get("Type") == "SequenceNumber"
        and v.get("Name") == name
    )


def _verify_sequence_number(draft: Draft, name: str) -> bool:
    for v in draft.values():
        if _is_sequence_field(v, name):
            props = v.get("Field::Property")
            return isinstance(props, list) and len(props) == 3
    return False


def _publish_sequence_flow(
    client: KfClient, kind: FlowKind, flow_id: str, publish: bool, verified: bool,
) -> bool | Err:
    if not (publish and verified):
        return False
    pub = client.publish(kind, flow_id)
    return pub if isinstance(pub, Err) else True


def _save_sequence_draft(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    field_name: str,
    section_name: str,
    prefix: str,
    padding: str,
    step_activity_name: str,
    start: int,
    end: int,
) -> Draft | Err:
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)
    try:
        new = add_sequence_number(
            draft, field_name, section_name, prefix, padding,
            step_activity_name, start=start, end=end,
        )
    except ValueError as e:
        return Err("verify", f"offline add_sequence_number rejected the spec: {e}")
    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written
    return client.get_draft(kind, flow_id)


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
    read_back = _save_sequence_draft(
        client, kind, flow_id, field_name, section_name, prefix, padding,
        step_activity_name, start, end,
    )
    if isinstance(read_back, Err):
        return read_back

    verified = _verify_sequence_number(read_back, field_name)
    pub = _publish_sequence_flow(client, kind, flow_id, publish, verified)
    if isinstance(pub, Err):
        return pub

    return SequenceNumberReport(
        flow_id=flow_id,
        field_name=field_name,
        section=section_name,
        verified=verified,
        missing=not verified,
        meta_version=read_back.get(_META_VERSION),
        published=pub,
    )


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


def _node_child_ids(draft: Draft, node_id: str, key: str) -> list[str]:
    node = draft.get(node_id)
    if not isinstance(node, dict):
        return []
    items = node.get(key)
    return items if isinstance(items, list) else []


def _condition_rule(cond: Any) -> tuple[str, str] | None:
    if isinstance(cond, dict) and isinstance(cond.get("Operator"), str):
        return (cond["Operator"], str(cond.get("RHSValue")))
    return None


def _criteria_conditions(read_back: Draft, cid: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for condid in _node_child_ids(read_back, cid, "Criteria::Condition"):
        rule = _condition_rule(read_back.get(condid))
        if rule is not None:
            out.add(rule)
    return out


def _field_live_rules(read_back: Draft, field_node: dict[str, Any]) -> set[tuple[str, str]]:
    criteria_ids = field_node.get("FieldValidation::Criteria")
    if not isinstance(criteria_ids, list):
        return set()
    live: set[tuple[str, str]] = set()
    for cid in criteria_ids:
        live.update(_criteria_conditions(read_back, cid))
    return live


def _field_map(draft: Draft) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for v in draft.values():
        if isinstance(v, dict) and v.get("Kind") == "Field":
            out[v.get("Name")] = v
    return out


def _audit_all_field_rules(
    read_back: Draft,
    rules: dict[str, list[tuple[str, str]]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    by_name = _field_map(read_back)
    flat: list[tuple[str, str]] = []
    verified: list[tuple[str, str]] = []
    for fname, fl_rules in rules.items():
        flat.extend(fl_rules)
        live = _field_live_rules(read_back, by_name.get(fname, {}))
        for rule in fl_rules:
            if rule in live:
                verified.append(rule)
    return flat, verified


def _calc_missing(
    flat: list[tuple[str, str]],
    verified: list[tuple[str, str]],
) -> tuple[tuple[str, str], ...]:
    verified_set = set(verified)
    missing: list[tuple[str, str]] = []
    for r in flat:
        if r not in verified_set:
            missing.append(r)
    return tuple(missing)


def _apply_field_validation_offline(
    draft: Draft,
    rules: dict[str, list[tuple[str, str]]],
) -> Draft | Err:
    try:
        new = draft
        for fname, fl_rules in rules.items():
            for operator, value in fl_rules:
                new = add_field_validation(new, fname, operator, value)
        return new
    except ValueError as e:
        return Err("verify", f"offline add_field_validation rejected the spec: {e}")


def _sync_field_validation_draft(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    rules: dict[str, list[tuple[str, str]]],
) -> Draft | Err:
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    new = _apply_field_validation_offline(draft, rules)
    if isinstance(new, Err):
        return new
    written = client.put_draft(kind, flow_id, new, expect_version=draft.get(_META_VERSION))
    if isinstance(written, Err):
        return written
    return client.get_draft(kind, flow_id)


def _publish_validation(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    publish: bool,
    missing: tuple[tuple[str, str], ...],
) -> bool | Err:
    if not publish or bool(missing):
        return False
    pub = client.publish(kind, flow_id)
    if isinstance(pub, Err):
        return pub
    return True


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
    read_back = _sync_field_validation_draft(client, kind, flow_id, rules)
    if isinstance(read_back, Err):
        return read_back

    flat, verified = _audit_all_field_rules(read_back, rules)
    missing = _calc_missing(flat, verified)
    pub_result = _publish_validation(client, kind, flow_id, publish, missing)
    if isinstance(pub_result, Err):
        return pub_result

    return ValidationReport(
        flow_id=flow_id,
        field_name=",".join(rules),
        rules=tuple(flat),
        verified=tuple(verified),
        missing=missing,
        meta_version=read_back.get(_META_VERSION),
        published=pub_result,
    )


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

    One check lives HERE rather than in `verify.doctor`, and only because it cannot live there:
    MEMBERSHIP is not in the draft at all. CLAUDE.md > Members first — "assignees cannot be
    written before members exist — publish fails with a metadata error if you try" — so a flow
    whose steps carry AppRole assignees while its live roster is EMPTY is a documented,
    zero-diagnostic publish failure that the pure offline module can only ever see half of (rule 6
    proves a Resource exists, never that anyone is in the role). The tool has the network, so it
    reads `GET .../member` and folds the verdict into the same `problems` list, its own `members`
    bucket, and `members_found`. A roster this tool could not READ is recorded in
    `member_fetch_error`, never counted as populated, AND recorded in `unvalidated` — an
    unreadable roster is UNKNOWN, not healthy, and the audit says so instead of reporting a clean
    bill of health for a claim it never checked.
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

    problems = list(report.problems)
    checked = dict(report.checked)
    unvalidated = list(report.unvalidated)

    # the blind spot the graph cannot close: an AppRole assignee with nobody in the role
    assignees = [v for v in draft.values()
                 if isinstance(v, dict) and v.get("Kind") == "Resource"
                 and v.get("ValueType") == "AppRole" and v.get("Value")]
    checked["members"] = len(assignees)
    members_found: int | None = None
    member_error: str | None = None
    if assignees:
        roster = client.get_members(kind, flow_id)
        if isinstance(roster, Err):
            member_error = roster.message
            # UNKNOWN is not healthy. Recording the error in its own key was only half the job:
            # the audit still reported `ok` for the one claim it never managed to check, so
            # "doctor is clean" could not distinguish a wired flow from an unreadable roster —
            # which is the whole reason this rule exists. It lands in `unvalidated` rather than
            # `problems` for the same reason a list whose items would not fetch does (the
            # `list_fetch_errors` precedent above): the FLOW is not known to be broken, the TOOL
            # failed to read, and flagging a network failure as a graph defect would false-flag a
            # perfectly wired flow. Never silently accepted, never silently flagged.
            unvalidated.append(
                f"membership of {len(assignees)} AppRole assignee(s) NOT validated — the live "
                f"member roster could not be read ({member_error}); a flow with assignees and an "
                f"EMPTY roster fails publish with a bare metadata error (CLAUDE.md > Members "
                f"first), and this run cannot tell you which case this is — re-run forge_doctor, "
                f"or read the roster with forge_member_batch's own report")
        else:
            members_found = len(roster)
            if not roster:
                problems.append(
                    f"flow has {len(assignees)} AppRole assignee(s) but ZERO members — publish "
                    f"fails with a bare metadata error (CLAUDE.md > Members first: members before "
                    f"assignees, every time; grant them with forge_member_batch)")

    return {
        "flow_id": flow_id,
        "ok": not problems,
        "problems": problems,
        "checked": checked,
        "unvalidated": unvalidated,
        "unvalidatable_scripts": report.unvalidatable_scripts,
        "list_ids_checked": sorted(list_options),
        "list_fetch_errors": list_errors,
        "members_found": members_found,
        "member_fetch_error": member_error,
        "isError": bool(problems),
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
    roles_seen: int = 0                  # every record discovery RECEIVED on this call, counted
                                          # before any filter -- reported next to `applied` so
                                          # "granted 1 of the 2 roles that exist" can never be
                                          # silent (live 2026-08-19: it was). 0 on any path that
                                          # discovers nothing -- the sibling harvest, and
                                          # apply_member_roles' caller-named set.
    roles_unusable: tuple[str, ...] = ()  # seen by discovery, NOT grantable (no `_id`, no `Name`,
                                          # or not a record at all) -- the bucket that keeps
                                          # `roles_seen` == len(applied) + len(roles_unusable).

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "target_flow_id": self.target_flow_id, "source_flow_id": self.source_flow_id,
            "harvested": list(self.harvested), "applied": list(self.applied),
            "verified": list(self.verified), "missing": list(self.missing), "note": self.note,
            "role_ids": list(self.role_ids),
            "resolved": {name: rid for name, rid in self.resolved},
            "roles_seen": self.roles_seen, "roles_granted": len(self.applied),
            "roles_unusable": list(self.roles_unusable),
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

    ⚠️ `roles_seen` counts what the ROUTE returned, not what survived a type filter. A record that
    is not a dict at all used to be dropped before the count — the route answered with two records
    and the report said it saw one, so `seen == granted + unusable` held only because the dropped
    record never entered it (the output-invariant bug, restated one bucket over). `list_app_roles`
    only filters non-dicts when it is SCOPING to an app id; called with `app_id=None` it returns
    the account route's bare array verbatim, so this is a reachable shape, not a hypothetical.
    `apply_member_batch`'s harvest path already counted its own unusable records this way; the two
    paths now agree.
    """
    app_id = client._cfg.app_id
    roles = client.list_app_roles(app_id)
    if isinstance(roles, Err):
        return roles
    usable = [r for r in roles if isinstance(r, dict) and r.get("_id") and r.get("Name")]
    # Every record the account list returned lands in exactly one bucket: usable -> granted, or
    # unusable -> named here. A record with no `_id`/`Name` — or one that is no record at all —
    # cannot be posted to member/batch, and dropping it silently is how "granted 1 of 2" reads as
    # success.
    unusable = tuple(sorted(
        (f"{r.get('_id') or r.get('Name') or '<blank>'} "
         f"(no {'Name' if r.get('_id') else '_id'} on the account list record)"
         if isinstance(r, dict) else
         f"{r!r} (not a record — the account list returned a non-dict)")
        for r in roles if not (isinstance(r, dict) and r.get("_id") and r.get("Name"))
    ))
    if not usable:
        return MemberReport(
            target_flow_id=target_flow_id, source_flow_id=None, harvested=(), applied=(),
            verified=(), missing=(), roles_seen=len(roles), roles_unusable=unusable,
            note=f"no existing flow with members found in KF_APP to harvest from, and the "
                 f"account-level AppRole list has no usable role scoped to app {app_id!r} either "
                 f"(saw {len(roles)} app-scoped record(s)) — this is NOT a dead end and needs no "
                 f"human: call forge_create_app_role to create one (POST /app_role/2/{{acct}}, "
                 f"PROVEN live 2026-08-08 — it scopes the role to KF_APP in a single call), then "
                 f"re-run forge_member_batch. forge_add_member_roles does both in one call.",
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
        roles_seen=len(roles), roles_unusable=unusable,
        # SAW vs GRANTED, always both, even when they agree. Live 2026-08-19 this path granted 1
        # of 2 AppRoles created minutes earlier against the same app and said nothing about the
        # second — with only a granted count in the note there is no way to tell a discovery gap
        # (the account list returned one role) from a grant gap (it returned two and one was
        # dropped). The two numbers make that unambiguous from the report alone.
        note=f"saw {len(roles)} AppRole(s) scoped to app {app_id!r} at the account level, "
             f"granted {len(members)} (no sibling flow had members to harvest) — "
             f"Role={_ACCOUNT_GRANT_ROLE!r} "
             f"Permission={list(_ACCOUNT_GRANT_PERMISSION)!r}: {', '.join(names)}"
             + (f"; {len(unusable)} seen but NOT granted: {', '.join(unusable)}"
                if unusable else "")
             + ("; a role you created and do not see counted here was not on the account list "
                "when this ran — re-run forge_member_batch" if not unusable else ""),
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
    # SAW vs GRANTED on this path too. `_normalize_member` drops any record with no `Role` key,
    # and until now it dropped it into nothing at all — the same silent gap the account-level
    # path showed live on 2026-08-19, one source of members over.
    unusable = tuple(sorted(
        f"{(r.get('_id') or r.get('Name') or '<blank>') if isinstance(r, dict) else r!r} "
        "(no Role on the harvested member record)"
        for r in raw if _normalize_member(r) is None
    ))
    # role_ids: the harvested AppRole `_id`s -- _normalize_member already keeps `_id` (one of the
    # 5 documented member/batch keys), so this is populated on BOTH paths apply_member_batch can
    # take, not just the account-level fallback (_apply_own_app_roles). A caller (e.g. a workflow
    # step assignee) must be able to rely on `role_ids` regardless of which path granted them.
    role_ids = tuple(str(n["_id"]) for n in normalized if n.get("_id"))
    if not normalized:
        return MemberReport(
            target_flow_id=target_flow_id, source_flow_id=source_flow_id, harvested=(),
            applied=(), verified=(), missing=(),
            roles_seen=len(raw), roles_unusable=unusable,
            note=f"source flow {source_flow_id!r} has no AppRole members to harvest "
                 f"(saw {len(raw)} member record(s), none usable)"
                 + (f": {', '.join(unusable)}" if unusable else "")
                 + " — forge_create_app_role then forge_member_batch, or forge_add_member_roles, "
                   "grants one without a source flow at all",
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
        applied=harvested, verified=verified, missing=missing, role_ids=role_ids,
        roles_seen=len(raw), roles_unusable=unusable,
        note=(f"saw {len(raw)} member record(s) on {source_flow_id!r}, granted "
              f"{len(harvested)}; {len(unusable)} seen but NOT granted: {', '.join(unusable)}"
              if unusable else None),
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
    """Archive+delete a flow (process/form/case/list/dataset), a PAGE, or an APPLICATION, verifying
    deletion via the appropriate LIST route — never the delete response alone (CLAUDE.md Page CRUD:
    a page DELETE returns `{"status":"success"}` for ANY id, even a bogus one, and its draft GET
    still 200s afterward — storage lingers — so the list route is the only proof). `app_id` is
    required when `kind == "page"`.

    `list` and `dataset` take the SAME final branch as process/form/case: they are ordinary
    `/flow/2/{acct}/{kind}/{id}` records (the family their own `create_list`/`create_dataset` and
    `run_sweep`'s `_SWEEP_FLOW_KINDS` already read), and `KfClient.delete_flow` archives only a
    `process`. They cannot be PUBLISHED — born live, no publish route — but "no publish route" was
    never the same statement as "no delete route", and reading it that way is what removed the only
    way to clean up a dataform (D7).

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
    groups_added: tuple[str, ...] = ()
    groups_already_present: tuple[str, ...] = ()
    groups_unverified: tuple[str, ...] = ()
    groups_refused: tuple[str, ...] = ()
    group_count: int | None = None
    groups_note: str | None = None

    def as_tool_result(self) -> dict[str, Any]:
        out = {
            "role_id": self.role_id, "added": list(self.added),
            "already_present": list(self.already_present), "not_found": list(self.not_found),
            "user_count": self.user_count,
            "groups_added": list(self.groups_added),
            "groups_already_present": list(self.groups_already_present),
            "groups_unverified": list(self.groups_unverified),
            "groups_refused": list(self.groups_refused),
            "group_count": self.group_count,
            "isError": bool(self.not_found) or bool(self.groups_unverified),
        }
        if self.groups_note:
            out["groups_note"] = self.groups_note
        return out


def apply_add_role_users(
    client: KfClient,
    role_id: str,
    user_query: str | None = None,
    user_ids: list[dict[str, Any]] | None = None,
    groups: list[dict[str, Any]] | None = None,
    confirm_group_notification: bool = False,
    force_regrant_groups: bool = False,
    app_id: str | None = None,
) -> RoleUsersReport | Err:
    """Grant one or more users onto an AppRole (#52's assignee-lookup + asymmetric role-write).

    GET the role detail -> resolve candidate assignee objects (by `user_query` via
    `KfClient.get_assignee`, and/or `user_ids` — full assignee dicts `{_id, Kind, Email, Name}` a
    caller already resolved earlier, passed through verbatim) -> merge them onto the role's
    EXISTING `Members` (never drop current membership) -> ONE `put_app_role` write under the
    WRITE key `Users` -> read back and verify by `Members`/`UserCount`.

    🚨 A `groups` grant NOTIFIES every member of that group, cannot be recalled, and cannot be
    UNDONE (membership writes are add-only — see CLAUDE.md Members first). It is refused unless
    `confirm_group_notification=True` is passed in the same call. Test this tool with ONE named
    developer (`user_query`), never with a group.

    🚨 This tenant exposes no group LIST on the role detail (only a nullable `GroupCount`), so a
    repeat `groups` grant can never be told apart from a fresh one by enumeration — every call used
    to re-issue the SAME `Groups` write, re-fanning the notification out to every member all over
    again (CLAUDE.md Members first: this happened, 2026-08-20). When `GroupCount` already shows a
    group present (`> 0`), a grant is refused and reported under `groups_refused` instead of
    written, unless `force_regrant_groups=True` is passed — fail closed: a write we cannot prove
    is new is treated as a duplicate, not as safe to resend. `GroupCount` is a COUNT, not a
    membership list, so this guard also refuses a genuinely DIFFERENT group when any group is
    already present — over-blocking (recoverable via the override) beats re-broadcasting
    (not recoverable); `groups_refused` never claims the group is present, only that it was not
    written.

    Requires at least one of `user_query`/`user_ids`. A `user_query` with zero assignee matches
    is not a tool error on its own — it lands in `not_found`, the same "state it, never silently
    drop it" discipline as every other audit in this pack.
    """
    if user_query is None and not user_ids and not groups:
        return Err("verify", "apply_add_role_users: give user_query, user_ids or groups")

    # A GROUP GRANT NOTIFIES EVERY MEMBER OF THAT GROUP BY EMAIL, and an email cannot be recalled.
    # On a whole-tenant group ("everyone") that is every person in the account. This is the one
    # effect on this surface that reaches PEOPLE rather than the graph, so it fails CLOSED: the
    # caller must say, in the call itself, that they mean it. Granting a single USER
    # (`user_query`/`user_ids`) is unaffected — that is the safe way to test this tool, and the
    # refusal below says so, because a refusal a caller cannot act on is just a dead end.
    if groups and not confirm_group_notification:
        named = ", ".join(str(g.get("Name") or g.get("_id")) for g in groups
                          if isinstance(g, dict)) or "<unnamed>"
        return Err(
            "verify",
            f"refusing to grant group(s) [{named}] without confirm_group_notification=True — "
            f"Kissflow FANS OUT A NOTIFICATION TO EVERY MEMBER the moment the grant lands, and on "
            f"a whole-tenant group that is every person in the account (CLAUDE.md Members first: "
            f"this happened, 2026-08-20). AND IT CANNOT BE UNDONE: membership writes are ADD-ONLY "
            f"— nine removal shapes were probed live and none of them remove a group, so the only "
            f"recovery is to build a REPLACEMENT role, re-point the workflow assignees at it, "
            f"rebuild the visibility matrix that re-point wipes, and delete the polluted role. "
            f"To TEST this tool, grant ONE named developer instead: user_query='<your name>'. "
            f"Pass confirm_group_notification=True only after a human has confirmed the actual "
            f"recipient list, the same as sending mail.",
        )

    for g in groups or []:
        if not isinstance(g, dict) or not g.get("_id"):
            return Err("verify",
                       f"apply_add_role_users: each group must be an assignee-shaped dict with an "
                       f"_id, e.g. {{'_id': 'everyone', 'Kind': 'Group', 'Name': 'Everyone'}} — got "
                       f"{g!r}")

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

    # GROUPS ride the SAME PUT under their own write key. Reported live by an operator and
    # reproduced: a group object placed in `Users` is refused with UserDoesNotExistError — the
    # endpoint validates that array as users only. The body must carry BOTH keys:
    #   {"Users": [...], "Groups": [{"_id": "everyone", "Kind": "Group", "Name": "Everyone"}]}
    # `Groups` is a second asymmetric write key alongside `Users` (which reads back as `Members`).
    # ⚠️ The READ key for groups is UNCAPTURED on this tenant: the detail route carries a
    # `GroupCount` (nullable) but no group LIST that we have ever seen. So existing groups cannot
    # be enumerated, and this write therefore CANNOT promise to preserve them the way the `Users`
    # merge preserves members. That is stated in `groups_note` rather than assumed away, and the
    # read-back verifies by `GroupCount` movement, never by claiming the group is present.
    existing_groups = _existing_group_list(detail)
    group_ids = [str(g["_id"]) for g in (groups or [])]
    groups_already = tuple(gid for gid in group_ids
                           if gid in {str(g.get("_id")) for g in existing_groups})
    new_groups = [g for g in (groups or []) if str(g["_id"]) not in
                  {str(e.get("_id")) for e in existing_groups}]

    # `_existing_group_list` is always `[]` on this tenant (see its own docstring), so the merge
    # above never actually drops a group that's already there — `new_groups` still equals `groups`
    # on every repeat call. `GroupCount` is the one signal this tenant's detail DOES carry, so gate
    # the repeat write on IT: a role that already reports `GroupCount > 0` has some group on it
    # already, and this SAME `groups` argument is treated as a duplicate rather than resent, unless
    # the caller passes `force_regrant_groups=True` in the same call — the identical
    # "state your intent" discipline `confirm_group_notification` already uses above.
    blocked_note: str | None = None
    groups_refused: tuple[str, ...] = ()
    if new_groups and force_regrant_groups is False \
            and isinstance(detail.get("GroupCount"), int) and detail["GroupCount"] > 0:
        # GroupCount is a COUNT, not a membership check — a role with any group reads > 0, so this
        # cannot prove the requested group is the same one already present. The refused group lands
        # in its OWN `groups_refused` bucket, never `groups_already_present`: reporting a group as
        # "present" that was never proven present is exactly the invariant this pack forbids.
        groups_refused = tuple(str(g["_id"]) for g in new_groups)
        new_groups = []
        blocked_note = (
            f"refused to re-issue the Groups write for {', '.join(groups_refused)}: GroupCount is "
            f"already {detail['GroupCount']} on this role and no group LIST exists to prove these "
            f"are different groups, so a repeat grant is assumed to be a duplicate and skipped to "
            f"avoid re-broadcasting the notification — pass force_regrant_groups=True to override"
        )

    if not new_ones and not new_groups:
        return RoleUsersReport(role_id=role_id, added=(), already_present=already,
                               not_found=tuple(not_found), user_count=detail.get("UserCount"),
                               groups_already_present=groups_already, groups_refused=groups_refused,
                               group_count=detail.get("GroupCount"), groups_note=blocked_note)

    count_before = detail.get("GroupCount")
    body = _role_write_body(detail)
    body["Users"] = existing_members + new_ones
    if new_groups or existing_groups:
        body["Groups"] = existing_groups + new_groups

    written = client.put_app_role(role_id, body, app_id)
    if isinstance(written, Err):
        return written

    read_back = client.get_app_role(role_id)
    if isinstance(read_back, Err):
        return read_back
    live_ids = {str(m.get("_id")) for m in (read_back.get("Members") or []) if isinstance(m, dict)}
    added = tuple(str(c["_id"]) for c in new_ones if str(c["_id"]) in live_ids)
    unverified = tuple(str(c["_id"]) for c in new_ones if str(c["_id"]) not in live_ids)

    # Group read-back: verify by the only signal this tenant exposes. A group list, if the detail
    # ever grows one, wins; otherwise GroupCount MOVING is the evidence. When neither is available
    # the group lands in `groups_unverified` — written, not proven — because a write we cannot read
    # back is exactly what THE RULE says never to report as success.
    live_groups = {str(g.get("_id")) for g in _existing_group_list(read_back)}
    count_after = read_back.get("GroupCount")
    groups_note = None
    if live_groups:
        g_added = tuple(str(g["_id"]) for g in new_groups if str(g["_id"]) in live_groups)
        g_unver = tuple(str(g["_id"]) for g in new_groups if str(g["_id"]) not in live_groups)
    elif new_groups and isinstance(count_after, int) and isinstance(count_before, int) \
            and count_after > count_before:
        g_added, g_unver = tuple(str(g["_id"]) for g in new_groups), ()
        groups_note = (f"verified by GroupCount {count_before} -> {count_after} only — this tenant "
                       f"exposes no group LIST on the role detail, so membership is proven by count "
                       f"movement, not by naming the group back")
    elif new_groups:
        g_added, g_unver = (), tuple(str(g["_id"]) for g in new_groups)
        groups_note = (f"WRITTEN BUT UNPROVEN: no group list on the role detail and GroupCount did "
                       f"not move ({count_before!r} -> {count_after!r}). Confirm in the builder UI "
                       f"before relying on it — a 200 from the write proves nothing (THE RULE)")
    else:
        g_added, g_unver = (), ()
    if new_groups and not existing_groups and groups_note is None:
        groups_note = ("existing groups could not be enumerated (no group list on the role detail), "
                       "so this write cannot promise it preserved any that were already there")
    groups_note = groups_note or blocked_note

    return RoleUsersReport(
        role_id=role_id, added=added, already_present=already,
        not_found=tuple(not_found) + unverified, user_count=read_back.get("UserCount"),
        groups_added=g_added, groups_already_present=groups_already,
        groups_unverified=g_unver, groups_refused=groups_refused,
        group_count=count_after, groups_note=groups_note,
    )


def _existing_group_list(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """Whatever group LIST an AppRole detail exposes, or `[]` when it exposes none.

    Checked under both the write key (`Groups`) and the users-style read key (`Members` has its
    own asymmetry, so a group list could plausibly arrive under either). Returns only dicts
    carrying an `_id`, mirroring how the member merge filters candidates. `[]` means "no list was
    exposed" — NOT "there are no groups"; the caller must not read absence as emptiness, which is
    why every path that uses this also reports `group_count` and a note."""
    for key in ("Groups", "GroupMembers"):
        raw = detail.get(key)
        if isinstance(raw, list):
            return [g for g in raw if isinstance(g, dict) and g.get("_id")]
    return []


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
    """What `create_flow_any` made. The three `template_*` buckets are populated only on the
    `process` branch, which is the one that clones the identity shell (S4a — the same blindness
    `ProcessCreateReport` fixes for create_process, on the other tool that runs that clone). They
    stay empty for every born-live kind, which has no scaffold to inventory.

    `template_read_error` is the same field, for the same reason, as `ProcessCreateReport`'s: an
    inventory that could not be READ must never be indistinguishable from a template that brought
    nothing in. The two reports now make that distinction identically."""
    kind: str
    flow_id: str
    name: str
    status: str | None
    born_live: bool
    from_template: bool = False
    template_sections: tuple[str, ...] = ()
    template_required_fields: tuple[str, ...] = ()
    template_steps: tuple[str, ...] = ()
    template_read_error: str | None = None

    def as_tool_result(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind, "flow_id": self.flow_id, "name": self.name,
            "status": self.status, "born_live": self.born_live,
            "from_template": self.from_template,
            "template_sections": list(self.template_sections),
            "template_required_fields": list(self.template_required_fields),
            "template_steps": list(self.template_steps),
            "template_read_error": self.template_read_error,
            "isError": not self.flow_id,
        }
        if self.template_read_error:
            out["note"] = (f"could not read the scaffold back to inventory it: "
                           f"{self.template_read_error} — the three template_* buckets are empty "
                           f"because nothing was READ, not because the shell brought nothing in")
        elif self.from_template:
            out["note"] = (
                f"the process template shell brought in {len(self.template_sections)} section(s) "
                f"and {len(self.template_required_fields)} Required field(s) you did not ask for. "
                f"forge_set_visibility's `owners` must cover EVERY section listed above or that "
                f"section is editable at no step. Pass extra={{'from_template': False}} for a "
                f"bare shell."
            )
        return out


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
    if kind == "form":
        fid = client.create_flow(kind, name)  # type: ignore[arg-type]
        if isinstance(fid, Err):
            return fid
        return FlowCreateReport(kind=kind, flow_id=fid, name=name, status="Draft", born_live=False)

    if kind == "process":
        # A bare process draft is rejected 500 on the very next write until it carries a
        # ProcessDef (create_process's own docstring / FINDINGS.md). The unified create must
        # seed that scaffold too, or forge_apply_fields immediately 500s (bug found by the
        # Mode-A proof run 2026-08-12). `extra["from_template"]` (default True, issue #59) clones
        # the process-template identity shell instead of the bare single-step scaffold — same
        # from_template/template_path contract as create_process, see clone_template_shell's own
        # docstring. `extra["steps"]` is only consulted when from_template is False. On any
        # post-shell failure, abandon the junk flow.
        fid = client.create_flow("process", name)
        if isinstance(fid, Err):
            return fid
        draft = client.get_draft("process", fid)
        if isinstance(draft, Err):
            client.delete_flow("process", fid)
            return draft
        try:
            if extra.get("from_template", True):
                scaffolded = clone_template_shell(draft, extra.get("template_path"))
            else:
                scaffolded = ensure_process_def(draft, extra.get("steps") or ("Review",))
        except ValueError as e:
            client.delete_flow("process", fid)
            return Err("verify", str(e))
        written = client.put_draft("process", fid, scaffolded,
                                   expect_version=draft.get(_META_VERSION))
        if isinstance(written, Err):
            client.delete_flow("process", fid)
            return written
        # What the scaffold ACTUALLY landed, off an explicit GET of the live flow — the same
        # deliberate extra read `create_process` does, and for the same reason. This used to
        # inventory the PUT RESPONSE with a fallback to `scaffolded`, the payload that was SENT:
        # an inventory that can echo the request is not evidence (THE RULE), and a PUT that
        # answers with an ack rather than the graph inventoried to three empty tuples with no
        # error anywhere — indistinguishable from a template that genuinely brought nothing in,
        # which is precisely the distinction `template_read_error` exists to make.
        final = client.get_draft("process", fid)
        if isinstance(final, Err):
            inv, read_error = ScaffoldInventory((), (), ()), final.message
        else:
            inv, read_error = scaffold_inventory(final), None
        return FlowCreateReport(kind="process", flow_id=fid, name=name, status="Draft",
                                born_live=False,
                                from_template=bool(extra.get("from_template", True)),
                                template_sections=inv.sections,
                                template_required_fields=inv.required_fields,
                                template_steps=inv.steps,
                                template_read_error=read_error)

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


def publish_application_verified(client: KfClient, app_id: str) -> dict[str, Any] | Err:
    """Publish an APPLICATION (`forge_publish` already exposes `kind="application"`, but bare —
    this adds a genuine post-publish read-back, THE RULE: a 200 from publish proves nothing by
    itself). `publish_app` -> `get_app_draft` -> report the fresh `_meta_version` plus any
    `Runtime_`-prefixed node id found on the draft.

    ⚠️ `Runtime_` is UNCAPTURED — no shape in this repo has ever observed one (grepped the whole
    tree before writing this). It is included here defensively, as the read-back's own honest
    finding, not asserted as a proven shape: `runtime_id` is `None` with a note when absent,
    never a guessed or synthesized value (CLAUDE.md: never guess a literal — read it).
    """
    published = client.publish_app(app_id)
    if isinstance(published, Err):
        return published
    draft = client.get_app_draft(app_id)
    if isinstance(draft, Err):
        return {"app_id": app_id, "published": True, "runtime_id": None,
                "meta_version": None, "isError": True,
                "error": f"publish succeeded but read-back failed: {draft.as_tool_result()['error']}"}
    runtime_id = next((k for k in draft if isinstance(k, str) and k.startswith("Runtime_")), None)
    return {
        "app_id": app_id, "published": True, "runtime_id": runtime_id,
        "meta_version": draft.get(_META_VERSION), "isError": False,
        "note": None if runtime_id else (
            "no Runtime_-prefixed node observed on the app draft read-back — that shape is "
            "unconfirmed on this tenant; ponytail: not verified live yet, do not treat absence "
            "as proof either way"
        ),
    }


def create_template_app(client: KfClient, name: str) -> dict[str, Any] | Err:
    """ONE call, under the caller's own identity, creates a fresh Template App on the dev tenant
    carrying the transplanted source template process (ADR-0006, spec #10 seam 2, ticket #13), published end
    to end. `client` is account-level (no app selected required) — every step after the first
    scopes onto the app it just created via `scoped_to_app`. Composed ONLY of existing live
    primitives plus the pure `transplant_template` op, in the proven build order (CLAUDE.md >
    Build order): create application -> create a BARE process flow -> members FIRST -> write the
    transplanted graph (assignees ride in that write) -> publish the process with a status
    read-back (THE RULE: a 200 proves nothing) -> app-level publish with its own read-back ->
    doctor. A failed run after the application exists archives+deletes the half-built app, so a
    refused build leaves no junk in the tenant. A duplicate name surfaces the platform's own
    FlowNameAlreadyExists loud — no auto-rename, no retry.

    ⚠️ `app_url`'s `/view/app/{id}` pattern is a prod hyperlink found inside the vendored
    template's own rich-text Description field — prose written by a human into a field, not a
    route this codebase has ever captured off the builder itself. `url_verified: False` in the
    response reflects that honestly; the first human to actually open the URL should confirm or
    correct the pattern.
    """
    created = create_application_verified(client, name)
    if isinstance(created, Err):
        return created
    if created.get("isError"):
        return created
    app_id = created["app_id"]
    app = client.scoped_to_app(app_id)

    role_id: str | Err | None = None

    def _abandon(err: Err) -> Err:
        # fail loud on the cleanup too: the returned Err must say whether the half-built app is
        # really gone, never imply "no junk left" while the delete or its verify actually failed
        cleanup = delete_anything(app, "application", app_id)
        outcome = ("deleted+verified" if cleanup.get("verified")
                   else "deleted, NOT verified" if cleanup.get("deleted")
                   else "NOT deleted")
        notes = [f"app {app_id} {outcome}"]
        if cleanup.get("error"):
            notes.append(str(cleanup["error"]))
        if isinstance(role_id, str):
            role_gone = app.delete_app_role(role_id)  # best-effort, same convention as create_process's cleanup
            if isinstance(role_gone, Err) and not cleanup.get("verified"):
                notes.append(f"role {role_id} delete failed: {role_gone.message}")
        return Err(err.kind, f"{err.message} [cleanup: {'; '.join(notes)}]", status=err.status)

    role_name = f"{name} Role"
    role_id = app.create_app_role(role_name)
    if isinstance(role_id, Err):
        return _abandon(role_id)

    # Bare flow, NOT create_process: the transplant needs a bare draft (no RootProcessDef yet).
    flow_id = app.create_flow("process", name)
    if isinstance(flow_id, Err):
        return _abandon(flow_id)

    # Members FIRST (CLAUDE.md > Members first): assignees ride in the graph write below. A fresh
    # app has no sibling flow to harvest from, so this falls back to granting the app's own
    # AppRoles discovered at the account level — exactly the role just created.
    members = apply_member_batch(app, flow_id)
    if isinstance(members, Err):
        return _abandon(members)
    if members.missing or role_id not in members.role_ids:
        return _abandon(Err(
            "verify",
            f"member grant did not land the created AppRole {role_id!r}: "
            f"missing={list(members.missing)!r} role_ids={list(members.role_ids)!r}",
        ))

    draft = app.get_draft("process", flow_id)
    if isinstance(draft, Err):
        return _abandon(draft)
    try:
        grafted = transplant_template(draft, app_role=(role_id, role_name))
    except ValueError as e:
        return _abandon(Err("verify", str(e)))

    written = app.put_draft("process", flow_id, grafted, expect_version=draft.get(_META_VERSION))
    if isinstance(written, Err):
        return _abandon(written)

    # A PUT that 200s proves nothing about what actually persisted (THE RULE) — read the draft
    # back and confirm every transplanted node is really there before trusting the write.
    read_back = app.get_draft("process", flow_id)
    if isinstance(read_back, Err):
        return _abandon(Err("verify", f"graph write read-back failed: {read_back.message}"))
    graft_node_ids = [nid for nid in grafted if nid not in ("Root", _META_VERSION)]
    missing = [nid for nid in graft_node_ids if nid not in read_back]
    if missing:
        return _abandon(Err("verify",
            f"graph write did not land: {len(missing)} of {len(graft_node_ids)} nodes missing "
            f"from the live draft read-back (first few: {missing[:5]!r})"))

    # Publish the process WITH a status read-back — THE RULE, not a bare 200.
    pub = app.publish("process", flow_id)
    if isinstance(pub, Err):
        return _abandon(pub)
    detail = app.get_flow_detail("process", flow_id)
    if isinstance(detail, Err):
        return _abandon(Err(
            "verify", f"publish succeeded but status read-back failed: {detail.message}"
        ))
    status = detail.get("Status")
    if status != "Live":
        return _abandon(Err("verify", f"process publish read-back status {status!r}, not Live"))

    app_pub = publish_application_verified(app, app_id)
    if isinstance(app_pub, Err):
        return _abandon(app_pub)
    if app_pub.get("isError"):
        return _abandon(Err("verify", f"app publish read-back failed: {app_pub.get('error')}"))

    # Doctor read-back rides in the response — never a separate call the caller must remember.
    # Its own findings do NOT flip this tool's isError: the vendored capture ships known problems
    # (the differential bar) on purpose, reported as data for the caller/test to judge.
    doctor_report = run_doctor(app, flow_id)
    if isinstance(doctor_report, Err):
        return _abandon(doctor_report)

    return {
        "app_id": app_id, "name": name, "flow_id": flow_id,
        "role_id": role_id, "role_name": role_name,
        "members": members.as_tool_result(),
        "process_status": status,
        "app_publish": app_pub,
        "doctor": doctor_report,
        "app_url": f"{client._cfg.base}/view/app/{app_id}",
        "process_url": f"{client._cfg.base}/view/process/{flow_id}",
        "url_verified": False,
        "graph_nodes_verified": len(graft_node_ids),
        "isError": False,
    }


def _resolve_dataset_record_keys(
    client: KfClient, flow_id: str, record: dict[str, Any],
) -> dict[str, Any] | Err:
    """Translate a dataform record's KEYS from field NAMES to field ids, so a caller may pass
    either (the raw record route 404s FieldNotFound on a name key). Mirrors the simulate_case fix:
    fetch the dataform's live draft, build the name->id index, resolve. The synthetic system
    `"Name"` key (the record's unique key — a column id, not a display name) is passed through
    verbatim. A name matching no field fails LOUD, listing every available field name; a draft
    read failure fails LOUD too rather than silently letting a name key 404 downstream.
    """
    # Function-local import breaks the client<->dataplane cycle (dataplane imports client at module
    # load; a module-level import here would deadlock). Safe at call time — both modules are loaded.
    from .dataplane import field_name_index, resolve_value_keys
    draft = client.get_draft("dataset", flow_id)  # type: ignore[arg-type]
    if isinstance(draft, Err):
        return Err("verify", f"cannot resolve dataform field names — draft read failed: "
                             f"{draft.message}", status=draft.status)
    index = field_name_index(draft)
    return resolve_value_keys(record, index, passthrough=frozenset({"Name"}))


def apply_dataset_records(
    client: KfClient,
    flow_id: str,
    op: str,
    record: dict[str, Any] | None = None,
    record_id: str | None = None,
) -> dict[str, Any] | Err:
    """The THIRD data-plane route family: dataform records (#50, per-record CRUD #58). Record KEYS
    accept a field NAME or a field id for `create`/`update` — auto-resolved to ids against the
    dataform's live draft before the write (the raw route 404s FieldNotFound on a name key), the
    synthetic `"Name"` key passing through verbatim.

    - `op="create"`: writes ONE `record` (must carry the unique `Name` key; a duplicate 409s
      DuplicateKeyException, surfaced as a CLEAN Err naming the duplicate `Name`).
    - `op="update"`: partial-patches the record `record_id` (`PUT .../{flow}?_id={rec}`) with
      `record` (only the keys sent change).
    - `op="delete"`: deletes `record_id` (`DELETE .../{flow}?_id={rec}`); `record` must carry the
      mandatory `{"Name": ...}` delete body.
    - `op="list"`: reads back `{Columns, Data}`.

    Output-invariant audit: `created`/`listed`/`updated`/`deleted`/`failed` are integer counts,
    never a swallowed exception — a write that errors lands in `failed` with the cause in `error`,
    never silently dropped.
    """
    base = {"flow_id": flow_id, "op": op, "created": 0, "listed": 0,
            "updated": 0, "deleted": 0, "failed": 0, "isError": False}

    if op == "create":
        if not record:
            return Err("verify", "apply_dataset_records(op='create') requires a non-empty record")
        resolved = _resolve_dataset_record_keys(client, flow_id, record)
        if isinstance(resolved, Err):
            return resolved
        got = client.create_dataset_record(flow_id, resolved)
        if isinstance(got, Err):
            if got.status == 409:
                name = record.get("Name", "<unknown>")
                return Err("verify", f"dataset record with Name={name!r} already exists "
                                     f"(duplicate key) — {got.message}", status=409)
            return got
        return {**base, "created": 1, "record": got}

    if op == "update":
        if not record:
            return Err("verify", "apply_dataset_records(op='update') requires a non-empty record")
        if not record_id:
            return Err("verify", "apply_dataset_records(op='update') requires record_id (the "
                                 "record's _id)")
        resolved = _resolve_dataset_record_keys(client, flow_id, record)
        if isinstance(resolved, Err):
            return resolved
        got = client.update_dataset_record(flow_id, record_id, resolved)
        if isinstance(got, Err):
            return got
        return {**base, "updated": 1, "record_id": record_id, "record": got}

    if op == "delete":
        if not record_id:
            return Err("verify", "apply_dataset_records(op='delete') requires record_id (the "
                                 "record's _id)")
        name = (record or {}).get("Name")
        if not name:
            return Err("verify", "apply_dataset_records(op='delete') requires record={'Name': "
                                 "<key>} — the delete route mandates the Name body")
        got = client.delete_dataset_record(flow_id, record_id, name)
        if isinstance(got, Err):
            return got
        return {**base, "deleted": 1, "record_id": record_id}

    if op == "list":
        got = client.list_dataset_records(flow_id)
        if isinstance(got, Err):
            return got
        rows = got.get("Data", []) if isinstance(got, dict) else []
        return {**base, "listed": len(rows),
                "columns": got.get("Columns", []) if isinstance(got, dict) else [],
                "records": rows}

    return Err("verify", f"apply_dataset_records: unknown op {op!r} — valid: create, list, "
                         f"update, delete")


@dataclass(frozen=True)
class RolePreferenceReport:
    role_id: str
    default_page: str | None
    default_navigation: str | None
    verified: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id, "default_page": self.default_page,
            "default_navigation": self.default_navigation, "verified": self.verified,
            "isError": not self.verified,
        }


def apply_set_role_preference(
    client: KfClient,
    role_id: str,
    default_page: str | None = None,
    default_navigation: str | None = None,
    app_id: str | None = None,
) -> RolePreferenceReport | Err:
    """Set an AppRole's own default page/navigation (shapes/app_role_grant.json note 0, write
    route proven live 2026-08-12): `PUT /app_role/2/{acct}/{role_id}?_application_id={app}` body
    `{"Preference": {"DefaultPage": <page id or "Default">, "DefaultNavigation": <Navigation
    node's own Id, e.g. "Navigation001", or "Default">}}` — the sentinel string `"Default"` is
    valid for either key, meaning "use the platform default".

    Reuses the SAME `put_app_role` write route `apply_add_role_users` uses, and the same
    `_role_write_body` helper (`Members`->`Users` passthrough), so setting only a preference never
    accidentally drops existing membership. At least one of `default_page`/`default_navigation`
    must be given. Verified by re-reading the role's own `Preference` block.
    """
    if default_page is None and default_navigation is None:
        return Err("verify", "apply_set_role_preference: give default_page or default_navigation")

    detail = client.get_app_role(role_id)
    if isinstance(detail, Err):
        return detail

    body = _role_write_body(detail)
    pref = dict(body.get("Preference") or {})
    if default_page is not None:
        pref["DefaultPage"] = default_page
    if default_navigation is not None:
        pref["DefaultNavigation"] = default_navigation
    body["Preference"] = pref

    written = client.put_app_role(role_id, body, app_id)
    if isinstance(written, Err):
        return written

    read_back = client.get_app_role(role_id)
    if isinstance(read_back, Err):
        return read_back
    live_pref = read_back.get("Preference") or {}
    verified = all(
        live_pref.get(k) == v for k, v in
        (("DefaultPage", default_page), ("DefaultNavigation", default_navigation))
        if v is not None
    )
    return RolePreferenceReport(role_id=role_id, default_page=default_page,
                                default_navigation=default_navigation, verified=verified)


_SWEEP_SCOPES = ("apps", "flows", "pages", "roles", "lists")
_SWEEP_FLOW_KINDS = ("process", "form", "case", "list", "dataset")


def _sweep_bucket(got: list[Any] | Err) -> dict[str, Any]:
    if isinstance(got, Err):
        return {"status": "error", "count": 0, "items": [], "error": got.message}
    return {"status": "read", "count": len(got), "items": got, "error": None}


def run_sweep(client: KfClient, scope: str, app_id: str | None = None) -> dict[str, Any]:
    """Read-only full-inventory discovery, `_application_id`-scoped everywhere it matters — the
    TWO known leakage routes (CLAUDE.md: `list_flows`/`list_lists` return the WHOLE ACCOUNT's
    flows/lists without it) are already scoped inside `KfClient` itself, so this sweep inherits
    the safety, not just the convenience.

    `scope` is one of "apps"|"flows"|"pages"|"roles"|"lists"|"all". `app_id` defaults to the
    client's own configured `KF_APP`. Every requested sub-scope lands in exactly one bucket —
    `read` (with its item count + inventory), `error` (the Err message, never swallowed), or
    `skipped` (only "pages", when no `app_id` is available at all — pages are app-scoped by
    construction) — the output-invariant audit this whole engine insists on.
    """
    valid = (*_SWEEP_SCOPES, "all")
    if scope not in valid:
        return {"scope": scope, "isError": True,
                "error": f"forge_sweep: unknown scope {scope!r} — valid: {sorted(valid)}"}

    effective_app = app_id if app_id is not None else client._cfg.app_id
    wanted = _SWEEP_SCOPES if scope == "all" else (scope,)

    results: dict[str, Any] = {}
    any_error = False
    for s in wanted:
        if s == "apps":
            bucket = _sweep_bucket(client.list_applications())
        elif s == "flows":
            by_kind = {kind: _sweep_bucket(client.list_flows(kind))  # type: ignore[arg-type]
                      for kind in _SWEEP_FLOW_KINDS}
            any_error = any_error or any(v["status"] == "error" for v in by_kind.values())
            results[s] = by_kind
            continue
        elif s == "pages":
            if not effective_app:
                bucket = {"status": "skipped", "count": 0, "items": [],
                         "error": "no app_id given or configured — pages are app-scoped"}
            else:
                bucket = _sweep_bucket(client.list_pages(effective_app))
        elif s == "roles":
            bucket = _sweep_bucket(client.list_app_roles(effective_app))
        else:  # "lists"
            got = client.list_lists()
            rows = got.get("Data", got) if isinstance(got, dict) else got
            bucket = _sweep_bucket(rows if not isinstance(got, Err) else got)
        any_error = any_error or bucket["status"] == "error"
        results[s] = bucket

    return {"scope": scope, "app_id": effective_app, "results": results, "isError": any_error}


@dataclass(frozen=True)
class CopilotAskReport:
    """A copilot SEND ack + whatever the immediate follow-up read happens to show. The reply text
    is NEVER proof of anything landing (memory note "REPLY LAGS THE GRAPH", proven live
    2026-08-12: the thread can still show an old clarifying question as newest while the graph
    already has the field) — `forge_copilot_check`, called after a real delay, is the only
    oracle."""
    app_id: str
    message: str
    conversation_id: str | None
    immediate_reply: str | None
    expect: tuple[str, ...]
    status: str = "matched"  # "matched" | "pending: ..." | "read_failed: ..." — WHY id is null

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id, "message": self.message,
            "conversation_id": self.conversation_id, "immediate_reply": self.immediate_reply,
            "expect": list(self.expect), "reply_is_proof": False,
            "status": self.status,
            "note": "reply text is NEVER proof of success — structural builds land ~70s later, "
                   "not immediately; call forge_copilot_check after a real delay and diff the "
                   "actual graph before trusting anything landed (THE RULE). A null "
                   "conversation_id with status 'pending' is EXPECTED, not a failure.",
            "isError": False,
        }


def apply_copilot_ask(
    client: KfClient,
    app_id: str,
    message: str,
    expect: list[str] | None = None,
) -> CopilotAskReport | Err:
    """SEND one message to the app's copilot thread, then ONE immediate read of the
    conversation list — deliberately NOT a long poll (an MCP tool call has a budget; a
    structural build lands ~70s later per the live capture, far past any reasonable single-call
    wait). Returns whatever `ConversationId`/`SystemMessage` the immediate read happens to show,
    paired to `message` by exact `UserMessage` match — call `forge_copilot_check` later, after a
    real delay, for the actual verdict.

    `expect` is an OPTIONAL hint (node kinds the caller expects this ask to produce, e.g.
    `["Field"]`) — echoed back verbatim for the caller's own bookkeeping; this function does not
    itself verify it (that is `forge_copilot_check`'s job, against a real graph read-back).
    """
    sent = client.copilot_send(app_id, message)
    if isinstance(sent, Err):
        return sent

    convs = client.copilot_conversations(app_id)
    conversation_id: str | None = None
    reply: str | None = None
    if isinstance(convs, Err):
        # Fail loud, never a silent null: a READ failure must not read back identical to "message
        # not registered yet" — that is exactly what made a caller conclude the tool was broken
        # when it got null/null five times (Cowork bug report 2026-08-13).
        status = f"read_failed: {convs.kind}: {convs.message}"
    else:
        for c in convs:
            if isinstance(c, dict) and c.get("UserMessage") == message:
                conversation_id = c.get("ConversationId")
                reply = c.get("SystemMessage")
                break
        status = ("matched" if conversation_id else
                  "pending: your message is not in the thread yet — this is NORMAL, the copilot "
                  "lags ~70s; call forge_copilot_check after a real delay, do not retry the ask")

    return CopilotAskReport(app_id=app_id, message=message, conversation_id=conversation_id,
                            immediate_reply=reply, expect=tuple(expect or ()), status=status)


def _flow_id_inventory(client: KfClient) -> dict[str, list[str]] | Err:
    """`{flow kind: [flow id, ...]}` across every kind this engine can create — the SAME
    app-scoped inventory `run_sweep`'s "flows" bucket reads, factored out so
    `apply_copilot_check` can diff against it without duplicating the leakage-safe scoping."""
    out: dict[str, list[str]] = {}
    for kind in _SWEEP_FLOW_KINDS:
        got = client.list_flows(kind)  # type: ignore[arg-type]
        if isinstance(got, Err):
            return got
        out[kind] = [f["_id"] for f in got if isinstance(f, dict) and isinstance(f.get("_id"), str)]
    return out


@dataclass(frozen=True)
class CopilotCheckReport:
    """The real verdict for a copilot ask: the thread's reply (NEVER trusted on its own) plus
    `scatter` — every flow id that exists now but did not appear in `baseline_inventory` (memory
    note "SCATTER CAVEAT": copilot is APP-scoped, not flow-scoped, and has been observed silently
    building into a different flow than the one asked about). `landed_nodes` is a CHEAP top-level
    node-count per newly-scattered flow (ponytail: not a deep semantic diff — a caller who needs
    to know exactly WHAT landed should follow up with kf_get_flow_schema/forge_compare_to_spec on
    the flagged flow id; this function's job is to prove SOMETHING changed and WHERE, not to
    replay the full graph diff inline)."""
    app_id: str
    conversation_id: str
    reply: str | None
    scatter: dict[str, list[str]]
    landed_nodes: dict[str, dict[str, int]]

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id, "conversation_id": self.conversation_id, "reply": self.reply,
            "reply_is_proof": False, "scatter": self.scatter, "landed_nodes": self.landed_nodes,
            "note": "scatter = flow ids present now but absent from baseline_inventory; "
                   "landed_nodes is a cheap top-level-key COUNT per new flow, not a semantic "
                   "diff — never trust `reply` alone (THE RULE)",
            "isError": False,
        }


def apply_copilot_check(
    client: KfClient,
    app_id: str,
    conversation_id: str,
    baseline_inventory: dict[str, list[str]] | None = None,
) -> CopilotCheckReport | Err:
    """Read the copilot thread for `conversation_id`, and diff the app's CURRENT flow inventory
    against `baseline_inventory` (the shape `run_sweep(scope="flows")` returns per kind — a
    caller should snapshot it via forge_sweep BEFORE calling forge_copilot_ask). Every flow id
    that showed up since is `scatter`; each scattered flow's draft is read once for a cheap
    top-level node COUNT (`landed_nodes`), never a full semantic diff.
    """
    convs = client.copilot_conversations(app_id)
    if isinstance(convs, Err):
        return convs
    thread = [c for c in convs if isinstance(c, dict) and c.get("ConversationId") == conversation_id]
    reply = next((c.get("SystemMessage") for c in thread if c.get("SystemMessage")), None)

    current = _flow_id_inventory(client)
    if isinstance(current, Err):
        return current

    baseline = baseline_inventory or {}
    scatter: dict[str, list[str]] = {}
    landed_nodes: dict[str, dict[str, int]] = {}
    for kind, ids in current.items():
        base_ids = set(baseline.get(kind) or [])
        new_ids = [fid for fid in ids if fid not in base_ids]
        if not new_ids:
            continue
        scatter[kind] = new_ids
        counts: dict[str, int] = {}
        for fid in new_ids:
            draft = client.get_draft(kind, fid)  # type: ignore[arg-type]
            counts[fid] = len(draft) if isinstance(draft, dict) else -1  # -1 = read failed
        landed_nodes[kind] = counts

    return CopilotCheckReport(app_id=app_id, conversation_id=conversation_id, reply=reply,
                              scatter=scatter, landed_nodes=landed_nodes)


@dataclass(frozen=True)
class FullFieldsReport:
    """Output-invariant audit for forge_apply_fields' full extension (#55, ticket #48's field-
    layer capabilities — validation/computed/conditional-visibility offered alongside the field
    itself, not as bolt-ons). Every requested field, validation rule, computed formula, and
    conditional-visibility rule lands in its own verified/missing pair — never silently
    unaccounted for, same discipline as every other Report in this module.

    `changed_ignored`/`remediation` carry the same F2 meaning they do on `ApplyReport`: a
    requested field that already exists under a DIFFERENT type/required flag was not applied, is
    not a success, and sets `isError`.

    `collateral` carries the same A4 meaning it does on `ApplyReport`, and this report had no such
    field at all until D5: passing `groups` runs `graph.regroup_into_sections`, which REBUILDS
    every section's rows at a uniform width — one forge_apply_fields call silently re-tiled a
    custom grid an earlier forge_apply_layout had written, and the report said nothing. It does
    not set `isError` (nothing was lost — ids, Permissions and Events all survive), it is the
    damage made visible."""
    flow_id: str
    added: tuple[str, ...]
    skipped: tuple[str, ...]
    verified: tuple[str, ...]
    missing: tuple[str, ...]
    changed_ignored: tuple[str, ...]
    collateral: tuple[str, ...]
    remediation: tuple[str, ...]
    validations_verified: tuple[str, ...]
    validations_missing: tuple[str, ...]
    computed_verified: tuple[str, ...]
    computed_missing: tuple[str, ...]
    conditional_verified: tuple[str, ...]
    conditional_missing: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "added": list(self.added), "skipped": list(self.skipped),
            "verified": list(self.verified), "missing": list(self.missing),
            "changed_ignored": list(self.changed_ignored),
            "collateral": list(self.collateral),
            "remediation": list(self.remediation),
            "validations_verified": list(self.validations_verified),
            "validations_missing": list(self.validations_missing),
            "computed_verified": list(self.computed_verified),
            "computed_missing": list(self.computed_missing),
            "conditional_verified": list(self.conditional_verified),
            "conditional_missing": list(self.conditional_missing),
            "meta_version": self.meta_version, "published": self.published,
            "isError": bool(self.missing or self.changed_ignored or self.validations_missing
                            or self.computed_missing or self.conditional_missing),
        }


def apply_fields_full(
    client: KfClient,
    kind: FlowKind,
    flow_id: str,
    specs: list[FieldSpec],
    groups: list[tuple[str, list[str]]] | None = None,
    validations: dict[str, list[dict[str, str]]] | None = None,
    computed: dict[str, dict[str, Any]] | None = None,
    conditional: dict[str, dict[str, str]] | None = None,
    publish: bool = False,
) -> FullFieldsReport | Err:
    """forge_apply_fields' full extension (#55): fields + layout + per-field validation rules +
    computed formulas + conditional visibility, in ONE guarded read-verify-write — a caller
    building a form never leaves it half-configured between several separate PUTs (the "offer the
    whole field" build doctrine: validation + computed + defaults alongside the field itself, not
    bolted on afterward).

    `validations` maps a field NAME to `[{"operator":..., "rhs":..., "error_message": optional},
    ...]` (graph.add_field_validation, extended with `ErrorMessage`, #48). `computed` maps a field
    NAME to a formula AST `{"fn":..., "args":[...]}` (graph.set_field_computed, the Field-owned
    Expression, #48). `conditional` maps a field NAME to `{"trigger_field":..., "operator":...,
    "rhs":...}` (graph.set_conditional_visibility, the ColumnVisibility Criteria family, #48).
    `default_value` has NO separate parameter here — it rides on each FieldSpec's own `options`
    (`kfforge.tools._to_spec` folds a `default_value` key into `options["DefaultValue"]`), since
    it is just another per-type Field key, not a new node shape.

    `groups` is a PARTIAL `(section title, [field names])` list, same as `apply_fields_and_layout`:
    it is overlaid onto the draft's CURRENT section membership via `graph.merge_groups` before the
    rebuild, so a field the caller doesn't name keeps its current section instead of collapsing
    into `regroup_into_sections`'s own "Other" catch-all — the common "add one field to an
    existing section" call used to dump every OTHER field already in that section into "Other".

    Every one of the four layers is independently read-back verified; `missing` in any of them
    marks the whole report `isError` (never publishes on a partial landing).

    Collateral (A4, D5): `groups` runs `graph.regroup_into_sections`, a REBUILD that re-tiles
    every section at a uniform width — a custom grid an earlier `forge_apply_layout` wrote does
    not survive one call here. Every pre-existing field that actually moved is named in
    `collateral`, measured on the read-back against the pre-write draft (`_layout_collateral`),
    with `forge_apply_layout` in `remediation`. This is why forge_apply_fields is annotated
    `destructiveHint: True`; until D5 the tool carried the hint and reported none of the damage.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft

    before = field_names(draft)
    version = draft.get(_META_VERSION)
    requested = [s.name for s in specs]
    ignored = _changed_ignored(draft, specs)
    skipped = tuple(n for n in requested if n in before and n not in ignored.names)
    validations = validations or {}
    computed = computed or {}
    conditional = conditional or {}

    try:
        new = apply_changes(draft, specs)
        if groups:
            new = regroup_into_sections(new, merge_groups(new, groups))
        for fname, rules in validations.items():
            for rule in rules:
                new = add_field_validation(new, fname, rule["operator"], rule["rhs"],
                                           error_message=rule.get("error_message"))
        for fname, formula in computed.items():
            new = set_field_computed(new, fname, formula)
        for fname, cond in conditional.items():
            new = set_conditional_visibility(new, fname, cond["trigger_field"], cond["operator"],
                                             cond["rhs"])
    except (ValueError, NotImplementedError, KeyError) as e:
        return Err("verify", f"offline apply rejected the change set: {e}")

    added = tuple(n for n in requested if n not in before)
    if added or groups or validations or computed or conditional:
        written = client.put_draft(kind, flow_id, new, expect_version=version)
        if isinstance(written, Err):
            return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    live_names = field_names(read_back)
    verified = tuple(n for n in requested if n in live_names and n not in ignored.names)
    missing = tuple(n for n in requested if n not in live_names)
    collateral = _layout_collateral(draft, read_back, exclude=added)

    by_name = {v.get("Name"): v for v in read_back.values()
              if isinstance(v, dict) and v.get("Kind") == "Field"}

    val_verified: list[str] = []
    val_missing: list[str] = []
    for fname, rules in validations.items():
        fld = by_name.get(fname, {})
        live_rules: set[tuple[str, str]] = set()
        for cid in fld.get("FieldValidation::Criteria") or []:
            for condid in (read_back.get(cid, {}).get("Criteria::Condition") or []):
                c = read_back.get(condid, {})
                if isinstance(c.get("Operator"), str):
                    live_rules.add((c["Operator"], str(c.get("RHSValue"))))
        for rule in rules:
            key = f"{fname}:{rule['operator']}:{rule['rhs']}"
            (val_verified if (rule["operator"], rule["rhs"]) in live_rules else val_missing).append(key)

    computed_verified = tuple(n for n in computed if by_name.get(n, {}).get("Field::Expression"))
    computed_missing = tuple(n for n in computed if n not in computed_verified)

    cond_verified: list[str] = []
    cond_missing: list[str] = []
    for fname in conditional:
        fld = by_name.get(fname, {})
        col_id = fld.get("Column")
        col = read_back.get(col_id, {}) if isinstance(col_id, str) else {}
        (cond_verified if col.get("ColumnVisibility::Criteria") else cond_missing).append(fname)

    published = False
    all_ok = not (missing or ignored.entries or val_missing or computed_missing or cond_missing)
    if publish and all_ok:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return FullFieldsReport(
        flow_id=flow_id, added=added, skipped=skipped, verified=verified, missing=missing,
        changed_ignored=ignored.entries, collateral=collateral,
        remediation=ignored.remediation + (("forge_apply_layout",) if collateral else ()),
        validations_verified=tuple(val_verified), validations_missing=tuple(val_missing),
        computed_verified=computed_verified, computed_missing=computed_missing,
        conditional_verified=tuple(cond_verified), conditional_missing=tuple(cond_missing),
        meta_version=read_back.get(_META_VERSION), published=published,
    )


# =====================================================================================
# FIELD LIFECYCLE (F2). `graph.delete_nodes`, `graph.rename_fields` and `graph.set_required` have
# been pure, tested ops since the first wave and had ZERO callers — the live field surface was
# add-only, so one wrong field NAME meant rebuilding the whole flow. These three wrappers are the
# same GET -> capture _meta_version -> pure transform -> guarded PUT -> read-back -> audit ->
# optional publish shape as apply_fields/apply_step_permissions above, with ONE difference that
# matters: for a delete the audit unit is INVERTED. Success is the field being ABSENT on
# read-back, so reusing ApplyReport would make `missing` the good case and `verified` the failure
# — an audit nobody would read correctly twice. Each gets buckets that say what they mean.
# =====================================================================================


@dataclass(frozen=True)
class DeleteFieldsReport:
    """Output-invariant audit for a live field/table DELETE. INVERTED unit, see above.

    `deleted` = requested AND confirmed absent on read-back (the success bucket).
    `surviving` = requested, written, and STILL THERE on read-back — the loud failure, and the
    only thing that sets `isError`. Every requested name lands in exactly one of the two.
    `collateral` is what went WITH them: the column, its Permissions, its Events, its query
    definition, its formula — counted by node Kind off the same `graph.delete_closure` the
    deleter itself uses, never a separate guess at what should have gone.
    """
    flow_id: str
    fields: tuple[str, ...]
    tables: tuple[str, ...]
    deleted: tuple[str, ...]
    surviving: tuple[str, ...]
    collateral: tuple[str, ...]
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "fields": list(self.fields), "tables": list(self.tables),
            "deleted": list(self.deleted), "surviving": list(self.surviving),
            "collateral": list(self.collateral), "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.surviving),
        }


def _live_names(draft: Draft) -> tuple[set[str], set[str]]:
    """(every Field name, every table-host name) in a draft — the two namespaces a delete/rename
    audit reads back against. Table hosts are `Column{Type:"Model"}`, never Fields."""
    return (
        {v.get("Name", "") for v in draft.values()
         if isinstance(v, dict) and v.get("Kind") == "Field"},
        {v.get("Name", "") for v in draft.values()
         if isinstance(v, dict) and v.get("Kind") == "Column" and v.get("Type") == "Model"},
    )


def delete_fields(
    client: KfClient,
    flow_id: str,
    fields: tuple[str, ...] = (),
    tables: tuple[str, ...] = (),
    publish: bool = False,
    kind: FlowKind = "process",
) -> DeleteFieldsReport | Err:
    """GET draft -> REFUSE if anything that survives still references what is about to go
    (`graph.field_delete_blockers`) -> graph.delete_nodes offline -> guarded PUT -> read-back
    verify each name is genuinely ABSENT -> optional publish.

    The refusal is the point, not a formality. `delete_nodes` sweeps the field's own cluster and
    every LIST reference to it, but a scalar reference from a node it does not own — another
    field's computed formula, a branch condition, a conditional-visibility trigger, an event
    Script naming the id — survives, and a dangling scalar is the deterministic publish-500 (#18,
    zero diagnostics). Refusing with the remedy named beats writing a graph that publishes fine
    today and 500s on the next unrelated publish.

    Nothing is deleted unless EVERY requested name resolves: `delete_nodes` raises on the first
    unknown one, before the deepcopy, so a typo in a 5-name batch deletes none of the 5.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    try:
        blockers = field_delete_blockers(draft, fields, tables)
        if blockers:
            return Err("verify", "refusing to delete — these references would be left dangling: "
                                 + "; ".join(blockers))
        doomed = delete_closure(draft, fields, tables)
        new = delete_nodes(draft, fields, tables)
    except ValueError as e:
        return Err("verify", f"offline delete_nodes rejected the request: {e}")

    collateral = tuple(sorted(
        f"{n} {kind_name} node(s)"
        for kind_name, n in Counter(
            (draft.get(nid) or {}).get("Kind", "?") for nid in doomed).items()
    ))

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    # AUDIT BY NODE ID, never by name. `fields`/`tables` accept a NAME **or a raw node id** —
    # the documented way to disambiguate a name a form field and a table child both carry — and a
    # node id is never in the NAME namespace, so a name-keyed read-back reported every
    # id-addressed delete as gone whether or not the write landed, and then PUBLISHED on it. That
    # is a read-back that cannot fail, which is precisely what THE RULE forbids: a 200 and a clean
    # publish prove nothing. `graph.delete_closure` is the single derivation of "what goes" (the
    # same one the blocker audit reads), so asking it per token yields that token's own node ids
    # with no second, driftable walk.
    requested = tuple(fields) + tuple(tables)
    targets = [(n, (n,), ()) for n in fields] + [(n, (), (n,)) for n in tables]
    surviving = tuple(
        token for token, f_arg, t_arg in targets
        if any(nid in read_back for nid in delete_closure(draft, f_arg, t_arg))
    )
    deleted = tuple(token for token in requested if token not in surviving)

    published = False
    if publish and not surviving:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return DeleteFieldsReport(
        flow_id=flow_id, fields=tuple(fields), tables=tuple(tables), deleted=deleted,
        surviving=surviving, collateral=collateral,
        meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class RenameFieldsReport:
    """Output-invariant audit for a live field RENAME. TWO conditions per record, not one: the
    new name must be PRESENT and the old name must be GONE. Splitting them is deliberate —
    `stale` (new name landed, old one still there) is what a half-applied rename or a duplicate
    node looks like, and folding it into `missing` would report it as "the rename didn't happen"
    when in fact something worse did.

    `unchanged` is the third condition the two-test split cannot express: a rename whose old and
    new name are the SAME. The collision guard exempts it (renaming A onto A is not a collision),
    and the two-test read-back then classified it `stale` — new name present, old name also
    present, because they are one name — which is the WORST bucket, sets `isError`, and suppresses
    the publish, for a write that did exactly what was asked. A no-op is not a half-applied
    rename; it gets its own bucket, and a no-op whose name is not on the read-back at all is
    still `missing` (a real failure)."""
    flow_id: str
    renames: tuple[str, ...]      # "old -> new", the requested records
    verified: tuple[str, ...]     # new name present AND old name gone
    missing: tuple[str, ...]      # new name ABSENT on read-back
    stale: tuple[str, ...]        # new name present but the OLD one survives too
    unchanged: tuple[str, ...]    # old == new, and the name is present -> an honest no-op
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "renames": list(self.renames),
            "verified": list(self.verified), "missing": list(self.missing),
            "stale": list(self.stale), "unchanged": list(self.unchanged),
            "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing or self.stale),
        }


def rename_form_fields(
    client: KfClient,
    flow_id: str,
    renames: dict[str, str],
    publish: bool = False,
    kind: FlowKind = "process",
) -> RenameFieldsReport | Err:
    """GET draft -> graph.rename_fields offline -> guarded PUT -> read-back verify BOTH halves of
    every rename -> optional publish.

    A rename is the cheap fix for a wrong field name and the one field edit that is genuinely
    safe: the node id never changes, so per-step Permissions, `Field::Event` and any submitted
    data stay attached (a delete-and-recreate silently orphans all three). Only ROOT-model fields
    are renamed — a child-table column keeps its name, because names are not unique across a form
    and its tables; an unknown or ambiguous name raises before any write.

    A rename that would COLLIDE with a name already on the form is refused here rather than
    written: two fields sharing a name make every later name-keyed op (`apply_changes`' idempotent
    skip, `set_field_events`, `add_field_validation`) resolve to an arbitrary one of them. Renaming
    a field onto its OWN name is exempt from that guard — it collides with nothing — and is
    reported in its own `unchanged` bucket, not as `stale` (D9: the guard already knew a no-op was
    legitimate; only the read-back classification disagreed).
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    live_before, _tables = _live_names(draft)
    clashes = sorted({new_name for old, new_name in renames.items()
                      if new_name in live_before and new_name != old})
    if clashes:
        return Err("verify", f"refusing to rename onto name(s) already on this form: {clashes} — "
                             "two fields sharing a name make every name-keyed op resolve to an "
                             "arbitrary one of them")

    try:
        new = rename_fields(draft, renames)
    except ValueError as e:
        return Err("verify", f"offline rename_fields rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back
    live_after, _t = _live_names(read_back)

    wanted = tuple(f"{old} -> {new_name}" for old, new_name in renames.items())
    # A no-op (old == new) is read FIRST, because the two-condition test cannot express it: the
    # new name is present and so is the old one — they are the same name — which reads as `stale`,
    # the worst bucket, for a write that did exactly what was asked. Absent from the read-back it
    # is still `missing`; the no-op exemption is on the CLASSIFICATION, never on the audit.
    unchanged = tuple(f"{old} -> {n}" for old, n in renames.items()
                      if old == n and n in live_after)
    real = {old: n for old, n in renames.items() if old != n}
    verified = tuple(f"{old} -> {n}" for old, n in real.items()
                     if n in live_after and old not in live_after)
    missing = tuple(f"{old} -> {n}" for old, n in renames.items() if n not in live_after)
    stale = tuple(f"{old} -> {n}" for old, n in real.items()
                  if n in live_after and old in live_after)

    published = False
    if publish and not (missing or stale):
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return RenameFieldsReport(
        flow_id=flow_id, renames=wanted, verified=verified, missing=missing, stale=stale,
        unchanged=unchanged, meta_version=read_back.get(_META_VERSION), published=published,
    )


@dataclass(frozen=True)
class RequiredReport:
    """Output-invariant audit for a live Required sweep. `graph.set_required` is a SET operation,
    not a patch: every root field NOT named comes back optional. `cleared` is that collateral —
    the fields that were Required before this call and are not any more because the caller did
    not list them. It is reported, never silently applied, and never folded into `isError`
    (clearing is the documented semantics; being unable to see it was the bug)."""
    flow_id: str
    required: tuple[str, ...]     # the requested set
    verified: tuple[str, ...]     # read-back Required flag matches the request
    missing: tuple[str, ...]      # read-back Required flag does NOT match, OR a REQUESTED name is
                                  # absent from the read-back entirely -> loud failure either way
    cleared: tuple[str, ...]      # was Required before, is not now (collateral of the SET)
    meta_version: str | None
    published: bool

    def as_tool_result(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id, "required": list(self.required),
            "verified": list(self.verified), "missing": list(self.missing),
            "cleared": list(self.cleared), "meta_version": self.meta_version,
            "published": self.published, "isError": bool(self.missing),
        }


def _root_field_nodes(draft: Draft) -> dict[str, dict[str, Any]]:
    """ROOT-model field NAME -> node. The exact population `graph.set_required` rewrites."""
    root = draft.get("Root")
    return {v.get("Name", ""): v for v in draft.values()
            if isinstance(v, dict) and v.get("Kind") == "Field" and v.get("Model") == root}


def apply_required(
    client: KfClient,
    flow_id: str,
    required: tuple[str, ...],
    publish: bool = False,
    kind: FlowKind = "process",
) -> RequiredReport | Err:
    """GET draft -> REFUSE a Required flag the runtime can never satisfy -> graph.set_required
    offline -> guarded PUT -> read-back verify every root field's flag -> optional publish.

    SET semantics, not a patch: naming {"A"} makes A required and everything else optional. The
    fields that lose the flag are reported in `cleared` rather than changing silently.

    Two refusals before any write, both for the same reason — a Required field a human cannot
    type into makes its step permanently unsubmittable, and nothing downstream can move either
    (CLAUDE.md Visibility: "a Required field that is Hidden at its own step is still fatal"):
      * a COMPUTED field (`Field::Expression`) — the value is calculated, not entered. This is
        exactly how an auto-number and a Created-At mirror blocked step 1 live on 2026-08-05,
        the war story `graph.set_required`'s own docstring records.
      * a SequenceNumber field — stamped by the runtime, in a hidden column, never on screen.
    """
    draft = client.get_draft(kind, flow_id)
    if isinstance(draft, Err):
        return draft
    version = draft.get(_META_VERSION)

    root_fields = _root_field_nodes(draft)
    wanted = set(required)
    unsatisfiable = sorted(
        f"{name} ({'computed' if node.get('Field::Expression') else 'SequenceNumber'})"
        for name, node in root_fields.items()
        if name in wanted and (node.get("Field::Expression") or node.get("Type") == "SequenceNumber")
    )
    if unsatisfiable:
        return Err("verify", f"refusing to mark un-fillable field(s) Required: {unsatisfiable} — "
                             "a value the user cannot type makes that step permanently "
                             "unsubmittable (graph.set_required, CLAUDE.md Visibility)")

    was_required = {name for name, node in root_fields.items() if node.get("Required")}

    try:
        new = set_required(draft, wanted)
    except ValueError as e:
        return Err("verify", f"offline set_required rejected the spec: {e}")

    written = client.put_draft(kind, flow_id, new, expect_version=version)
    if isinstance(written, Err):
        return written

    read_back = client.get_draft(kind, flow_id)
    if isinstance(read_back, Err):
        return read_back

    # The audit unit is EVERY root field the read-back knows about, UNION every name the caller
    # REQUESTED. The union is the load-bearing half: iterating the read-back population alone
    # (what this used to do) means a requested name that was on the form before the write and is
    # NOT in the read-back lands in no bucket at all — `{"required": ["A"], "verified": ["B"],
    # "missing": [], "published": true}`. Every sibling here (delete_fields, rename_form_fields,
    # apply_fields) iterates the REQUESTED set; this one used to invert it. Keeping the read-back
    # side too is deliberate and is what `apply_required` alone needs: a SET operation that
    # flipped a field the caller never mentioned is exactly what this report exists to surface.
    live = _root_field_nodes(read_back)
    audited = sorted(set(live) | wanted)
    verified = tuple(n for n in audited
                     if n in live and bool(live[n].get("Required", False)) is (n in wanted))
    missing = tuple(n for n in audited
                    if n not in live or bool(live[n].get("Required", False)) is not (n in wanted))
    cleared = tuple(sorted(was_required - wanted))

    published = False
    if publish and not missing:
        pub = client.publish(kind, flow_id)
        if isinstance(pub, Err):
            return pub
        published = True

    return RequiredReport(
        flow_id=flow_id, required=tuple(required), verified=verified, missing=missing,
        cleared=cleared, meta_version=read_back.get(_META_VERSION), published=published,
    )
