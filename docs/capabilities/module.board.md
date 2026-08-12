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
built-in category set hinted by `_disabled_category: ["Done","ReOpened"]`, and
a satellite `_default_workflow_id` object that 403s on every draft route even
for the creating API key (unresolved — treat board workflow as uncaptured, not
absent). A fresh case has **no style chain at all**, unlike process/form where
an incomplete chain is a render-breaker; whether the builder needs one on a
case is unverified.

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
- Member surface: same `member/batch` route shape, but the Role enum differs —
  `Admin` and `Member` exist (`DataAdmin`/`User`/`Participant` etc. rejected).
  Every guessed `Permission` literal was rejected (UnsupportedPermissionError);
  only `Permission: []` returned 200, which per the process precedent is
  presumptively a silent no-op grant. The valid Permission vocabulary for a
  case is UNCAPTURED — read it off the builder UI's own network tab before
  granting anything that must actually work.
- Application archive CASCADES: archiving the app archived every child flow,
  page, and system report in one call; delete then succeeds. Verify via the
  inventory route, never the delete response.

## Gotchas

Copilot **fabricated a success** on this module: asked for a Kanban view, it
replied with a specific-sounding view id while `CaseView` stayed `[]` and no
graph key changed — not reply-lag, a false claim. Stronger than the known
"reply lags the graph": diff the graph (and the flow-detail `CaseView`/
`Report` arrays, which live on flow-detail, not the draft) after EVERY claimed
board change, however concrete the reply sounds.
