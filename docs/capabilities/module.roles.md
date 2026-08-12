---
id: module.roles
name: Roles & permissions (AppRole, member/batch two-axis grants, per-role defaults)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "App builder > Settings > Roles (4-tier permission screen)"
routes:
  - "POST /flow/2/{acct}/{type}/{id}/member/batch?_application_id={app}"
  - "GET /flow/2/{acct}/{type}/{id}/member?_application_id={app}"
  - "POST /flow/2/{acct}/{type}/{flow}/report/{rid}/member/batch"
  - "GET /app_role/2/{acct}/list?page_number={n}&page_size=100"
  - "GET/PUT /app_role/2/{acct}/{role_id}"
shapes:
  - shapes/app_role_grant.json
params:
  - name: Role
    type: string
    required: true
    default: null
    constraints:
      - "flow-type-scoped vocabulary: process Admin|DataAdmin|Member; form Admin|Member|Viewer; report Admin|Member — proven by bisection, the 04230 error never names the valid set"
    depends_on:
      - "the AppRole must already exist and be scoped to the app (create_app_role)"
    status: proven-live
  - name: Permission
    type: list[string]
    required: true
    default: null
    constraints:
      - "role-AND-flow-type-scoped: Admin=[] only; process Member/DataAdmin InitiateItems|View; form Member Edit|View|Delete|Share; form Viewer ReadOnly; report Member Edit|View|Share"
      - "re-POST REPLACES the array, not additive"
      - "MUST be a list — a bare string is iterated char-by-char and 400s naming each letter"
    depends_on: []
    status: proven-live
  - name: Preference
    type: object
    required: false
    default: null
    constraints:
      - "{DefaultPage: <page _id or \"Default\">, DefaultNavigation: <Navigation node Id or \"Default\">} via PUT /app_role/2/{acct}/{role_id}"
      - "sentinel ids write clean; whether the builder honors them at render is unverified"
    depends_on: []
    status: captured
---

## What

The builder's 4-tier role screen (No-access / Read-only / Edit / Manage) is
NOT a wire enum — nothing on the API speaks those words. The real mechanism
is TWO axes on the already-documented `member/batch` route: `Role` (what the
AppRole IS on the flow) and `Permission[]` (extra grants layered on top),
both with flow-type-scoped vocabularies (see params). "No-access" is the
AppRole simply absent from the member list — no explicit-deny exists.
"Views" have no entity of their own: a table/kanban/chart view IS a report
record (`ViewType: Tabular|IconCard|BarColumnChart|...`), permissioned via
the report `member/batch` route. Per-role Default page + Default navigation
live on the AppRole itself as `Preference`, writable via
`PUT /app_role/2/{acct}/{role_id}` — a newly proven write route.

## Where

App builder role screen at app level; per-flow sharing panels; per-view
(report) sharing panel. Engine side: `create_app_role`, `member/batch`
helpers, and now the `Preference` PUT.

## Best practice

- Grant by reading, not guessing: the vocabularies above were proven by
  bisection because error bodies never enumerate the valid set. Outside the
  proven (flow-type, Role) pairs, probe before writing.
- Admin needs no flags — every extra Permission word 400s on Admin. Wire
  Manage-tier asks as `Role:"Admin", Permission:[]`.
- The 4-tier → wire mapping is a HYPOTHESIS: before presenting a permission
  matrix to a user as "the builder's tiers", confirm by setting each tier by
  hand in the builder role screen once and diffing the member/batch body it
  writes.
- Remember replace semantics: build the full Permission array per grant;
  never POST a delta expecting a merge.

## Gotchas

Copilot role asks landed on attempt 1 both times in the probe, but the reply
text mismatched the graph both times ("Initiator" → `Role:Member,
Permission:[]`, which cannot submit; "Admin" → `Role:DataAdmin,
Permission:["InitiateItems"]`). Copilot is inconsistent in wording, not
incapable — read back the member list after every grant, and re-grant with
`InitiateItems` where submission must actually work (CLAUDE.md Members
first).
