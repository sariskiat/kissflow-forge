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
- `**GotoTask` is the one backward edge node.** It is how a loop jumps back to
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
  (src/app/domain/graph.py) + Robot acceptance suite. The line above was captured off a MINIMAL 2-node
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

- `**IsSuspended` skips a step at runtime without deleting it:**

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

