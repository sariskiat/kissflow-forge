---
name: kissflow-forge-builder
description: Build or edit a Kissflow app, process, board, dataform, page, or role through the kissflow-forge MCP (the forge_* / kf_* tools). Use whenever the user wants to create, change, wire, or fix anything in Kissflow via that MCP — "build me a Kissflow process/app", "add a field/step/table/gate", "wire approvals", "make a board/dataform", "build the pages", "why doesn't my flow render". You are the brain; the forge_* tools are the hands. Covers THE RULE (200 proves nothing), the proven build order, the intent→tool map, what to refuse and why, and the copilot fallback.
---

# Kissflow Forge Builder

You are a fresh Claude with ONLY the kissflow-forge MCP connected. This is the whole
playbook. The engine writes an **undocumented** internal builder graph; every rule here
was captured live, not read off a schema. When unsure of a wire shape, do not guess —
call `forge_capabilities(query)`.

## THE RULE — the one thing you must never forget

**An HTTP 200, a clean publish, and a confident copilot reply all prove NOTHING.**
The builder UI is a second, stricter validator on top of whatever the write API accepted.
A flow can accept every write, publish clean, report itself live, and still render to a
user as an error screen.

The only two oracles are:
1. **Graph read-back** — read what actually landed in the draft, never what you asked to land.
2. **A real item walk** — `forge_simulate_case` from create → fill → submit → every gate → complete.

Run `forge_doctor` after EVERY edit. Never say "it works" on a 200. Never gate on copilot's
reply text. When told "it still errors," do not re-diff the part you already checked — go find
the layer you have not checked (config payload, membership, per-node keys, the UI's own network).

## Design is YOUR job

The user is not expected to hand you a finished design. Grill them, then map their intent onto
Kissflow best practice — the workflow they describe may be wrong or unoptimized. Only exception:
they arrive with a complete mockup + diagram + schema → build to that verbatim. Offer the WHOLE
field, never a bare skeleton (see step 4). Before a destructive build, produce a confirmation
artifact (`forge_render_flow_diagram` / `forge_render_schema_diagram` / `forge_render_mockups`)
for human sign-off — building blind against an undocumented API is how sessions get lost.

## Sweep before you design

Call `forge_sweep` FIRST to discover what already exists (schemas, not just names; a sweep ends
in a read|error|skipped audit). Do not duplicate data a process already owns or a page already
shows. Scope everything to the target app — an unscoped list route silently leaks a DIFFERENT
app's flows/lists. Rough map: page design needs a page + role sweep; dataform needs a process
sweep; board/process needs a page sweep; permissions need a step sweep.

## Write-path discipline

Snapshot any draft you did not just create before writing to it. Read back what LANDED, never what
you asked to land. Then publish, then audit. To delete a PROCESS you must ARCHIVE it first — an
unarchived process delete fails; forms, lists, and datasets delete directly. `_meta_version` changes
only on publish, never on a plain draft save — do not treat two draft saves as two versions.

## Build order — the numbered playbook

Each step names the tool(s) and the gotcha it guards. Foundational first.

**-1. Master data first — `forge_create_list`, `forge_create_flow(kind="dataset")`, `forge_dataset_records`.**
   Lists and dataforms are reference data that Lookup / Remote-lookup fields point at, so they
   must exist before the fields that reference them. Both are born LIVE (no publish step); a
   dataform has NO members gate and NO workflow. A list `ReferredList` value outside the option
   set PUTs 200 and silently CLEARS the field — validate every option live.

**0. Create the flow — `forge_create_process` (default `from_template=True`), `forge_create_flow`, or `forge_create_app` + `forge_create_page`.**
   `from_template=True` (the default) clones a known-good identity/initiate shell with one
   "Manager Approve" step — `steps=` is IGNORED; rebuild the real workflow in step 5. Pass
   `from_template=False` only for a bare scaffold. A board is flowtype `case` (status-lane
   tracker, no step workflow, born live); a dataform is `dataset`. Duplicate flow name 400s.

**0.5. Roles + members BEFORE anything builds on top — `forge_create_app_role`, `forge_member_batch` / `forge_add_member_roles`, `forge_add_role_users`, `forge_grant_tier`.**
   An API-created flow has ZERO members, so the acting user has no permission and the builder
   refuses to render it — the #1 reason a fresh flow "does nothing." Grant `Permission:["InitiateItems"]`
   (a LIST, never a bare string; `[]` PUTs 200 but the initiator still gets 403 on submit). Then
   add the ACTING USER to the assignee role via `forge_add_role_users` — the creator is NOT
   auto-added, and that gap is THE reproducible submit-403 (KISSFLOW_ERROR_050302). Write key is
   `Users`, read key is `Members` (a `Members` write is silently ignored). `Role` vocabulary is
   flow-type-scoped (process: Admin|DataAdmin|Member) — read the rejection error, don't re-guess.

**1. Fields + sections — `forge_apply_fields`, `forge_apply_layout`.**
   Node-graph invariants apply from the first field: every Field needs a `Model` back-ref + a
   `CreatedAt`; ids use capitalised prefixes (`Field_`, `Column_`); a Row is a 6-unit grid, max
   3 columns, tiled `(0,2)(2,4)(4,6)` — overflow breaks the WHOLE form. The mandatory style chain
   (`Model::Appearance → Appearance → Appearance::Style → Style`) must be COMPLETE on every flow;
   an Appearance with zero Style children renders "There was an error / Reload" while doctor,
   publish, and item-create all pass.

**2. Offer the WHOLE field, not the skeleton.** Every field has four layers — build all four:
   - **Native config** — per-type keys (Number: `DefaultValue`+`Decimalpoint`; Textarea:
     `AllowFormatting`; Attachment: `CaptureOnly`; Currency: `CurrencyTypes`; Select:
     `ReferredList`; Lookup/Remote-lookup: `Field::QueryDefinition` with `FlowType` = the sole
     discriminator "Process" vs "Dataset"). Call `forge_capabilities("field.<type>")` for the shape.
   - **Validation** — `forge_add_field_validation` writes `Condition{Operator, RHSValue, ErrorMessage}`.
     Wire-proven operators: MAX_LENGTH, CONTAINS, GREATER_THAN, AFTER. "Not empty" is `Required:true`,
     not a Condition. Always write an ErrorMessage.
   - **Computed** — `forge_set_events` for a field EVENT (a script on the SOURCE field; trigger is a
     function of the source type — never guess it; six types can't be a source: Attachment, Image,
     Rich text, Signature, Sequence number, Geolocation). A native formula also exists as a
     Field-owned Expression (`forge_capabilities("config.computed")`) — build the Node AST, not just
     the string mirror; validate every referenced field exists.
   - **Default + visibility** — a static default costs one key (`forge_apply_fields` `default_value=`;
     `"Today"` is the platform relative-date keyword for Date — `forge_capabilities("config.defaults")`).
     Form-level conditional show/hide (this field appears only when ANOTHER field equals a value)
     is a SEPARATE lever from step 7's per-step matrix: a `ColumnVisibility` Criteria on the target
     field (`forge_capabilities("config.conditional-visibility")`), not a Permission node.
   A bare field with no validation/computed offered is a quarter of the job.

**3. Tables — `forge_add_table`.**
   A table is a nested child Model, NOT a field type. It must sit in its own root-level Row
   (`Model::Row`), NEVER inside a Section — a section-nested table renders empty. Use a banner
   Section immediately ABOVE the table, and pass `after_section=<banner name>` so the host row
   sits directly after the banner (a stranded empty banner breaks the whole form's render).
   Row cap is `MaxRow` on the host column.
   ⚠️ **HARD ORDERING (live-proven render-breaker, THE RULE trap): NEVER call `forge_apply_fields`
   with a `sections` re-layout AFTER `forge_add_table`.** A re-layout rebuilds the ROOT `Model::Row`,
   which (a) strands the child table's own schema Row (dangling `Model::Row` ref on the child Model)
   and (b) dumps the child columns into a stray form-level "Other" section. Result: the flow
   publishes Live and items walk fine, but the BUILDER FORM shows "There was an error / Reload" —
   Live+walks ≠ renders. Correct order: create process → ALL form fields + the FINAL section layout
   in as few `apply_fields` calls as possible (never a corrective re-layout later) → `add_table`(s)
   LAST with `after_section` → workflow → conditions → gotos → visibility → publish. If a layout fix
   IS needed after a table exists, DELETE+REBUILD the flow — never re-layout in place.

**4. Workflow — `forge_build_workflow`.**
   Needs `Model::ProcessDef` + `RootProcessDef` (the id as a string ref) + `Button::Row`.
   `WorkflowType:"Sequence"` means array order IS the flow — no forward-edge nodes. A `Parallel`
   built here is an UNCONDITIONAL and-fork (every branch always runs) until step 7. **A rebuild
   deletes EVERY Permission node** — treat "just rebuilt the workflow" as an automatic cue to
   rebuild the visibility matrix (step 8). It also strands in-flight items and any SequenceNumber
   Step stamp (a publish-500 cause). To slim a LIVE workflow, prefer `IsSuspended:true` on a step
   over deleting it — the runtime walks past a suspended step but keeps its node, so in-flight
   items are not orphaned. A bare/incomplete `ProcessDef` 500s on a draft PUT even unmodified —
   suspect the ProcessDef shape, not your own edit, if a process-draft PUT 500s.

**5. Assignees — only after members exist (step 0.5).**
   A step assignee is `Resource{ValueType:"AppRole", Value:<role id>}` — use AppRole, not User
   (a User assignee publishes but is ignored at runtime). Writing assignees before members exist
   fails publish. Membership grants the ability to act; the assignee tells the runtime WHO owns
   the step — both are required or first submit 500s.

**6. Branch conditions + goto gates — `forge_set_branch_conditions`, `forge_add_goto_gate`.**
   An `Expression`'s OWNER key decides what it is — `ProcessDef` = branch condition, `Activity` =
   goto loop condition, `Field` = computed formula, `Property` = value-generator (auto-number) —
   check the owner before reading any Expression as routing logic.
   - **Conditional split**: one Expression per branch on the branch's own `ProcessDef`, keyed to a
     deciding field's REAL literal. **Validate every literal against the live option list** — a
     mis-cased literal writes fine, publishes fine, and silently NEVER fires. Branches FAIL OPEN:
     a value matching no branch skips the whole Parallel and the item silently completes — leave
     NO real option unclaimed (`forge_set_branch_conditions` reports an `uncovered` bucket).
   - **Rework loop**: `forge_add_goto_gate` gates on a Boolean, FAIL-CLOSED. Pattern
     `<Boolean> = false()` (a zero-arg Function literal) — unticked keeps the item IN the loop; a
     trapped item is visible and fixable, a silently-skipped rework round is not. Never gate a loop
     on an optional Select (it escapes fail-open). A per-branch goto needs `branch_name` and stays
     branch-local — never cross-branch.

**7. Visibility matrix — `forge_set_visibility`.**
   `Permission{Column, Activity, Permission:"Editable"|"ReadOnly"|"Hidden"}`. Use the SECTION-level
   lever when a whole section shares a rule (one Permission vs one-per-field). `StartEvent` is
   position 0 — the first section must list `Start` as an owning step or the submit form renders
   empty. A Required field Hidden at its own step is fatal (nothing can satisfy it). Rebuild this
   after ANY workflow rebuild.

**8. Events (computed) — `forge_set_events`.** See step 2's computed layer.

**9. Styles — `forge_set_styles`.**
   Form sections take token refs only (read the real token name off the builder — a bogus token
   PUTs 200 and fails silently at render). Pages take raw CSS strings for dimensions and either
   raw hex or a token ref for color. Use a real token to complete a stranded style chain.

**10. Pages — `forge_build_page`, `forge_create_page`, `forge_set_navigation`, `forge_share_report`.**
   Widgets bind through one of three trios: view-type (`flow_type`/`flow_id`/`view_id`),
   report-type (single `report_id`, renders the report's own type), or native KPI
   (`metrics_type:"stepmetrics"`, flow id only). A page's content + behavior (widgets, KPIs,
   actions, popups, events) is governed; exact layout/color is NOT a build-correctness gate.
   API page-create does NOT touch navigation — wire the Menu via `forge_set_navigation`. Role-scope
   a menu with `Menu.VisibleTo:[<role ids>]` on a SHARED Navigation (no key = visible to all) rather
   than duplicating Menus per role. Reports have the same member surface as flows (`forge_share_report`).

**11. Publish — `forge_publish` (flows + pages), then `forge_publish_app` (the app itself).**
   App-level publish (`POST .../application/{app}/publish`) is SEPARATE from flow publish. Apps are
   born Draft. ⚠️ The builder's "Deploy" button is dev→UAT/prod PROMOTION — NEVER trigger it on dev.

**12. Verify — `forge_doctor` after every edit; `forge_compare_to_spec` if a spec exists.**

**13. Simulate — `forge_simulate_case`.** Walk a real item to completion. Two-item divergence
   (different deciding-field values landing on different steps) is the ONLY proof a split works.
   A loop-stays walk (Boolean unticked → item stays put) is the only proof a gate works.
   ✅ `forge_simulate_case` now accepts field NAMES directly in each step's `values` map (a
   field id like `Field_ab12` still works, and names+ids can mix) — it resolves names→ids off the
   live draft itself before the fill, so you no longer hand-resolve via `kf_get_flow_schema`. Only
   the KEY is resolved; a Select `value` must still be the exact option literal. An unknown name
   fails that step loud, listing every available field name. Resolution is scoped to root-model
   fields — a child-table field is addressed differently.

## Intent → tool map

| Intent | Tool(s) |
|---|---|
| Discover existing objects (sweep first) | `forge_sweep` |
| Exact wire shape for anything uncertain | `forge_capabilities(query)` |
| Create app / page | `forge_create_app`, `forge_create_page` |
| Create process (from template default) | `forge_create_process`, `forge_create_flow` |
| Create board (case) / dataform (dataset) | `forge_create_flow(kind="case"|"dataset")` |
| Create list + fill records | `forge_create_list`, `forge_dataset_records` |
| Fields / layout / validation / seq-number / table | `forge_apply_fields`, `forge_apply_layout`, `forge_add_field_validation`, `forge_add_sequence_number`, `forge_add_table` |
| Workflow | `forge_build_workflow` |
| Branch conditions / rework gate | `forge_set_branch_conditions`, `forge_add_goto_gate` |
| Roles / members / add users / tier / role default | `forge_create_app_role`, `forge_delete_app_role`, `forge_member_batch`, `forge_add_member_roles`, `forge_add_role_users`, `forge_grant_tier`, `forge_set_role_preference` |
| Visibility per step | `forge_set_visibility` |
| Computed / field events | `forge_set_events` |
| Styles | `forge_set_styles` |
| Pages / navigation / report sharing | `forge_build_page`, `forge_set_navigation`, `forge_share_report` |
| Publish flow+pages / publish app | `forge_publish`, `forge_publish_app` |
| Health check / spec compare | `forge_doctor`, `forge_compare_to_spec` |
| Walk a real item | `forge_simulate_case` |
| Confirmation artifacts | `forge_render_flow_diagram`, `forge_render_schema_diagram`, `forge_render_mockups`, `forge_request_confirmation` |
| Intake pipeline (optional macro) | `forge_intake_questions`, `forge_update_spec`, `forge_approve_spec`, `forge_plan_app` |
| Copilot fallback | `forge_copilot_ask`, `forge_copilot_check` |

Legacy `kf_*` tools (`kf_create_process`, `kf_get_flow_schema`, `kf_list_field_types`,
`kf_plan_field_change`/`kf_apply_field_change`, `kf_plan_step_visibility`/`kf_set_step_visibility`,
`kf_publish`) are the older thin surface — prefer the `forge_*` tools above.

## Refuse loudly — name the reason, never best-effort

The forge refuses the API-impossible at compile rather than degrading. When asked for one of
these, say so and name the reason; do not fake success.

| Refuse | Reason |
|---|---|
| Cross-branch / branch-to-root goto jump | No proven live shape; `doctor` flags a goto whose target sits in a different ProcessDef as "jumps out of its own branch." Keep gotos branch-local. |
| Aggregate / arbitrary live-number KPI binding on a page | No shape reaches a freely-bound single live value through engine+API. The native `stepmetrics` widget (a fixed per-step analytics table) is the only buildable live-number substitute. |
| Custom-component install | A custom component needs an installed bundle; there is NO API install path. |
| Environment "Deploy" on dev | Deploy = dev→UAT/prod promotion. Publish (`forge_publish_app`) is the dev-local go-live; NEVER trigger Deploy. |
| Bare `User` field without a QueryDefinition | A `User` field blocks publish until its `Field::QueryDefinition{FlowType:"User"}` is wired against a real user source. |

NOT refused anymore: adding a user to a role — that's solved via `forge_add_role_users`
(the `Users`-write / `Members`-read asymmetry).

## Copilot fallback doctrine

`forge_copilot_ask` drives Kissflow's in-builder AI assistant (headless). It can build almost
ANYTHING — full opinionated apps from one prompt — but it is SLOW (a change can land ~70s after
the reply), INCONSISTENT (misses in N attempts, or builds into a DIFFERENT flow of its own
choosing and scatters scratch lists), and sometimes FABRICATES success (a concrete-sounding
reply while zero graph keys changed).

- **Never trust the reply.** The reply lags, outruns, or misdescribes the graph. Always
  `forge_copilot_check` / read the graph back across ALL flows in the app (it is app-scoped, not
  flow-scoped) and clean up scattered scratch objects.
- A miss is an inconsistency observation, NOT a "cannot" — retry with a rephrase and a fresh poll
  window before concluding anything.
- Copilot answers clarifying questions in-thread (it may ask "which step + assignee?" on a
  step-less process) — answer in-thread.
- **Copilot is the coverage/capture factory; the deterministic `forge_*` tools are correctness.**
  For anything that must be RIGHT, use the direct tools and verify by read-back + a real item walk.

## Gotcha — never name a banner Section the same as its table

A table's host is a `Column{Type:"Model"}`; a banner Section is a `Column{Type:"Section"}`.
If both carry the SAME Name (e.g. both "FDE Log"), an `owners` key in `forge_set_visibility`
used to resolve to the host (empty) and hard-reject the banner's field as "outside every
matrix section". The engine now resolves a section-owner name to the Section node first, but
DON'T rely on it — give the banner Section a distinct name (e.g. "FDE Log Notes") from the
table ("FDE Log"). Proven live building a sample Case form 2026-08-12.
