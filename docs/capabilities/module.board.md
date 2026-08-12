---
id: module.board
name: Board (flowtype "case")
status: captured
modules:
  process: "no"
  board: "yes"
  dataform: "no"
ui_path: "App builder > + New > Board"
routes:
  - "POST /flow/2/{acct}/case?_application_id={app}"
  - "GET /flow/2/{acct}/case?_application_id={app}&page_size=100"
  - "GET /flow/2/{acct}/case/{id}?_application_id={app}"
  - "GET/PUT /metadata/2/{acct}/case/{id}/draft?_application_id={app}"
  - "GET /flow/2/{acct}/case/{id}/member?_application_id={app}"
  - "POST /flow/2/{acct}/case/{id}/member/batch?_application_id={app}"
shapes:
  - shapes/board_case_skeleton.json
params:
  - name: Name
    type: string
    required: true
    default: null
    constraints:
      - "duplicate name behavior untested on case (process 400s FlowNameAlreadyExists)"
    depends_on: []
    status: proven-live
  - name: ItemType
    type: string
    required: true
    default: null
    constraints:
      - "\"Board\" | \"Case\" — both accepted; graphs byte-identical bar ids, echoed verbatim on flow-detail; looks cosmetic, semantic effect unverified"
    depends_on: []
    status: captured
  - name: Prefix
    type: string
    required: true
    default: null
    constraints:
      - "item-code prefix shown to users (PB-1, PB-2, ...); 2-char values proven, max length unconfirmed"
    depends_on: []
    status: proven-live
---

## What

A board is flowtype `case` — a data-record tracker with a platform-owned
lifecycle, NOT a custom step workflow. Create requires `Name` + `ItemType` +
`Prefix` (missing either extra 400s MissingRequiredFieldError) and the flow is
**born Live** — no publish step, same as a list flow. The draft arrives
**pre-scaffolded**: 3 default fields (Summary Text Required / Description
Textarea / Attachment), one "Add details" Section, rows/columns, ButtonRow.
Scaffolded nodes use FLAT ids (`Summary`, `Column001`); anything added later
uses the normal `Field_`/`Column_` prefix convention — both conventions
coexist in one graph. No `ProcessDef` exists in the draft; flow-detail instead
carries a built-in `Priority` enum (Critical/High/Medium/Low, Low default), a
built-in category set, and a satellite `_default_workflow_id` object that
403s on every draft route even for the creating API key. **RESOLVED (browser
round 2026-08-12): the board Workflow tab is a STATUS-LANE model, not a
ProcessDef** — fixed categories Not started / In progress / Done (optional,
toggle-enabled, "for review before closed") / Closed, each holding statuses
(defaults New / In progress / Closed) with "+ Add status" and "+ Connect a
flow to a status" (statuses can trigger flows). `_disabled_category:
["Done","ReOpened"]` matches the optional categories. Also RESOLVED: a fresh
case with **no style chain renders fine** in the builder — the style-chain
render-breaker rule is process/form-only, it does not apply to a case.

## Where

App builder "+ New > Board". API: the `case` routes above — `board`, `kanban`,
`caseflow`, `taskboard` all 404 (wrong door). The auto-created "All Items"
system TabularReport appears on a case exactly as on a process.

## Best practice

- "Board columns"/"Grid" is NOT a field type. No `Type:"Grid"` exists on this
  write path — a status column is an ordinary `Select` + `ReferredList`, the
  same pattern as any process Select. Route any "add board columns" ask to
  that pattern; the 6-unit row packing rule applies on a case identically.
- Reach for a board when the ask is "track cards through a few stages" — the
  form is free (pre-scaffolded), there is no workflow build order at all.
  Reach for a process when the ask is a multi-step routed approval with
  per-step assignees and gates; a case has no reachable equivalent surface.
- Member surface (RESOLVED, browser round 2026-08-12 — replacing the earlier
  "Permission vocabulary UNCAPTURED" flag): on a case the ROLE string is the
  whole grant and `Permission` stays `[]`. The builder's 5 tiers write:
  Read-only = `Viewer`, Initiate = `Initiator`, Edit = `Member`, Manage =
  `Admin` (all `Permission:[]`), No access = `DELETE .../member/{role_id}`.
  `Initiator` and `Viewer` are real case roles the earlier bisection missed.
- Application archive CASCADES: archiving the app archived every child flow,
  page, and system report in one call; delete then succeeds. Verify via the
  inventory route, never the delete response.

## Gotchas

Copilot **claimed a success that had not landed** on this module: asked for a
Kanban view, it replied with a specific-sounding view id while `CaseView`
stayed `[]` and no graph key changed in the polling window. The copilot
system is slow and inconsistent — a reply can outrun, lag, or misdescribe the
graph — so this is a verification rule, not a capability verdict: diff the
graph (and the flow-detail `CaseView`/`Report` arrays, which live on
flow-detail, not the draft) after EVERY claimed board change, however
concrete the reply sounds, and retry rather than conclude "cannot" on a miss.
