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

The role screen's tiers are FLOW-TYPE-DEPENDENT (browser-captured
2026-08-12, replacing the earlier 4-tier hypothesis): process = No access /
Initiate / Manage; board (case) = No access / Read-only / Initiate / Edit /
Manage; report = No access / View report / View report & form. Each tier
click writes `member/batch` (No access writes `DELETE
.../member/{role_id}` — a real removal route). Wire map, read back live:
process Initiate = `Member+[]` (NOT a no-op trap — it IS this tier), process
Manage = `DataAdmin+["InitiateItems"]`; case Read-only/Initiate/Edit/Manage
= `Viewer`/`Initiator`/`Member`/`Admin`, all `Permission:[]` — on a case the
ROLE string is the whole tier, and `Initiator`/`Viewer` are real case roles
(the earlier bisection that "rejected Viewer" was wrong).
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
- The tier → wire mapping is now WIRE-PROVEN (browser round 2026-08-12) —
  see What above. Submit permission still ALSO requires the acting user to
  be a member of the assignee AppRole — the creator is NOT auto-added, and
  its absence is THE reproducible submit-403 (KISSFLOW_ERROR_050302).
  RESOLVED (same day, user network capture + live proof): the add-user
  write is `PUT /app_role/2/{acct}/{role_id}?_application_id={app}` with
  `"Users": [<assignee object from GET /user/2/{acct}/assignee?q=...>]` —
  WRITE key `Users`, READ key `Members` (a `Members` write is silently
  ignored; that asymmetry defeated every earlier probe). Verify by reading
  back `Members`/`UserCount`.
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
