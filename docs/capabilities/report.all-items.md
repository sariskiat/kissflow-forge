---
id: report.all-items
name: Process "All Items" report (the system report every process gets)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "App builder > process > Reports > All Items"
routes:
  - "GET /metadata/2/{acct}/process/{flow_id}/draft?_application_id={app}"
  - "GET /flow/2/{acct}/process/{flow_id}/report?_application_id={app}"
  - "GET /process-report/2/{acct}/{flow_id}/{report_id}"
  - "GET /metadata/2/{acct}/process/{flow_id}/report/{report_id}/draft"
  - "POST /flow/2/{acct}/process/{flow_id}/report/{report_id}/member/batch"
shapes:
  - shapes/report_all_items.json
params:
  - name: IsAllItemsReport
    type: boolean
    required: false
    default: false
    constraints:
      - "on the report LIST record only — the graph node spells the same fact IsAllItem"
    depends_on: []
    status: captured
  - name: IsAllItem
    type: boolean
    required: false
    default: false
    constraints:
      - "on the report GRAPH node only — do not 'fix' it to match IsAllItemsReport"
    depends_on: []
    status: captured
  - name: FieldId
    type: string
    required: true
    default: null
    constraints:
      - "on a ReportField node; must be a live process Field node id (or a name slug) — a stale id is the orphaned-reference case that breaks a deploy's copy-application step"
    depends_on:
      - "the process Field must exist in the process node graph"
    status: captured
  - name: ModelId
    type: string
    required: true
    default: null
    constraints:
      - "on a ReportField node; holds the parent PROCESS flow id, not a table model id"
    depends_on:
      - "the parent process flow must exist"
    status: captured
  - name: SharedWith
    type: list
    required: false
    default: null
    constraints:
      - "same member surface as a flow — an empty list renders the embedded chart as 'you don't have access to this component'"
    depends_on:
      - "the AppRole must already exist; member/batch cannot create one"
    status: captured
---

## What

The "All Items" report is the system report (`_is_system: true`) Kissflow
auto-generates for every process. It is recorded across THREE separate
surfaces — a list record, a saved-view definition, and its own node graph —
and the engine READS all three; it never builds a report (refused at compile,
ADR-0004).

Captured live 2026-08-17 from the dev tenant, process `Sample_Case_A14`
(app `Sample_Operations_Hub_COWORK_Pr_A00`).

## Where the process schema is recorded

One endpoint, the node graph:

```
GET /metadata/2/{acct}/process/{flow_id}/draft?_application_id={app}
```

The response is a flat id→node map keyed by `Root`. Node kinds here are the process side:
`Field`, `Column`, `Row`, `Section`, `Model` (table host), `ProcessDef`, `Activity`, `Node`,
`Expression`, `Event`, `Resource`, `Permission`. This is the schema the whole engine builds on
(see `docs/engine/01-node-graph-invariants.md` and `shapes/`). Field ids look like
`Field_4666bc2c5c`; every field the report can show lives here.

## Where the "All Items" report is recorded — three layers

### 1. Report record (the list)

```
GET /flow/2/{acct}/process/{flow_id}/report?_application_id={app}
```

One record per report. The system "All Items" record:

```json
{
  "_id": "Sample_Case_A14_All_Items",
  "Name": "Sample Case All Items",
  "ViewType": "Tabular",
  "ReportType": "TabularReport",
  "ChildTables": [{"_id": "Sample_Case_A14_All_Items", "Name": "Sample Case All Items"}],
  "_is_system": true,
  "SharedWith": [],
  "Permissions": ["Assignee", "View", "ViewAllReports", "..."]
  "IsAllItemsReport": true
}
```

`SharedWith` is the same member surface as flows (`POST .../report/{rid}/member/batch`).
`Permissions` here is a flag list, not the member structure.

### 2. Report definition (the view config)

```
GET /process-report/2/{acct}/{flow_id}/{report_id}
```

This is the SAVED-VIEW definition, not a node graph. Top-level keys:
`Appearance`, `Filter`, `Sort`, `PageSize`, `Style`, `Columns`, `Id`, `Name`, `Data`.

`Columns` is the real content — one object per visible column (the system report ships a default
of the process's first 10 fields, not every field):

```json
{
  "FieldId": "Field_4666bc2c5c",   // -> process Field node id (or a name slug like "Business_Unit_ID")
  "Name": "Case ID",
  "Type": "Text",
  "ProjectionFunction": null,
  "AggregationFunction": null,
  "IsSystemField": false,
  "Id": "Column-DzvJSM6jbR",
  "Width": null,
  "IsVisible": true
}
```

### 3. Report graph (the node graph)

```
GET /metadata/2/{acct}/process/{flow_id}/report/{report_id}/draft
```

A SECOND flat id→node map, keyed by `Root` (which points at the Report node id). Kinds:
`Report` (1), `Column` (one per visible column), `ReportField` (one per column), `User`
(PublishedBy).

**Report node:**

```json
{
  "Id": "Sample_Case_A14_All_Items",
  "Name": "Sample Case All Items",
  "Kind": "Report",
  "FlowType": "Report",
  "Model": "Sample_Case_A14",        // <- binds the report to its parent process flow
  "Type": "TabularReport",
  "ViewType": "Tabular",
  "Report::ReportField": ["ReportField-..."],
  "Report::Column": ["Column-..."],
  "IsAllItem": true
}
```

**Column node** (thin, a join record):

```json
{ "Id": "Column-DzvJSM6jbR", "Kind": "Column", "ReportField": "ReportField-DzvJSM6jbQ", "Report": "Sample_Case_A14_All_Items" }
```

**ReportField node** (the binding to the process schema):

```json
{
  "Id": "ReportField-DzvJSM6jbQ",
  "Kind": "ReportField",
  "FieldId": "Field_4666bc2c5c",      // <- the process Field node id
  "ModelId": "Sample_Case_A14",    // <- the process flow id
  "Report": "Sample_Case_A14_All_Items",
  "ReportField::Column": ["Column-DzvJSM6jbR"]
}
```

## The one relationship that matters

`ReportField.FieldId` → a process `Field` node id, and `ReportField.ModelId` → the process flow id.
That pair is the ONLY link between the report and the process schema. A report column whose
`FieldId` points at a field that no longer exists (renamed/deleted) is the orphaned-reference case
that breaks the deploy's `copy-application` step — see `skills/deploy/SKILL.md`.

## Best practice

Treat `ReportField.FieldId` as a reference that must be checked, not assumed.
Before a deploy, list the report's columns and confirm every `FieldId` still
resolves to a live process `Field` node — a column pointing at a renamed or
deleted field is the orphaned reference that kills `copy-application` with a
generic error (see `skills/deploy/SKILL.md`). Read the report graph
(`/metadata/.../report/{rid}/draft`) for the binding and the report definition
(`/process-report/...`) for what the user actually sees; they describe the same
columns through separate writes, so never infer one from the other.

A report with an empty `SharedWith` renders as "you don't have access to this
component" inside any page that embeds it — the flow `member/batch` shape fixes
it.

## Gotchas

- The list record says `IsAllItemsReport: true`; the graph node says `IsAllItem: true`. Both exist,
  different spellings, two different surfaces — do not "fix" one to match the other.
- The report graph's `Column` is a DIFFERENT node kind from the process graph's `Column` (a section
  holder). Same word, unrelated shapes.
- The report definition (`/process-report/...`) and the report graph (`/metadata/.../report/.../draft`)
  both describe the same columns but are separate writes; they are read here, not built by the engine
  (report creation is refused at compile — ADR-0004).
