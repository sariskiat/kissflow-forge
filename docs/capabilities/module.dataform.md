---
id: module.dataform
name: Dataform (flowtype "dataset")
status: captured
modules:
  process: "no"
  board: "no"
  dataform: "yes"
ui_path: "App builder > + New > Dataform"
routes:
  - "POST /flow/2/{acct}/dataset?_application_id={app}"
  - "GET /flow/2/{acct}/dataset?_application_id={app}&page_size=100"
  - "GET/PUT /metadata/2/{acct}/dataset/{id}/draft?_application_id={app}"
  - "POST /dataset/2/{acct}/{flow_id}"
  - "GET|POST /dataset/2/{acct}/{flow_id}/list"
shapes:
  - shapes/dataform_dataset_skeleton.json
params:
  - name: Name
    type: string
    required: true
    default: null
    constraints:
      - "flow name at create; the flow is born Live from this one call"
    depends_on: []
    status: proven-live
  - name: MaxRowCount
    type: integer
    required: false
    default: 50000
    constraints:
      - "native ceiling read off the flow record; behavior AT the ceiling never exercised"
    depends_on: []
    status: captured
  - name: MaxColumnCount
    type: integer
    required: false
    default: 100
    constraints:
      - "native ceiling read off the flow record; behavior AT the ceiling never exercised"
    depends_on: []
    status: captured
---

## What

A dataform is flowtype `dataset` — a typed data table with no lifecycle: a
bare `Model` (fields, sections, the same mandatory style chain as any flow)
with **zero workflow surface** (`ProcessDef`/`Activity`/`Permission` never
appear) and **zero membership gate** (record create/list works with an empty
member list — the one flow kind exempt from Members-first). Born Live; the
publish route 404s — draft edits ARE live immediately, same family as `list`.
Best mental model: a `list` flow generalized from "array of strings" to
"array of typed rows with named columns" — with a native hard ceiling of
`MaxRowCount: 50000` / `MaxColumnCount: 100` baked into the flow record.

Records live on their own third route family (`/dataset/2/...`, see routes) —
no submit/reject, nothing to advance. Every record's `Name` is a synthetic
system "Key" column, required and UNIQUE (duplicate → 409
DuplicateKeyException). Per-record GET/PUT/DELETE by id is uncaptured — all
route guesses 404'd; the `/list` response's empty `Sort`/`Filter` keys are
the flagged follow-up.

## Where

App builder "+ New > Dataform". Field building is byte-identical to
form/process — the engine's `apply_fields` runs unmodified with
`kind="dataset"`, producing the full Node-graph-invariants chain from the
first write.

## Best practice

- Reach for a dataform for reference/master data with no lifecycle — option
  catalogs, lookup masters, vendor/item tables. It skips two whole
  build-order phases: no members grant, no publish step. Fields → done.
- Reach for a process when records must move through steps, people, or
  approval gates — a dataform cannot route or approve anything.
- Plan the unique `Name` key: whatever business concept plays "the record's
  name" must genuinely be unique, or creation starts failing at runtime.
- Connect a process to a dataform with a Reference field:
  `QueryDefinition{LHSModel: <dataform id>, FlowType: "Dataset"}` —
  `FlowType` is the sole discriminator of the target kind (Process / Form /
  User / Dataset all confirmed). Page widgets bind through the same
  `view/*` `flow_type`/`flow_id`/`view_id` trio with `flow_type:"Dataset"`
  (write-proven; render unverified until a builder-UI check).

## Gotchas

Copilot is **inconsistent on dataforms** — in a 2-ask probe it substituted a
`Form` both times even when given the exact flowtype name and an explicit
create-from-scratch instruction (its own `QueryDefinition` read back
`FlowType:"Form"`). That is a reliability observation, not a capability
verdict: the copilot system is slow and inconsistent, so a miss in N attempts
never proves "cannot". Practical rule: after any copilot dataform ask, verify
the created flow's `Type` is `"Dataset"` on read-back; on a `Form`
substitution, retry with rephrasing or fall back to the engine's direct write
path, which is deterministic and fully proven here. Copilot also scattered 2
extra `list` flows as unmentioned side effects during the attempts —
inventory-diff the whole app after any copilot ask, as always.
