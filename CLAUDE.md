# RULE

remember: generalise. the eval comparison cases are just eval, not the build target!

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

## Commands

No `.venv` here. Deps arrive per-run via `uv --with` (`requirements.txt` =
`fastmcp>=3`, `pytest>=8`).

```bash
# unit + integration — 637 passed, 25 skipped, 2.38s (verified 2026-08-10). The 25
# skips are the live suites below — excluded by default, see conftest.py.
uv run --with pytest --with 'fastmcp>=3' --no-project pytest -q

# one file / one test by name
uv run --with pytest --with 'fastmcp>=3' --no-project pytest -q tests/test_pages.py
uv run --with pytest --with 'fastmcp>=3' --no-project pytest -q -k step_permissions

# live acceptance — 25 tests, 25 passed (verified 2026-08-10). Hits the REAL
# Kissflow dev tenant (KF_APP) via direct in-process calls to kfforge.server's own
# tool functions — no subprocess, no Robot Framework. Opt in with --run-live, or
# these 25 just skip (see above).
uv run --with pytest --with 'fastmcp>=3' --no-project pytest --run-live -q \
  tests/test_live_lifecycle.py tests/test_live_branching.py

# MCP server
uv run --with 'fastmcp>=3' python -m kfforge.server
```

**Dropping `--with 'fastmcp>=3'` silently loses ~96 tests.** `test_p2_server.py`
and `test_p3_surface.py` die at collection with `ModuleNotFoundError: No module
named 'fastmcp'`, and pytest reports `524 tests collected, 2 errors` — not a
failure you'd notice if you only read the tail.

`tests/test_engine_doc.py` is a contract test over **this file**: it requires
every `##` heading listed in its `HEADINGS`, 2–4 marker phrases inside each
section's own text, and `len(CLAUDE.md) > 8000`. The manual below is mandatory
by test, not by accident — do not "tidy" it into `docs/`.

## Layout

```
kfforge/
  types.py         # frozen structs, closed enums — the typed core
  graph.py         # pure offline ops on the normalized node-graph
  expr.py          # Expression/Node AST for branch conditions + GotoTask gates
  nav.py           # pure offline ops on the app-level navigation graph
  pages.py         # pure offline ops on the app-PAGE graph
  verify.py        # health check: every reference that would break the form
  client.py        # live builder client — THE WRITE PATH (dev tenant only)
  pages_live.py    # live orchestration for page + navigation graphs
  dataplane.py     # documented /process API — create an item, fill it, move it
  engine.py        # offline planning; apply/publish orchestration lands here later
  tools.py         # framework-agnostic tool logic (dict in / dict out)
  server.py        # fastmcp MCP server
  design/          # confirm.py (approval protocol) · diagram.py (draw.io XML) ·
                   # mockup.py (self-contained HTML for the business owner)
  intake/          # schema.py (11-dimension AppSpec) · questions.py (grilling
                   # script) · compile.py (AppSpec → ordered BuildPlan) · serde.py
shapes/            # 57 captured JSON node shapes — the proven-capture reference
tests/             # pytest + tests/robot/ (2 suites) + fixtures/
docs/adr/          # 4 ADRs — locked decisions, don't re-litigate
CONTEXT.md         # domain glossary
```

Trunk is `develop`. `CONTEXT.md` and `docs/` are **untracked** — the ADRs are
not committed yet.

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
- **The style chain must exist COMPLETE on every flow**: `Model::Appearance` →
  `Appearance` → `Appearance::Style` → `Style`. A missing chain fails to
  render the page — and an INCOMPLETE one is exactly as fatal (proven live
  2026-08-12, replacing an earlier belief that only a wholly-absent chain
  breaks render): an `Appearance` whose `Appearance::Style` is EMPTY (zero
  `Style` children) throws the builder's "There was an error / Reload" for the
  whole form. doctor `ok`, publish 200, and a live item create all passed
  while the form stayed broken — only the builder UI caught it. The tell:
  Appearance-node count > Style-node count in the draft; each `Appearance`
  must own exactly one `Style`. `forge_set_styles` with a real token on the
  stranded section completes the chain and restores render.
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

  **Submit count for a walk that never loops: 1 (the StartEvent) + N (the UserTasks). A `GotoTask`
  is never itself a hop — it never becomes `_current_step` and never consumes a submit.** When its
  condition DOES fire the item jumps backward and the walk simply continues from there, so the
  total then depends on how many times the loop runs; the 1+N figure is the non-firing case.
  A Draft item's OWN first submit is a real hop (it leaves
  `Start`, landing on the first UserTask) — miss counting it and every later hop's target looks
  shifted by one, which reads exactly like "the last step needs a second submit" if you go by
  hop COUNT alone instead of instrumenting `_current_step` at every submit. Re-verified live
  2026-08-07 with `_current_step` read before and after every submit, on a workflow WITH a
  `GotoTask` (condition deliberately false, so the Goto should not fire): submits landed on
  `Start`, then each UserTask once, in order, with the LAST UserTask's own submit completing the
  item directly — no step ever repeated, no extra hop anywhere. (An earlier version of this note
  claimed the opposite — that a `GotoTask` forces the step before it to be submitted twice — from
  a test that never separately counted the `Start` hop; a caller that believed it would have
  double-submitted before every gate and silently skipped a real step at the same time. Deleted,
  not appended, per this file's own rule: a corrected belief replaces the wrong one outright.)
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
  **A rebuild also strands any SequenceNumber `Step` stamp — THE deterministic
  publish-500 condition (#18, isolated live 2026-08-12).** The stamp is
  `Property{Name:"Step", Value:<activity id>}`, a SCALAR reference the
  list-only dangling sweep never touches; once its activity is deleted,
  `PUT` still 200s but every publish dies `500 MetadataError` with zero
  diagnostic content ("An unexpected error has occurred"), doctor-clean at
  the time. Isolated by a subsystem-deletion bisect (Permissions, Events,
  Expressions, GotoTasks all ruled out; removing the SequenceNumber tree
  flipped publish to 200) and confirmed by a one-key surgical fix:
  repointing that single `Value` at a live activity made the same graph
  publish. `build_workflow` now repoints stamps by activity NAME (falling
  back to the new StartEvent), and `verify.doctor` flags any dangling Step
  stamp as its own rule.
- **A `Parallel`'s branches are UNCONDITIONAL by default.** `build_workflow`'s
  `parallel` argument alone produces an and-fork — every branch always runs.
  Making a branch conditional is a separate, later step; see Conditional
  routing.
- **A `GotoTask` placed inside a branch must be told which branch, explicitly
  — it cannot always be inferred from the target alone.** `add_goto_task`
  gained a `branch_process_def_id` parameter (node M, 2026-08-07) that PINS
  and VALIDATES which `ProcessDef` chain hosts the new GotoTask, instead of
  always deriving it from `target_activity_id`'s own `ProcessDef` (the
  original, still-default behavior — unaffected when this parameter is
  omitted). The gap this closed, reproduced live: a target 2 root-chain steps
  before a 2-branch `Parallel`, added with no way to say "put this inside
  branch A," landed the GotoTask **after the LAST root-chain activity** —
  right before the trailing `EndEvent`, exactly where a root-chain target is
  *supposed* to land (see the workflow bullet above) — evaluated once for the
  whole item instead of scoped to the one branch that actually needed the
  rework loop. `branch_process_def_id` does **not** enable a cross-branch
  jump — passing it REQUIRES the target to already belong to that exact
  `ProcessDef`, and raises a loud `ValueError` before any write otherwise.
  This is deliberate, not a missing feature: `verify.doctor`'s own rule 2b
  already flags any GotoTask whose target sits in a different `ProcessDef` as
  "jumps out of its own branch," and the oracle app's own two GotoTasks are
  both branch-local (see Conditional routing) — there is no proven live shape
  for a cross-branch jump to reproduce. What the parameter buys is an
  explicit, validated lever where none existed before, so a caller resolving
  a target by (name, branch) — needed the moment two branches share a step
  name — gets a clean rejection instead of a silently wrong graph.

## Expressions

An `Expression` node is not always a branch condition — its owner key tells
you what it actually is, and **the owner key is one of three**, each meaning
something different:

| Owner key    | Meaning                                    |
|--------------|---------------------------------------------|
| `ProcessDef` | a branch condition (which path an item takes) |
| `Activity`   | a `GotoTask` loop condition (see Workflow)     |
| `Property`   | a value-generator prefix (e.g. an auto-number scheme) |
| `Field`      | a computed-field formula (#48, 2026-08-12 — see Field events) |

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

## Conditional routing

A `Parallel` gateway built by `build_workflow` is an unconditional and-fork on
its own — every branch always runs. **Conditional routing** (service-tier /
triage / approval-routing: "this branch runs when field X equals value Y") is
that gateway plus one `Expression` per branch, wired to the branch's own
`ProcessDef` (see Expressions' owner-key table). Node M (2026-08-07) is where
this became reachable from the tool surface — `expr.build_branch_condition`
existed since the branching AST work but had ZERO callers until then.

**The oracle shape** (a working app on this same tenant, read-only, months in
production): one `Parallel` Activity, N branch `ProcessDef`s each carrying
exactly one `ProcessDef`-owned `Expression` (`<field> = "<literal>"`, the same
AST as any other branch condition), and — on the branches that need rework —
its own `GotoTask` sitting **last within that branch's own
`ProcessDef::Activity`**, targeting an early step of the SAME branch. Never a
cross-branch or branch-to-root jump (see the Workflow section's
`branch_process_def_id` note). All fields tie together: the deciding field is
a plain `Select`, one distinct literal per branch, no branch left without a
condition (a genuine switch, not an if/else-if with an implicit "else").

⚠️ **Fail OPEN, not closed — a value matching no branch condition SKIPS THE
WHOLE PARALLEL and the item completes with no work done, silently.** Verified
live 2026-08-07 (node M's own negative control, independently reproduced, then
pinned as a permanent regression test — `tests/robot/forge_branching.robot`
test 11): walked with a deciding-field value that matched none of 3 branch
literals, the item never touched any branch step — the admin detail response
carries **NO `_current_step` key at all** (confirmed via `Dictionary Should
Not Contain Key`, not merely a null value under that key — a first draft of
this note said "came back null" from a paraphrase, and the live run corrected
it: code that does `detail["_current_step"]` would `KeyError` here, code that
does `detail.get("_current_step")` reads `None` either way — write it the
`.get()` way) and `_status` comes back `"Completed"` on the very next submit
past the step before the gateway. This is the SAME fail-open hazard Gate polarity already
names for a loop (a blank optional Select silently "escapes"), now confirmed
for a switch: an item that silently finishes is *worse* than one that gets
stuck, because a stuck item is visible on a dashboard and a finished one looks
identical to a real success — nobody ever goes looking for it. This is why
the oracle leaves NO branch without a condition (previous paragraph): every
value your users can actually pick needs a branch that claims it, or that
value quietly ends the case. `forge_set_branch_conditions`'s own result
carries an `uncovered` bucket for exactly this — every real Select option
(when the deciding field is one) that no branch on the gateway claims, across
the WHOLE gateway, not just the branches one call happened to touch.
`uncovered` is never folded into `isError` (a caller may genuinely want an
ending value) — it exists so the gap is stated, never discovered later.

**The tool**: `forge_set_branch_conditions(flow_id, field_name,
branch_literals, kind, publish)` — `branch_literals` maps a branch NAME to the
literal that selects it. Requires the flow to have **exactly one** `Parallel`
gateway (this engine can only build one anyway, via `build_workflow`'s single
`parallel` argument) — fails loud rather than guessing which one on a flow
with zero or more than one. Every literal is validated against the deciding
field's REAL live list options (fetched via its `ReferredList`) before any
write, same "never guess a literal — read it" discipline as everywhere else —
CLAUDE.md's own war story is a branch that silently never fired over one
mis-cased literal. Idempotent per branch in the SET sense: re-running with a
changed literal REPLACES that branch's condition (`expr.remove_condition`
strips the old Expression + AST subtree + back-refs first) rather than
accumulating a second one alongside the stale first; a branch not named in
`branch_literals` is left untouched. Pair with `forge_add_goto_gate`'s
`branch_name` parameter (see Workflow) for the per-branch loop half of the
shape.

⚠️ **A tenant-state limitation, not an engine limitation, logged rather than
silently worked around**: KF_APP's list inventory was EMPTY (0 lists) as of
2026-08-07 (same finding `forge_lifecycle.robot` already logged for its own
Select-field fallback) — no human has wired a Kissflow List into this app yet.
`build_branch_condition` also accepts a Text-typed deciding field (the same
plain-string wire shape as a Select's value — see `_BRANCH_FIELD_DATA_TYPE`),
so the live proof below used Text and got the real literal-validation-against-
options codepath exercised only by the OFFLINE tests (a fake list). The
Select-backed path is offline-proven and code-reviewable, but **its live
option-fetch-and-validate behavior remains unverified on THIS tenant** until a
human wires a real List — do not upgrade that to "proven" without re-running
against one.

⚠️ **A live-verified mechanic, worth recording because it is easy to guess
wrong**: crossing a conditional `Parallel` gateway needs **no separate
submit**. An item sitting on the step immediately before the `Parallel`
(`ProcessDef::Activity` order) that gets submitted lands **directly** on the
selected branch's own first step, in the SAME API call — the gateway itself
is never a `_current_step` a caller submits against, conditional or not (it
carries no Permissions either — see `NO_PERMISSION_NODETYPES`). Verified live
2026-08-07 (node M): two items, submitted past the same step with different
values of the deciding field, landed on `Handle Alpha` and `Handle Beta`
respectively after that ONE submit each — not on the `Parallel` itself, and
not requiring a second hop.

**Two-item divergence is the only real proof.** Every check up to and
including a clean `forge_doctor` can pass with a branch condition silently
inverted, missing a literal, or pointed at the wrong field — a branch that
never fires looks identical to one that works (THE RULE, restated for this
specific shape). The only oracle is walking two real items with different
values of the deciding field and reading back — directly, never an echo of
the plan — which concrete step each one actually landed on
(`tests/robot/forge_branching.robot`'s `Get Current Step` keyword; a plain
`_current_step` read via the item data plane — `Get Item Detail` is the
general-purpose sibling for a test that needs a field `Get Current Step`'s own
strictness would raise on, like test 11's legitimately-absent one). `tests/
robot/forge_branching.robot` is the permanent regression suite for this whole
section, including the fail-open negative control above — 11/11 live
against KF_APP as of 2026-08-07, artifact deleted and deletion verified via
the app-scoped flow-list route in its Suite Teardown.

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
- ⚠️ **CONFIRMED on the live builder oracle: a banner Section and its table host must be
  ADJACENT in root `Model::Row` — the banner row immediately followed by the table-host row.**
  `add_table` (graph.py ~592) does `root.setdefault("Model::Row", []).append(host_row)` — it
  unconditionally APPENDS the host to the END. When a banner Section was created for the table,
  appending strands the empty banner: other sections fall between it and its table, leaving a
  standalone empty Section (`Column::Row=[]`, zero fields). The builder then renders
  "There was an error / Reload" for the WHOLE form — it will not even open. An empty Section is
  renderable ONLY as a caption directly above its table (the banner→table unit in the golden
  reference); stranded, it is the render-breaker.
  - It is NOT the empty `Column::Row: []` key — removing that alone did NOT fix it (verified on
    the oracle first). The fix that rendered the form: reorder root `Model::Row` so the table host
    sits immediately after the banner (matches the golden reference).
  - The semantic comparator never caught this: its section-order check EXCLUDES the table host
    (`Column{Type:"Model"}`, not a Section), so a misordered host is invisible — the rebuild read
    as "1 gap" while being completely unrenderable. HTTP 200 + publish + doctor-clean +
    compare-clean all lied; only the builder UI told the truth.
  - **Fix landed (#10, 2026-08-12):** `add_table`/`forge_add_table` take `after_section: <banner
    name>` and INSERT the host directly after that section's root row (unknown name raises before
    any write; omitted = old append behavior). The banner Section itself stays caller-created
    (`regroup_into_sections` with an empty field list). Still owed elsewhere: the comparator must
    diff root `Model::Row` order INCLUDING the table host, not around it (#16).

## Field events

⚠️ A CORRECTED BELIEF (2026-08-12, #48 browser capture): this section used to
open "Kissflow has no formula or computed field type" — WRONG on the current
platform. The field Settings tab carries an "Is this a computed field?"
toggle opening a full Formula builder; saving writes a FOURTH Expression
owner, the Field itself (`Field::Expression` → Expression{Field, ExpressionStr,
Expression::Node} — same Node AST family as branch conditions, field refs BY
ID, toggle disables DefaultValue). See docs/capabilities/config.computed.md +
shapes/field_computed_expression.json. Runtime caveat: the formula did NOT
evaluate on an admin data-plane fill — evaluation is client/submit-side,
runtime proof still open. Field events below remain a real, separate
mechanism for script-based computation: a script the client SDK runs in
response to a field change.

```
Field { ..., "Field::Event": ["Event_Sample01"] }        # back-reference, bidirectional
Event { Id, Kind:"Event", Field:<field id>, Trigger:"onChange", Script:"<raw JS>" }
```

**The trigger is a FUNCTION of the SOURCE field's type**, and all three wire
strings are now LIVE-OBSERVED on a published flow (2026-08-10 eval-case read,
issue #12 — replacing the earlier belief that only `onChange` was captured):
a Select source fires `onClick`, Date and Number sources fire `onSelect`,
Text/Textarea sources fire `onChange`. A hand-picked wrong trigger writes
fine, publishes fine, and simply never fires — derive it from the source
type (`kfforge.intake.schema.trigger_for`), never guess it. User→`onSelect`
and Boolean→`onClick` are family-inferred, still unverified live.

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
not a bare id string**; filtering with a plain `app_id in record
["Applications"]` silently matches zero roles (found live writing this note)
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
  refused when they try to submit their own item: `403
  KISSFLOW_ERROR_050302 "You don't have permission to submit this item
  anymore."` Re-granting the SAME role/flow pair with `"Permission":
  ["InitiateItems"]` instead (a second `member/batch` call is an upsert, not
  a duplicate) is what actually lets the walk proceed. A live reference app's
  own AppRoles carry exactly `"Role": "DataAdmin", "Permission":
  ["InitiateItems"]`.
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
- **`ReferredList` wiring is CAPTURED and proven (#13, 2026-08-12 — replacing
  the old "never synthesize" rule outright).** The whole chain is three
  probed routes plus one key: create a list flow with
  `POST /flow/2/{acct}/list?_application_id={app}` body `{"Name": ...}` →
  200 `{_id, Type:"List", Status:"Live"}` (born LIVE, no publish step;
  duplicate name 400s FlowNameAlreadyExists); SET its values with
  `POST .../list/{id}/items` body `{"ListItems": [...]}` — REPLACE
  semantics, proven by a two-write probe (a bare array 403s
  TypeMissMatchError, any other dict key 400s InvalidSchemaArguments); then
  write `ReferredList:<list_id>` on the Select's Field node. Proven end to
  end on a real item: a value from the list persists, a value outside it
  PUTs 200 and silently CLEARS the field (the Select discard rule, one
  notch worse than "discards" — it wipes what was there). Lists flagged as
  holding personal data stay human-made (PDPA, D2/D9).
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

⚠️ **The `lists` route needs `_application_id` scoping too, the SAME leakage
class the flow-list route already has (see Members first)** — confirmed live
2026-08-07: `GET /flow/2/{acct}/list?page_size=100` with no `_application_id`
returned 100 lists (paginated) from an UNRELATED app in the same account;
adding `&_application_id={app_id}` to the SAME call returned the true,
correctly-scoped count for KF_APP (0, on the tenant checked).
`KfClient.list_lists` now wraps this route with the scoping baked in (#13);
`KfClient.get_list_items` is scoped by a specific `list_id` and has no
leakage risk — this note stays so nobody hand-rolls the unscoped URL and
reads, or later writes against an id sourced from, a DIFFERENT app's list.

- **The aiid trap:** the activity-instance id returned by a "my items"-style
  listing is the initiator's already-CONSUMED instance — submitting or
  rejecting against it fails with an "already used" style error. Never
  resurrect a myitems-style id as a fallback for anything below — that trap
  is exactly what the two-phase rule's own fallback (next paragraph) is NOT.

  ⚠️ **A CORRECTED BELIEF on "always fetch detail, use that id," captured
  live 2026-08-07 walking a real item from its start step through to
  completion.** The rule used to say the live activity-instance id is
  *always* `detail._current_context[0]._context_activity_instance_id` — true
  from the SECOND submit on, but wrong for the very first one. An item still
  sitting at its start step, never yet submitted, has no `_current_context`
  at all; the only usable id for THAT submit is the one the CREATE call's own
  response returned. The real rule is **two-phase**:

  | hop | step (example)  | ctx activity-instance id | id actually used   | result |
  |-----|------------------|--------------------------|---------------------|--------|
  | 1   | start step       | absent                   | the CREATE response's id | 200 |
  | 2   | 1st user step    | present                  | detail's context id | 200 |
  | 3   | 2nd user step    | present                  | detail's context id | 200 |
  | 4   | last user step   | present                  | detail's context id | 200 |
  | 5   | (none)           | —                        | —                    | status = Completed |

  So: fetch detail and use `_current_context[0]._context_activity_instance_id`
  whenever it is present — that part of the old rule still holds on every hop
  past the first. Only when it is genuinely absent, and only on the very
  first submit right after create, fall back to the id the create call
  itself returned. A missing context id on any LATER hop is still a real
  problem, not a second excuse to reuse the create-time id — reusing it
  there would recreate exactly the "stale/consumed id" failure mode this
  whole trap exists to avoid.
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
  re-probes them: a legacy list-flow path is pure front-end with no
  API behind it; per-field lookup/reverse-lookup routes 500 on any editable
  Select; and no API route exists to reassign an in-flight activity to a
  different user. ⚠️ A CORRECTED BELIEF (2026-08-12, #50): this list used to
  claim "a dataset-style product surface 403s outright (account tier)" — WRONG
  for flow creation. The `dataset` flowtype (Dataforms) works cleanly:
  `POST /flow/2/{acct}/dataset` creates one born Live, records live on their
  own `/dataset/2/{acct}/{flow_id}` route family, no members needed, no
  publish route at all. See docs/capabilities/module.dataform.md +
  shapes/dataform_dataset_skeleton.json. The old 403 note likely described an
  analytics-shaped surface, not this flowtype.

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

**An API-created application is born `Draft` and its Play/runtime view shows
"This app has not been published yet" until the APP-LEVEL publish fires**
(captured live 2026-08-12, browser round): `POST
/metadata/2/{acct}/application/{app}/publish` → 200 with a `Runtime_{app}`
blob. This is a separate step from per-flow and per-page publishes — build
order gains it as the app-shell finisher. ⚠️ Do NOT confuse it with the
builder's **Deploy** button, which is a CROSS-ENVIRONMENT promotion (dev →
UAT on this tenant, with Build/Version numbers) — never click Deploy on the
dev tenant. Builder URL pattern: `https://{domain}/appbuilder/{app_id}`
(Play/Studio; Studio sub-routes `/role/list`, `/process/{id}`, `/case/{id}`,
`/page/{id}`).

**No AppRole auto-provisions on a fresh application** — this used to be
inferred from a `PageAccess` list seen in one archive response;
independently re-tested and disproven live 2026-08-07 (node G review): a
throwaway app's own member roster (`GET .../application/{app}/member`) held
exactly one entry, the creating user, and zero AppRole entries. `member/batch` at the
application level 500s `FlowError` regardless of which AppRole name is tried
(`Admin`/`User`/`Member`), and a `ValueType:"User"` assignee persists and
publishes cleanly but never confers runtime submit permission —
`_current_context[0]` still lacks `_context_activity_instance_id` and submit
still returns `403 KISSFLOW_ERROR_050302`, even with that user granted via
`member/batch` (⚠️ `Permission` must be a **list**, e.g. `["Editable"]` — a
bare string 400s `KISSFLOW_ERROR_04231 UnsupportedPermissionError`). There is
still no API route that creates an AppRole or adds a user to one — both are
builder-UI-only. The workaround: grant membership at the PROCESS level
instead of the application level (`Role:"DataAdmin"`, `Permission:
["InitiateItems"]` — see Members first), and wire the assignee as
`ValueType:"AppRole"`, not `"User"`. Proven live end to end — a real item
walked from its start step through every user step to completion under
exactly that combination.

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

Known gaps, worth knowing before you spend time chasing them: ⚠️ rich-text
serialization is now CAPTURED (2026-08-12, #51 — replacing the old "not
captured" note): the `value` Property holds a PLAIN HTML STRING (`<h2>`,
`<p><strong>`, `<ul><li>`), no wrapper, survives publish byte-identical;
builder-UI pixel render still unchecked. A custom component needs an actual
installed component bundle, which has no API-driven install path at all
(re-confirmed #51: 4 route families 404, `/marketplace/2/{acct}/component`
503s — backend exists, nothing installed; manage surface is UI-only under
Developer > Custom Components); card- and pivot-type report widgets need a
matching report of that exact type to already exist; and a progress-bar
widget has been seen configured correctly yet render blank, cause unresolved
(a fresh #51 capture landed one cleanly — render check queued). Navigation
role-scoping: prefer `Menu.VisibleTo:[<role ids>]` on a shared Navigation
(no key = visible to all) over duplicating Menus per role — see
shapes/menu_navigation.json.

- **`Page::Component` registration is NOT load-bearing (#24, proven live
  2026-08-11).** `kfforge/pages.py` never writes `Page::Component`, so a
  built page leaves the key absent entirely. Test: built a page with three
  `general/label` widgets (their Component ids never registered, `Page::Component`
  absent), published, opened the builder — all three rendered fine. So an
  unregistered Component still renders; `add_widget` needs no registration step.
  A page's earlier partial registration (30 of 34) is therefore cosmetic, not
  a render gate. Recorded so nobody chases it again.
- **A freely-bound single live value on a page: the #23 Known Exclusion is
  NARROWED (2026-08-12, #51), not gone.** The old absolute ("no shape reaches
  it") fell to a live capture: a `VariableRef{Type:"PageVariable",
  Variable:"<pageVar>.<field>"}` bound into a label's text Property IS a
  real, reachable freely-bound live value — the working master-detail
  composition (repeater + `on_click` `setVariable("selectedItem", ...)` +
  Json-typed page `Variable` + one PageVariable ref per detail label, see
  shapes/variable_ref.json). What remains excluded: a live AGGREGATE number
  (an "open cases" count) with no user click feeding the Variable — the
  engine still has no route to a report of the right type, a `general/card`
  `count` is still a static int, and `metrics`/`stepmetrics` still renders a
  fixed per-step analytics TABLE only. So KPI tiles bound to a clicked
  record: buildable now; KPI tiles bound to a query aggregate: still refused
  at compile, metrics table is the substitute.

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
5. **Workflow** — ProcessDef, Activities, any GotoTask loops (see Workflow). A
   `Parallel` gateway built here is UNCONDITIONAL — every branch always runs
   — until step 7's branch conditions attach (see Conditional routing).
6. **Assignees** — only once members exist (see Members first).
7. **Goto gates and branch conditions** — the loop conditions on any backward
   edges, gated on a Boolean, fail-closed (see Expressions, Gate polarity); a
   `Parallel`'s branches, made conditional on a deciding field's real values,
   never guessed (see Conditional routing). A per-branch goto gate is placed
   with `add_goto_task`'s `branch_process_def_id` / `forge_add_goto_gate`'s
   `branch_name`, last within its own branch, never cross-branch.
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

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI, inferred from this repo's `origin` remote
(`sariskiat/kissflow-forge`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default 5 canonical roles, label string equals role name. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at repo root, already in place.
See `docs/agents/domain.md`.

### Reader skill

Turn the two input files (a `.drawio` flow capture + an HTML page design) into
spec JSON, consumed via the existing `forge_update_spec` → `forge_approve_spec`
→ `forge_plan_app` surface — the engine never parses `.drawio` (D5). Ask on any
blocking gap, never enrich a guess; validate every routing literal against the
LIVE word list; refuse any `kfforge.coverage` shape marked `refuses-loudly`,
naming the row. Token discipline: never open the XML whole, analyze with
`python3`. See `docs/agents/reader.md`; its output boundary is proven by
`tests/test_reader_boundary.py`.
