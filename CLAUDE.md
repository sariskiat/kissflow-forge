# Kissflow Forge — Engine Manual

This file is the manual a fresh-context agent needs to build **any** Kissflow app
through this engine. It builds/edits Kissflow apps via the **undocumented**
internal `/flow` + `/metadata` builder API — not the documented public API, and
not anything published in Kissflow's own docs. Every rule below was captured
empirically, by building something in the Kissflow builder UI and reading back
what it actually wrote to the graph, never by guessing from a schema or from
what "should" be true. Treat every shape in this file as a proven capture, not
a spec: if the platform changes and a capture stops matching reality, recapture
it, don't patch around the mismatch.

The engine is dev-tenant only by construction and targets one app at a time via
config — no default app, no writing to anything that isn't an explicit dev
domain. Before any destructive build, produce a confirmation artifact (a
diagram or an HTML mockup of the intended shape) for a human to sign off on —
building blind against an undocumented API is how sessions get lost.

Read the sections in order; they're ordered the way a real build proceeds,
from "how do I know this worked" through node shapes, workflow, gating,
tables, computed fields, visibility, membership, the write-path gotchas, the
runtime item API, and finally app pages. The closing section is the proven
build order end to end.

## THE RULE

**An HTTP 200 and a clean publish prove nothing about whether the flow actually
works.** The Kissflow builder UI is a second, stricter validation layer on top
of whatever the write API accepted. A flow can accept every write, publish
clean, report itself live, and still render to an end user as nothing but an
error screen. Do not treat a 200 response, or a publish that returns success,
as evidence of anything beyond "the API accepted the bytes."

- Never claim a build works because the API returned 200. That is not
  evidence of a working flow, only of a syntactically acceptable write.
- The only reliable oracle is a **UI-built artifact to diff against**. When you
  are unsure whether a shape is right, build the equivalent piece by hand in
  the builder (or ask a human to), then diff your generated graph against that
  UI-built reference node by node, key by key. Guessing round after round is
  reliably slower than one real diff.
- When told "it still errors," do not re-diff the part of the graph you
  already checked. Stop and go find the layer you have not checked yet: the
  flow's own config payload, its membership, per-node keys you assumed were
  optional, or the UI's own network requests while it loads the broken page.

## Node-graph invariants

The write API enforces almost none of these. It will happily accept a graph
that is missing every one of them, return 200, and produce a flow that the
builder cannot render. These are the invariants the *builder*, not the API,
requires.

- **Every `Field` must carry a `Model` back-reference** (which model owns it)
  **plus a `CreatedAt` timestamp.** A Field missing `Model` will not render —
  the form silently drops it.
- **Node ids use capitalised prefixes**: `Field_`, `Column_`, `Row_`,
  `Resource_`. A lowercase `field_` id is wrong and will not be recognized as
  the node type it looks like.
- **Per-type keys** vary by field type and are easy to omit silently:
  - `Textarea` needs `AllowFormatting` (boolean).
  - `Number` needs `DefaultValue` and `Decimalpoint`.
  - `Attachment` needs `CaptureOnly` (boolean).
- **The style chain must exist on every flow**: `Model::Appearance` →
  `Appearance` → `Appearance::Style` → `Style`. If this chain is missing
  entirely (not just empty), the page fails to render, not just fails to look
  styled.
- **A Row is a 6-unit grid.** Field columns tile `(0,2) (2,4) (4,6)` — start
  and end units along a 6-wide row, at most 3 columns per row. Overflow one
  Row (say, columns all pinned at `Start=0`, or more than 3 columns crammed
  in) and it breaks rendering for the *whole* flow, not just that row.

```
Field  { Id:"Field_Sample01", Type:"Text", Model:<root model id>, CreatedAt:"<timestamp>" }
Row    { Column:<section id>, Row::Column:[Column_Sample01, Column_Sample02, Column_Sample03] }
  Column_Sample01 { Type:"Field", Start:0, End:2 }   # tile 1 of 3, max per row
  Column_Sample02 { Type:"Field", Start:2, End:4 }   # tile 2 of 3
  Column_Sample03 { Type:"Field", Start:4, End:6 }   # tile 3 of 3 — 6 units, fully packed
```
This Row is nested inside a section, so its parent key is `Column:<section id>`; a
root-level Row that instead holds a *section* column carries `Model:<root model id>`
in that same slot.

The mandatory style chain from the bullet above lives on the **root Model**,
not on any one section or column:

```
Model      { ..., Model::Appearance:[Appearance_Sample01] }
Appearance { Id:"Appearance_Sample01", Kind:"Appearance", Model:<root model id>,
             Appearance::Style:[Style_Sample01] }
Style      { Id:"Style_Sample01", Kind:"Style", Appearance:"Appearance_Sample01" }
```

A **second, optional** Appearance/Style pair can hang off a
`Column{Type:"Section"}` instead of the root Model — that's the separate,
per-section colour-styling chain (its token rules are covered in Pages and
Build order), and it does not substitute for the mandatory Model-level chain
above:

```
Column { Type:"Section" } --Column::Appearance--> Appearance --Appearance::Style--> Style
```

## Workflow

- A process needs `Model::ProcessDef` on the root Model, plus that same root
  Model's own `RootProcessDef` key holding the ProcessDef's **id** (a plain
  string reference — not a flag set on the ProcessDef itself), plus a
  `Button::Row` — also a key on the root Model, not on any one step —
  pointing at a Row whose own `Button` back-reference is the model id:

```
Model      { ..., Model::ProcessDef:[ProcessDef_Sample01], RootProcessDef:"ProcessDef_Sample01",
             Button::Row:[Row_Sample01] }
ProcessDef { Id:"ProcessDef_Sample01", Kind:"ProcessDef", WorkflowType:"Sequence",
             Model:<root model id>, ProcessDef::Activity:[...] }
Row        { Id:"Row_Sample01", Kind:"Row", Button:<root model id> }
```

  **A bare `ProcessDef` draft returns 500 on PUT even completely unmodified**
  — the presence of an incomplete `ProcessDef` is the cause of the 500, not
  whatever field-add you were actually trying to make. If a PUT 500s on a
  process draft, suspect the `ProcessDef` shape before suspecting your own edit.
- `WorkflowType: "Sequence"` means **the order of `ProcessDef::Activity` IS
  the flow** — there are no edge nodes for the forward path. A step simply
  follows the previous one in that array. `SendBackToInitiator` with
  `Name: null` is normal, not a bug.
- **`GotoTask` is the one backward edge node.** It is how a loop jumps back to
  an earlier step:

```json
{"Id":"Activity_Sample01","Kind":"Activity","NodeType":"GotoTask","Name":"Goto-<target step name>",
 "ProcessDef":"<owning branch id>","CreatedAt":"<timestamp>","Goto":"<target Activity id>"}
```

  The back-reference is bidirectional: the TARGET activity gets
  `"Goto::Activity":["<goto activity id>"]`. `GotoTask` sits LAST in
  `ProcessDef::Activity`. It renders no form of its own, so it carries zero
  Permissions — exclude it from any permission-matrix count, the same
  treatment as a `Parallel` gateway. A bare `GotoTask` with no attached
  condition loops forever; see Expressions for how the condition attaches.

  ⚠️ A CORRECTED BELIEF on "sits LAST", found live 2026-08-06 building node G's `add_goto_task`
  (kfforge/graph.py) + Robot acceptance suite. The line above was captured off a MINIMAL 2-node
  illustration (one UserTask + the GotoTask, no Start/End shown), where "last" and "last of the
  two elements shown" were indistinguishable. Against a REAL workflow with a terminal EndEvent,
  appending the GotoTask strictly last — AFTER the EndEvent too — PUTs 400
  `KISSFLOW_ERROR_00011 InvalidArguments` (a field-less, unhelpful error; isolated via a two-arm
  live experiment: identical draft, only the insertion point differs). The position that PUTs 200
  is last among the REAL activities, immediately BEFORE a trailing EndEvent. `add_goto_task`
  inserts there when the chain ends in one, and only plain-appends (matching the original minimal
  capture exactly) when it doesn't.
- **`IsSuspended` skips a step at runtime without deleting it:**

```json
{"Kind":"Activity","Name":"<step name>","IsSuspended":true,"SuspendedAt":"<timestamp>"}
```

  A suspended Activity stays in `ProcessDef::Activity` and keeps its
  Permissions, but the runtime walks straight past it — an in-flight item goes
  from the previous step to the next un-suspended one. This is the safe way
  to slim a live workflow: deleting a step orphans any item sitting on it,
  suspending does not.
  **Consequence for visibility:** a section whose only owning step is a
  suspended one becomes editable nowhere at all, and a Required field living
  in such a section makes that field's own step permanently unsubmittable
  (see Visibility) — suspending a step doesn't just skip it, it can silently
  strand whatever visibility depended on that step alone.
- **Rebuilding a workflow strands in-flight items.** A full workflow rebuild
  replaces every Activity, so anything sitting on an old step now points at
  an activity id that no longer exists — symptom: the form opens read-only
  with a message like "update field values," which has nothing to do with the
  form's own permissions. Check `_current_step` on in-flight items against the
  live Activity list before blaming the form. The same rebuild also **deletes
  every `Permission` node** — any step-visibility matrix you had configured is
  gone and must be rebuilt after any workflow rebuild, every time.

## Expressions

An `Expression` node is not always a branch condition — its owner key tells
you what it actually is, and **the owner key is one of three**, each meaning
something different:

| Owner key    | Meaning                                    |
|--------------|---------------------------------------------|
| `ProcessDef` | a branch condition (which path an item takes) |
| `Activity`   | a `GotoTask` loop condition (see Workflow)     |
| `Property`   | a value-generator prefix (e.g. an auto-number scheme) |

Always branch on which key is present before treating an `Expression` as
routing logic — treating a `Property`-owned Expression as a branch condition
misreads a formatting rule as broken routing.

The full node shape is a small AST, not a flat value:

```
owner --Expression--> Expression{ExpressionStr, Expression::Node:[root]}
root Node{Type:"Function", Value:"=", Syntax:"Infix", Node::Node:[lhs, rhs],
          DataType:"Boolean", FieldRefCount:<n>}
  lhs Node{Type:"Field",  Field:<field id>, DataType:"String", Node:<parent>}
  rhs Node{Type:"Static", Value:"Option A", DataType:"String", Node:<parent>}
Field{..., "Field::Node":[every node that references this field]}   # bidirectional, must be maintained
```

- **`ExpressionStr` is only a readable mirror** of the AST (and it references
  fields by id, not by name) — it is not itself evaluated. Build the `Node`
  tree; do not stop at writing the string.
- **A Boolean literal is a zero-arg `Function` node, not a `Static`.** A
  literal `false` is:

```json
{"Type":"Function","Value":"false","DataType":"Boolean","Category":"Boolean","Node":"<parent>"}
```

  No `Node::Node`, no `Syntax` key. A `Static` node with the string `"false"`
  is a different type entirely and will never match a Boolean comparison.
- **`Category` on the root node is the class of the operands being compared,
  not the result type.** Every root is shaped
  `{Type:"Function", Value:"=", Syntax:"Infix", DataType:"Boolean", FieldRefCount:<n>}`
  — `DataType` is always `"Boolean"` because `=` always produces a boolean —
  but `Category` is `"String"` when comparing two strings/Selects and
  `"Boolean"` when comparing two Booleans. Set `Category` from what the
  operands are, never copy it from `DataType`.
- **Literals are case-sensitive and never validated by the write API.** A
  typo'd option value (wrong case, extra space, anything not byte-identical to
  the real option) writes fine, publishes fine, and simply never fires — the
  branch or gate silently goes the other way forever. **Never guess a
  literal — read it.** Fetch the live list of valid option values for that
  field before writing any literal into an Expression, and compare
  byte-for-byte.
- **Rewiring a condition to point at a different field is six edits, not
  one:**
  1. the Field node's `Field` reference,
  2. that node's `DataType`,
  3. the literal node (value and, if the type changed, its shape),
  4. the root's `Category`,
  5. the `ExpressionStr` mirror,
  6. moving the `Field::Node` back-reference off the old field and onto the new one.

  Miss any one of the six and you get a graph that looks right on casual read
  but silently evaluates against stale data.

## Gate polarity

**Always gate a loop on a Boolean field, never on an optional Select.** The
two fail in opposite, and very differently dangerous, directions:

- A blank optional Select never equals the literal you're comparing it to, so
  the equality test is false — and false is what lets an item leave the loop,
  so the item **escapes the loop** unnoticed, having done none of the rework
  the loop existed for.
- The condition that actually gets evaluated lives on the `GotoTask`'s own
  `Activity::Expression`, and it gates **taking the backward jump**, not
  leaving the loop — condition true means "jump back," i.e. the item stays
  put. The proven live pattern is `<Boolean field> = false()` (a zero-arg
  `Function` literal, see Expressions): an unticked Boolean defaults to
  `false`, so `false = false()` evaluates true, the Goto fires, and the item
  **stays in the loop** — only once a human ticks the box does
  `true = false()` evaluate false, the Goto stops firing, and the item moves
  on.

**Fail closed.** A trapped item is visible on a dashboard and fixable by a
human. A silently-skipped rework round is invisible and unfixable after the
fact — nobody knows to go looking for it. When in doubt about which way a gate
should fail, make it the Boolean, and make the failure mode "stuck," not
"skipped."

## Tables

**A table is a nested `Model`, not a field type.** There is no "table" field —
a table is an entire child Model hung off a host column:

```
root Model  --Model::Model-->  ["Sample_Table"]
Row --Row::Column--> Column { Type:"Model", AllowImport, Column::Model:[<table id>], MaxRow:<n> }   # host row (root-level) + host column, full row width
Model  { Id:<table id>, Model:<parent>, Column:<host>,
         Model::Row:[1 schema row], Model::Field:[...] }
child Field { ..., Model:<table id> }                                          # a normal Field, parented to the table
```

- **The row cap lives as `MaxRow` on the HOST column**, not as a validation
  rule on a child field. It's native — no scripting needed to enforce a max
  row count. Don't confuse it with a string-length rule on a child field,
  which is a different kind of condition entirely.
- Child columns are `Start=0/End=0` — the 6-unit row grid from Node-graph
  invariants does not apply inside a table; a table's own columns aren't
  positioned that way.
- **A table host cannot live inside a Section.** Wiring the host Row into a
  Section's own `Column::Row` still returns 200 on write and 200 on publish —
  and the section then renders completely empty in the builder anyway. A
  table host must sit in its own root-level Row, never nested inside a
  Section's row. The working pattern is a Section used purely as a banner
  immediately above the table, with the table's own root Row directly below
  it — not the table nested inside the section. That root Row must itself be
  **registered in the root Model's own `Model::Row` list** — the same place
  the table's own id lands in `Model::Model` — or the Row exists as a node
  but isn't actually part of the form's layout, no matter how correctly its
  own columns are wired.

## Field events

Kissflow has **no formula or computed field type.** Any computed value is done
with a field event: a script the client SDK runs in response to a field
change.

```
Field { ..., "Field::Event": ["Event_Sample01"] }        # back-reference, bidirectional
Event { Id, Kind:"Event", Field:<field id>, Trigger:"onChange", Script:"<raw JS>" }
```

`onChange` is the confirmed trigger string. The trigger name likely varies by
the *source* field's type in other cases (a select-style field may use an
"on select" style trigger, a click-style widget an "on click" style trigger)
but only `onChange` has actually been captured live — treat any other trigger
string as unverified until you've captured it the same way, off a real
builder-authored event.

Six field types never get an event at all — the builder offers no Event tab
for any of them, so there's no trigger string to find no matter how hard you
look: **Attachment, Image, Rich text, Signature, Sequence number,
Geolocation.**

Two rules the event editor enforces, both learned by having a paste rejected:

- The event box is parsed as a **plain function body**, not a module — a
  top-level `await` is a `SyntaxError` in that context. Wrap everything in an
  immediately-invoked async function: `(async () => { ... })();`
- **`kf` is already injected into the event's scope. `KFSDK` is undefined
  here** — calling `KFSDK.initialize()` fails immediately. (`KFSDK.initialize()`
  is for a different host entirely — custom components — not a field event.)

**Always attach the event to the SOURCE field, never to the computed target
field.** An event on the target field only fires when a human edits that
field directly, which never happens for a value that's supposed to be
computed. The SDK available inside an event is read-and-update only — it can
read fields and write field values, but it cannot create or delete fields,
rows, or tables. It fills things in; it doesn't build structure.

## Visibility

Per-step visibility has **two independent levers**, and both write the same
node shape:

```
Permission { Id, Kind:"Permission", Column:<column id>, Activity:<activity id>,
             Permission:"Editable"|"ReadOnly"|"Hidden" }
```

Back-references are bidirectional (`Column::Permission[]` and
`Activity::Permission[]`). Neither `GotoTask` nor a `Parallel` gateway nor
`SendBackToInitiator` carries any Permissions — they render no form, so there
is nothing to gate.

- **`Column` may be a SECTION column, not just a field column.** "Hide this
  whole section at this step" writes exactly one Permission whose `Column` is
  the *section's* column, not one Permission per field inside it. Using the
  section-level lever instead of one Permission per field per step is roughly
  an order of magnitude cheaper in node count for the same visible effect —
  prefer it whenever an entire section shares one visibility rule.
- Both layers can coexist on the same flow — field-level Permissions on
  individual fields, section-level Permissions on their container — without
  either overwriting the other. **Precedence between a section-level Hidden
  and a field-level Editable on a field inside that section is unverified** —
  don't rely on one silently overriding the other until you've captured which
  wins.
- Hidden columns (for example the host column behind a sequence-number style
  auto-generated field) and sequence-number columns themselves take no
  Permissions at all — a hidden column has no per-step visibility to set, so
  its absence from the matrix is not a gap.
- **`StartEvent` is position 0.** The very first section a user sees must
  list `Start` as one of its owning steps, or the submission form renders
  empty — there is nothing conceptually wrong with the form in that case, it
  is simply not visible at the step the user is standing on.
- **Required is scoped by per-step visibility.** A step's submit validation
  only enforces the Required fields that are actually visible at that step —
  marking a later-step field Required does not block submission of an earlier
  step. The inverse is the dangerous direction: **a Required field that is
  Hidden at its own step is still fatal** — nothing can ever satisfy it, and
  nothing downstream can submit past it either.

Any full workflow rebuild deletes every Permission node (see Workflow) — treat
"just rebuilt the workflow" as an automatic cue to rebuild the visibility
matrix next, every time, not just when something looks visibly wrong.

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

⚠️ **`Permission` in that body must be a LIST, never a bare string** (proven
live 2026-08-07, node G review): `"Permission": "Editable"` is silently
iterated character-by-character by the request parser and 400s
`KISSFLOW_ERROR_04231 UnsupportedPermissionError`, naming each individual
LETTER as an invalid permission value — a genuinely confusing error shape if
you don't already know the cause. Always `"Permission": ["Editable"]`.

⚠️ **Listing flows in an app (`GET /flow/2/{acct}/{type}?...`) MUST carry
`_application_id`, or it silently returns the WHOLE ACCOUNT's flows of that
type, not just the target app's** (confirmed live: 0 flows with the filter on
an empty app vs. 19 without it, same account, same moment). `kfforge.client.
KfClient.list_flows` already does this correctly
(`?_application_id={app_id}&page_size=100`) — this note exists so nobody ever
hand-rolls the URL without it and silently starts reading (or, worse, later
writing against an id sourced from) a DIFFERENT app's flow.

There is no working route to list app roles from scratch (the obvious
"external list" endpoint for roles returns an empty array) — harvest role ids
by reading the member list of a flow that already has members, or by having a
human add one role in the builder UI first so you have an id to reuse.

- **`member/batch` Role names differ by flowtype.** A process flow accepts
  the role name `DataAdmin`; a list flow rejects it and expects `Admin` or
  `Member` instead — the error response itself names the valid set for that
  flow type, so read a rejected batch's error before just retrying with a
  different guess.
- **`member/batch`'s `Name` is separately validated against REAL, pre-existing
  AppRoles** (found live 2026-08-06, node G): POSTing a synthetic `Name` (e.g.
  `"Probe Admin"`) on an app with none defined 404s
  `KISSFLOW_ERROR_00051 UserOrGroupDoesNotExistError`, `en_message: "The
  AppRole {Name} does not exist in your account."` — a DIFFERENT, more
  specific check than the `Role` value alone. On an app with zero
  builder-UI-created AppRoles (confirmed live on the app under test),
  `member/batch` is therefore FUNCTIONALLY BLOCKED end to end — there is no
  API route that creates an AppRole either, so this can only ever re-grant a
  role harvested from a flow where a human already set one up.
- **⚠️ A CORRECTED MECHANISM, re-verified live 2026-08-07 (node G review).** An
  earlier version of this note claimed an unassigned step's item had NO
  derivable activity-instance id "so advance/submit can never even derive a
  live aiid to try, let alone 403." That is WRONG and would send a future
  agent looking in the wrong place. What is actually true, confirmed by
  independently re-running the probe:
  - The activity instance DOES exist and IS exposed — in the create
    response's own `_activity_instance_id`, and in a `myitems`-style listing's
    `_activity_id` + `_activity_instance_id`. Nothing about it is missing or
    unreachable.
  - Submitting WITH that real id returns `403 KISSFLOW_ERROR_050302`,
    `"You don't have permission to submit this item anymore."` — a
    **permission** failure, not a missing-id failure. The cause is the step
    has no AppRole assignee the API user belongs to (see above: a fresh app
    has no grantable AppRole at all).
  - What IS genuinely absent, on an unassigned step, is only the
    `_current_context[0]._context_activity_instance_id` MIRROR (Item data
    plane's own documented source for `live_aiid`) — not transient, unchanged
    across 5 reads 1s apart. `live_aiid()` (dataplane.py) correctly REFUSES to
    fall back to the create-response/myitems id instead — that fallback is
    exactly the "myitems consumed-instance" trap this whole module exists to
    avoid (see Item data plane) — so it reports its own "cannot submit without
    the live aiid" Err rather than ever reaching a submit call. The 403 above
    is what a caller sees if it bypasses `live_aiid` and submits with the
    create-response id directly; `walk`/`advance` never do that, so in
    practice this pack's own code stops one step earlier, at `live_aiid`'s
    refusal, for the SAME underlying reason (no AppRole membership).
- A step's assignee is `Resource{ValueType:"AppRole", Value:<role_id>,
  Activity:<id>}`. Writing `ValueType:"User"` instead persists and even
  publishes without error, but the builder appears to simply ignore it at
  runtime — use AppRole for assignees, not User.
- **Assignees cannot be written before members exist** — publish fails with a
  metadata error if you try. Members first, then assignees, every time, no
  exceptions.
- **Flow REPORTS have the same member surface as flows.** A report with an
  empty member list renders as "you don't have access to this component"
  inside any page that embeds its chart — the same `member/batch` shape fixes
  it (`POST .../{type}/{flow}/report/{rid}/member/batch`). The report's own
  definition and graph are reachable at `GET /process-report/2/{acct}/{flow}/{rid}`
  and `GET /metadata/2/{acct}/process/{flow}/report/{rid}/draft` respectively.

## Write path

- **Snapshot the draft before any write** to a flow you did not just create
  yourself. To restore from a snapshot, stamp the flow's CURRENT
  `_meta_version` onto the snapshot body before you PUT it back — PUTting a
  stale `_meta_version` returns a metadata-conflict error, not a silent
  overwrite. Republish afterward so the live version actually matches the
  restored draft. **`_meta_version` changes only on publish**, never on a
  plain draft save — it is not a save counter, don't treat two draft saves as
  two versions.
- **Archive before deleting a process** — deleting an unarchived process
  fails outright; archive first, then delete. Forms (non-process flows)
  delete directly, no archive step needed.
- A `User`-type field blocks publish outright. Avoid it until its exact
  required shape has been captured off a builder-authored example.
- **Never synthesize a `ReferredList` wiring.** The ids a `ReferredList`
  points at do resolve against the account's list inventory, and option
  values are readable through the runtime items route (see Item data plane),
  but the wiring shape of a *new* `ReferredList` reference has not been
  captured — only reuse one a human already wired in the builder, never
  invent the reference yourself.
- **Style tokens are not validated by the write API.** A completely bogus
  token name PUTs 200, publishes 200, and reads back verbatim — and then
  fails silently at render, with no error anywhere in the chain to tell you
  it was wrong. Never guess or probe token names against the API; read the
  real token names off the builder's own style dropdown. Setting a style
  property to `None` (rather than omitting it) is the only way back to the
  platform's own default — leaving the builder's defaults alone writes
  nothing at all, since Kissflow persists only non-default style values.

## Item data plane

The runtime item walk, on the documented (non-builder) API:

```
create   POST /process/2/{acct}/{flow}                          -> _id + first activity-instance id
fill     PUT  /process/2/{acct}/admin/{flow}/{iid}              -> {field_id: value, ...}
submit   POST /process/2/{acct}/{flow}/{iid}/{aiid}/submit      -> advance one step
reject   POST /process/2/{acct}/{flow}/{iid}/{aiid}/reject      -> {"Comment": "..."}; sets status Rejected
detail   GET  /process/2/{acct}/admin/{flow}/{iid}              (the non-admin path 404s)
fields   GET  /process/2/{acct}/{flow}/fields                   -> all runtime fields, no option values
options  GET  /flow/2/{acct}/list/{list_id}/items               -> bare array of valid option strings
lists    GET  /flow/2/{acct}/list?page_size=100                 -> inventory of every list in the app
```

- **The aiid trap:** the activity-instance id returned by a "my items"-style
  listing is the initiator's already-CONSUMED instance — submitting or
  rejecting against it fails with an "already used" style error. The LIVE
  activity-instance id is nested inside the detail response, at
  `detail._current_context[0]._context_activity_instance_id`. Always fetch
  detail and use that id, never the one off a list view.
- **Select values PUT 200 and silently discard when the value isn't in the
  field's option list** — the write succeeds, and a read-back shows the field
  as empty. **Always read back after writing a Select**, and validate the
  value against the live option list before you ever write it (see
  Expressions for the identical trap on literals).
- Child-table rows surface in the item detail under a key shaped
  `Table::<child model id>` — the key is present only when rows actually
  exist; its absence means no rows, not "no such table." Rows are written
  through the same admin fill route, keyed by the child fields' own ids.
  `PUT {"Table::<id>": []}` returns 200 and clears nothing — an empty-array
  write is not how you delete rows; deleting the child schema is the only
  proven way to purge orphaned ones.
- Submit permission follows the step's AppRole assignment — the acting API
  user must actually be a member of that role (see Members first); there is
  no API route that grants role membership itself, only the builder UI does.
- A handful of routes are confirmed dead ends, worth knowing so nobody
  re-probes them: a dataset-style product surface 403s outright (the account
  tier doesn't include it); a legacy list-flow path is pure front-end with no
  API behind it; per-field lookup/reverse-lookup routes 500 on any editable
  Select; and no API route exists to reassign an in-flight activity to a
  different user.

## Pages

App-level artifacts live under a distinct flowtype: `application`. The
navigation chain is `GET/PUT /metadata/2/{acct}/application/{app_id}/draft` →
`Navigation` (one per role's menu set) → `Menu` → `FieldMapping` →
`Property{Type:"Page", Value:<page_id>}`. The application root also carries a
`DefaultPage`.

**Creating/deleting the APPLICATION itself (not a page within one) — captured
live 2026-08-06, node G's forge_create_app probe.** Tried the obvious shapes;
only ONE worked, ≤3 attempts:

```
POST   /flow/2/{acct}/application         {"Name": "..."}    -> 200 {_id, Type:"Application", Status:"Draft"}
GET    /flow/2/{acct}/application?page_size=100                -> the true inventory (mirrors the page-list route)
POST   /flow/2/{acct}/application/{id}/archive                 -> 200
DELETE /flow/2/{acct}/application/{id}                          -> 400 KISSFLOW_ERROR_04602 unless archived first
```
`POST /metadata/2/{acct}/application` and `POST /flow/2/{acct}/app` both 404
(wrong door). Same archive-then-delete rule as a process. Duplicate `Name` on
create 400s `KISSFLOW_ERROR_04204 FlowNameAlreadyExists`.

⚠️ **A REFUTED CLAIM, deleted 2026-08-07 (node G review).** This note used to
say a freshly-created application gets built-in `Admin`/`User` AppRoles
auto-provisioned, inferred from a `PageAccess` list seen in one archive
response. Independently re-tested and disproven: a throwaway app's own member
roster (`GET .../application/{app}/member`) held exactly one entry — the
creating USER — and zero AppRole entries. `member/batch` against that app with
`Kind:"AppRole"` and `Name` of `"Admin"`, `"User"`, or `"Member"` each 500s
`FlowError`. What is actually proven, app-agnostic:
- A freshly-created (or otherwise fresh) application carries **no grantable
  AppRole** — there is nothing to `member/batch` a step's assignee onto yet.
- `member/batch` at the APPLICATION level with an `AppRole` name 500s
  `FlowError` regardless of which built-in-sounding name is tried.
- A step assignee written as `Resource{ValueType:"User", Value:<real user
  id>}` persists and PUBLISHES cleanly (CLAUDE.md elsewhere already notes the
  builder appears to ignore `ValueType:"User"` at render time) but does NOT
  confer runtime submit permission either: with a User-typed assignee AND
  that same user granted via `member/batch` (⚠️ `Permission` must be a
  **list**, e.g. `["Editable"]` — a bare string is iterated character-by-
  character and 400s `KISSFLOW_ERROR_04231 UnsupportedPermissionError`,
  naming each letter as an invalid value), `_current_context[0]` STILL lacked
  `_context_activity_instance_id` and submit STILL returned `403
  KISSFLOW_ERROR_050302` on a real live item.
- There is no API route that creates an AppRole, or adds a user to one — both
  are builder-UI-only, matching the "no route to list app roles from scratch"
  note above. This is a structural gap, not something a build script can work
  around with a different request shape.

Each page is its own draft/publish unit:

```
GET/PUT /metadata/2/{acct}/application/{app}/page/{page_id}/draft
POST    /metadata/2/{acct}/application/{app}/page/{page_id}/publish     # page-level publish
```

**Page CRUD lives on a different surface than the draft:**
`GET /flow/2/{acct}/application/{app}/page` is the true inventory of live
pages — always page this with `?page_size=100`, the default page size is
small. `POST` the same path with `{"Name": "..."}` creates a virgin page (four
nodes: a `Page`, one `Container` of `Type:"Body"`, an empty `Style`, and a
`User`) — creating via the API does not touch navigation; a human still has
to add the Menu/FieldMapping/Property into whichever Navigation is currently
selected in the builder. `DELETE` on the same path returns a success response
for *any* id, including ids that were never real, and a deleted page's own
draft route keeps returning 200 afterward too (storage lingers) — **the page
LIST route is the only truth surface** for what pages actually exist; never
trust a delete response or a draft GET as proof either way.

The page graph itself is a Container/Component tree, plus supporting node
kinds:

- **Layout**: `Page` → a `Container` tree (`Type: Body|Container`, real flex
  layout values: direction, gap, padding).
- **Widgets** are `Component` nodes, identified by a `Script.web` string (see
  the palette below), configured through `FieldMapping`/`Property` pairs.
- **Styling**: `Style{Container|Component, Value:{"<key>":{...}}}`. Keys are
  CSS-shaped (background, text color, icon color, corner radii, per-side
  border widths). **Dimensional values are always raw CSS strings** — padding,
  gap, width, and radius keys hold literal strings like `"24px"`, `"100%"`,
  `"auto"`, on every page captured, no exceptions seen. **Color values accept
  two different shapes, and both render live**: raw hex as
  `{"value":"#RRGGBB"}` (122 instances, confined to the 2 pages this engine
  API-restyled directly) and design-token refs as `{"ref":"Color.Xxx.Nnn"}`
  (1394 instances, spread across the capture and dominant on 15 of the 17 pages
  — the platform's own assistant-built page alone accounts for 227 of them, and
  zero hex) — both proven rendering in the same 17-page capture. This is looser
  than form-section styling (see Node-graph invariants), where every captured
  example uses token refs and none has ever used raw hex; on a page, the two
  shapes coexist, even across sibling components. Token names are just as
  unvalidated on a page as on a form section — a bogus
  ref name PUTs 200 and fails silently at render (see Write path) — so when
  writing a ref, read the real name off the builder, never synthesize one. A
  freshly generated page has its layout values filled in but every color still
  at `{"value": None}`, which is the platform's own default look, not a broken
  style.
- **State and logic**: `Variable` (page-local state — plain text, JSON with a
  schema, or a list-of-objects shape good for KPI-tile data), `VariableRef`
  (a dot-path like `selectedItem.some_field` bound into a component's
  Property), `EventMapping` (an `on_click`-style hook on a Container, either
  a small JS action or a "open a popup" action), `Criteria`/`Condition`
  (per-container visibility driven off a page Variable — this is also how
  tabs are built: an "active tab" Variable plus a click handler that sets it,
  plus one Criteria per pane), `Popup` (its own Container subtree), and
  `Tabs`/`Tab` as a first-class widget.

**Widget binding is one of three trios**, and once you know which one a
widget uses, every widget of that family needs no further capture:

- View-type widgets (form, table, gallery, sheet, kanban, matrix, list,
  timeline, and the repeater mechanism) bind through
  `flow_type` / `flow_id` / `view_id`. A page-hosted `view/form` auto-creates
  a fresh Draft item every time it renders — expect draft-item count to climb
  just from testing.
- Report-type widgets (chart, table, card, pivot) bind through a single
  `report_id`, and simply render whatever visualization type that report
  already is — a card-type report renders as a card everywhere, a chart-type
  report as a chart everywhere.
- The native KPI-number widget binds through `metrics_type:"stepmetrics"` and
  needs only a flow id — it renders a full per-step analytics table (min/max/
  average time in step, sent-back and rejected counts, a duration filter)
  with zero other wiring required.
- General-purpose widgets (label, icon, button, divider, progress bar,
  breadcrumbs, card, image, hyperlink, rich text, iframe, tab, and a
  "master-detail" widget) mostly bind through a single relevant Property
  (a label's text lives in a `title` Property; a hyperlink needs
  `title`/`url`/`openInNewWindow`/`tooltip`; a button needs
  `caption`/`size`/`type`/`iconPosition`; an image needs `imageSrc`).

**The repeater mechanism**: write the host component's own FieldMapping trio
(`flow_type`/`flow_id`/a `view_id` such as the admin view/`view_type`/
`selectedFields`) and it renders as a live repeated row for each matching
record — but the row template's own labels only pick up per-row data when
their text Property is a `VariableRef` of `Type:"DatasourceParameter"`
pointing at something like `item.<field>`, and that VariableRef must also be
registered in the page's own `Page::VariableRef` list. Writing only the host
FieldMappings without registering the template's VariableRefs produces a
repeater that visibly repeats N times but shows no per-row data — that is the
template-binding step missing, not a broken repeater.

Known gaps, worth knowing before you spend time chasing them: rich-text
component content does not reliably render however it's written (its real
serialization format has not been captured from a builder-authored example);
a custom component needs an actual installed component bundle, which has no
API-driven install path at all; card- and pivot-type report widgets need a
matching report of that exact type to already exist; and a progress-bar
widget has been seen configured correctly yet render blank, cause unresolved.

A few operational gotchas:

- Data-bound widgets obey a sticky **"Viewing as" role lens** in the builder —
  an access-denied message on a data widget usually means the role you're
  previewing as lacks permission on that flow or view, not that the page
  itself is broken. Check the lens before you go looking for a bug.
- Some auto-generated reference pages add an entirely NEW Navigation set
  instead of a Menu inside the role's existing navigation — the result is a
  page that was genuinely created but never actually appears as a tab
  anywhere a real user looks. If a newly built page "isn't showing up," check
  whether it landed in a stray Navigation before assuming the create failed.
  The fix for "give every role the same view" is to point every role's
  `Navigation::Menu` at the same shared Menu ids — the binding is what
  matters, not duplicating pages per role.
- Colors used **inside a Variable's own data** (for example, a KPI tile's
  color field in a list-of-objects Variable) are design-token references —
  the same convention most `Style.Value` colors use on a page. Token refs are
  the dominant color convention across the page capture; raw hex is the
  minority form, proven only on the pages this engine API-restyled directly.
- **Patching colors alone is not the same as achieving design parity with a
  mock.** If the mock has structural elements the current page doesn't — a
  hero band, a call-to-action, KPI tiles, status pills, a donut chart — no
  amount of recoloring existing containers closes that gap. Diff structure
  against the mock before claiming parity, not just style values.
- If you patch styles by matching on a container's name (a name-prefix rule,
  say), verify the match actually lands on a container that carries the
  style keys you're trying to set. A wrapper container one level up can share
  a very similar name while carrying none of the relevant keys, so the patch
  silently no-ops on exactly the containers you meant to hit.

## Build order

The proven end-to-end sequence, most foundational first:

1. **Create the flow** (process, form, or list as needed).
2. **Members** — before anything else gets built on top, or every later
   publish involving assignees fails (see Members first).
3. **Fields and sections** — the node-graph invariants apply from the first
   field onward (see Node-graph invariants).
4. **Tables**, if any — as their own nested Model, in their own root Row,
   never nested in a Section (see Tables).
5. **Workflow** — ProcessDef, Activities, any GotoTask loops (see Workflow).
6. **Assignees** — only once members exist (see Members first).
7. **Goto gates** — the loop conditions on any backward edges, gated on a
   Boolean, fail-closed (see Expressions, Gate polarity).
8. **Visibility matrix** — section-level where a whole section shares a rule,
   field-level otherwise; re-run this step after any later workflow rebuild,
   since a rebuild silently deletes every Permission (see Visibility).
9. **Events** — computed fields, wired onto their source fields (see Field
   events).
10. **Styles** — token refs only on form sections; pages take raw CSS strings
    for every dimensional value and either raw hex or a token ref for color
    (see Node-graph invariants, Pages).
11. **Publish.**
12. **Verify** — a read-only health check of the live flow, run after every
    single builder edit, not just at the end.
13. **Simulate items** — walk a real item through create → fill → submit →
    every gate → completion, using the runtime item API (see Item data
    plane), to prove the thing actually works end to end, not just that it
    published.

The standing discipline behind every one of those steps, and every future
script that touches this API: **snapshot → dry-run → apply → read-back verify
→ publish → audit.** Snapshot the draft first (see Write path). Dry-run the
change and inspect the diff before sending it. Apply. Read back what actually
landed, not what you asked to land. Publish. Audit.

**Every batch operation ends with an output-invariant audit**: added /
skipped / verified / missing — every single record you touched must land in
one of those counted buckets. A record that's just silently absent from all
four buckets is the bug, every time; never report a batch as successful while
anything is unaccounted for.

When probing for a route that might not exist: search whatever API reference
material you have first, then sweep suffix, prefix, an `admin/` variant, and
header variations before concluding it's not there. **403/500 = the route
exists, keep digging. Only 404 means wrong door.** A response that looks like
a hard failure is very often evidence you're close, not evidence you're
blocked.

Finally: treat any inherited inventory or manifest document — including this
one — as desired state, not proven state. A note that says a piece "exists"
or "is done" is a claim to verify by a live read, not a fact to build on
directly. Absence of some behavior in one captured sample is likewise not
proof of its absence from the API generally — a single sample that never
exercised a feature looks identical to a sample proving the feature doesn't
exist. When a belief here gets corrected by a live capture, replace it
outright and say so, rather than leaving the old belief to mislead the next
read.
