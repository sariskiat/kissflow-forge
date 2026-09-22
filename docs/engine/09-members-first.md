## Members first

**An API-created flow has zero members**, so the acting user has no
permission on it at all, and the builder refuses to render it — this is the
single most common reason a freshly-created flow "does nothing" in the UI.

```
POST /flow/2/{acct}/{type}/{id}/member/batch
  body = [{_id, Name, Kind:"AppRole", Role, Permission}, ...]      -> 200, the only route that works
POST /flow/2/{acct}/{type}/{id}/member                             -> 404
PUT  /flow/2/{acct}/{type}/{id}/member/{id}                        -> update-only; attempting a create via PUT 500s
GET  /flow/2/{acct}/{type}/{id}/member                             -> harvest role ids off an EXISTING flow
```

⚠️ `**Permission` in that body must be a LIST, never a bare string** (proven
live 2026-08-07, node G review): `"Permission": "Editable"` is silently
iterated character-by-character by the request parser and 400s
`KISSFLOW_ERROR_04231 UnsupportedPermissionError`, naming each individual
LETTER as an invalid permission value — a genuinely confusing error shape if
you don't already know the cause. Always `"Permission": ["Editable"]`. 

⚠️ **Listing flows in an app (`GET /flow/2/{acct}/{type}?...`) MUST carry
`_application_id`, or it silently returns the WHOLE ACCOUNT's flows of that
type, not just the target app's** (confirmed live: 0 flows with the filter on
an empty app vs. 19 without it, same account, same moment). `app.infrastructure.kissflow.client. KfClient.list_flows` already does this correctly
(`?_application_id={app_id}&page_size=100`) — this note exists so nobody ever
hand-rolls the URL without it and silently starts reading (or, worse, later
writing against an id sourced from) a DIFFERENT app's flow.

⚠️ **A CORRECTED BELIEF, captured live 2026-08-07.** This used to say there is
no working route to list app roles from scratch, and to harvest role ids only
by reading the member list of a flow that already has members, or having a
human add one role in the builder UI first. That was wrong about the route —
it was actually describing a DIFFERENT, unrelated suffix (an "external list"
endpoint that genuinely does return `[]`). The real account-level route works:

```
GET /app_role/2/{acct}/list?page_number={n}&page_size=100
```

A bare array, paginated (a probe tenant had 356 AppRoles spread across 4
pages of 100/100/100/56 — stop paginating the moment a page comes back
shorter than the page size, no need to probe an explicit empty page after
that). Each record carries an `Applications` array scoping which app(s) it
belongs to — **each entry is a `{"_id": ..., "Type": "Application"}` dict,
not a bare id string**; filtering with a plain `app_id in record ["Applications"]` silently matches zero roles (found live writing this note)
— check each dict's own `_id` instead. `GET /app_role/2/{acct}/{role_id}`
returns one role's own detail, including its `Members` list — which the list route's records
never carry (verified across every record, not sampled). Do NOT generalise the rest of the
list record's key-set: most records are
`['Applications','Description','Name','Preference','UserCount','_application_id','_id']`,
but a small minority also carry `GroupCount`, so treat every key beyond
`_id`/`Name`/`Applications` as optional and use `.get`. `GroupCount` is nullable even on the
detail route. (An earlier version of this note claimed the list route never has `GroupCount`,
generalised from one sample — the same "absence in one sample is not absence in the API" trap
this file already records twice.) Harvesting from an existing flow's member
list (still below) remains a valid, still-working path; this account-level
route is simply the ADDITIONAL one that also works when no sibling flow has
ever been granted membership yet — as long as a human created at least one
AppRole for the app at some point (the account-level list only ever shows
roles a human already made in the builder UI; there is still no route that
creates one from nothing, see below).

- `**member/batch` Role names differ by flowtype.** A process flow accepts
the role name `DataAdmin`; a list flow rejects it and expects `Admin` or
`Member` instead — the error response itself names the valid set for that
flow type, so read a rejected batch's error before just retrying with a
different guess.
- `**member/batch`'s `Name` is separately validated against REAL, pre-existing
AppRoles** (found live 2026-08-06, node G): POSTing a synthetic `Name` (e.g.
`"Probe Admin"`) on an app with none defined 404s
`KISSFLOW_ERROR_00051 UserOrGroupDoesNotExistError`, `en_message: "The AppRole {Name} does not exist in your account."` — a DIFFERENT, more
specific check than the `Role` value alone. On an app with zero
builder-UI-created AppRoles anywhere (confirmed live on the app under test
as of 2026-08-06 — no longer this app's state as of 2026-08-07, see the
corrected belief above and the member/batch grant recipe further below),
`member/batch` is FUNCTIONALLY BLOCKED end to end — there is still no API
route that creates an AppRole, so this can only ever re-grant a role a
human already set up somewhere, harvested either from a flow's member list
or from the account-level AppRole list above.
- ⚠️ **The grant that actually lets the INITIATOR submit their own draft,
proven live 2026-08-07 (two-arm control on a throwaway flow):**
`"Permission"` must be `["InitiateItems"]`, not just any non-empty list and
never `[]`. `"Permission": []` still PUTs 200 on the `member/batch` call
itself — the grant looks like it worked — but the initiator still gets
refused when they try to submit their own item: `403 KISSFLOW_ERROR_050302 "You don't have permission to submit this item anymore."` Re-granting the SAME role/flow pair with `"Permission": ["InitiateItems"]` instead (a second `member/batch` call is an upsert, not
a duplicate) is what actually lets the walk proceed. A live reference app's
own AppRoles carry exactly `"Role": "DataAdmin", "Permission": ["InitiateItems"]`.
- ⚠️ **Membership alone is not enough — the step also needs a real ASSIGNEE,
or submit fails a different, more confusing way.** Granting membership with
`Permission: ["InitiateItems"]` but leaving every workflow step's assignee
as `role=None` still fails a first submit — not with the clean 403 above,
but with a generic `500 processError "An unexpected error has occurred"`,
persistent across 7 retries with backoff up to ~56s (ruled out as a
propagation delay). Wiring the SAME AppRole id as the step's own assignee
(`Resource{ValueType:"AppRole", Value:<role id>}`, written by passing that
id — not `None` — as the step's role when building the workflow) is what
turns the generic 500 into a working submit. Both pieces are required
together: membership with the right `Permission` grants the ability to act
at all, the assignee Resource is what tells the runtime WHO owns the step.
- ⚠️ **An unassigned step's item still has a derivable activity-instance id**
(re-verified live 2026-08-07, node G review) — the create response's own
`_activity_instance_id`, and a `myitems`-style listing's `_activity_id` +
`_activity_instance_id`. Nothing about it is missing; the only genuinely
absent piece is the `_current_context[0]._context_activity_instance_id`
MIRROR (confirmed unchanged across 5 reads 1s apart, not transient).
`live_aiid()` (dataplane.py) correctly REFUSES to fall back to the
create-response/myitems id, reporting its own "cannot submit without the
live aiid" Err rather than ever reaching a submit call — so `walk`/
`advance` never hit this. A caller that bypasses `live_aiid` and submits
with the create-response id directly on a membership-gapped step sees
`403 KISSFLOW_ERROR_050302` — a **permission** failure (no AppRole
assignee), not a missing-id one; that id is NOT the myitems
consumed-instance trap (two different reads — see the two-phase aiid
rule under Item data plane). Granting membership AND an assignee
(bullets above) avoids the 403 entirely, at which point hop 1 succeeds.
- A step's assignee is `Resource{ValueType:"AppRole", Value:<role_id>, Activity:<id>}`. Writing `ValueType:"User"` instead persists and even
publishes without error, but the builder appears to simply ignore it at
runtime — use AppRole for assignees, not User.
- **Assignees cannot be written before members exist** — publish fails with a
metadata error if you try. Members first, then assignees, every time, no
exceptions.
- ⚠️ **A repeat `groups` grant on `apply_add_role_users` is fail-closed, not
  re-sent.** This tenant exposes no group LIST on the role detail, only a
  nullable `GroupCount`, so a repeat grant can never be told apart from a
  fresh one by enumeration alone. When `GroupCount` already shows a group
  present (`> 0`), the write is refused and reported under its own
  `groups_refused` bucket (never `groups_already_present`, since presence was
  never proven) instead of being resent — a resend re-fans the notification
  out to every member again. Pass `force_regrant_groups=True` to override
  when granting a genuinely different group to a role that already carries
  one. See `apply_add_role_users` in `src/app/infrastructure/kissflow/client.py` and the
  `test_group_regrant_*` cases in `tests/test_client.py`.
- **Flow REPORTS have the same member surface as flows.** A report with an
empty member list renders as "you don't have access to this component"
inside any page that embeds its chart — the same `member/batch` shape fixes
it (`POST .../{type}/{flow}/report/{rid}/member/batch`). The report's own
definition and graph are reachable at `GET /process-report/2/{acct}/{flow}/{rid}`
and `GET /metadata/2/{acct}/process/{flow}/report/{rid}/draft` respectively.

