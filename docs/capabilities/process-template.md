---
id: process-template
name: Process-template identity/initiate shell (from_template)
status: captured
modules:
  process: "yes"
  board: "no"
  dataform: "no"
ui_path: "n/a — engine-side scaffold, not a builder UI surface"
routes:
  - "POST /flow/2/{acct}/process?_application_id={app}"
  - "GET/PUT /metadata/2/{acct}/process/{id}/draft"
shapes:
  - shapes/process_template_identity_shell.json
  - shapes/process_skeleton.json
params:
  - name: from_template
    type: boolean
    required: false
    default: true
    constraints:
      - "create_process / create_flow_any(kind=\"process\") both default to True (issue #59: \"every process starts from a structure-clone\") — pass False for the old bare single-step scaffold"
      - "steps= is IGNORED when from_template is True; the shell defines its own single \"Manager Approve\" step, rebuild the real workflow with build_workflow/forge_build_workflow afterward"
      - "offline-verified only (unit tests over a mock KfClient) — NOT yet run against a live dev tenant; the shell's SOURCE prod template is proven published/rendering, the CLONE path on dev is not"
    depends_on: []
    status: captured
  - name: template_path
    type: string
    required: false
    default: null
    constraints:
      - "explicit arg > KF_PROCESS_TEMPLATE env var > the shipped shapes/process_template_identity_shell.json default"
      - "a plain filesystem path, not a shapes/<name> lookup — a tenant-specific override lives outside this repo, never hardcoded into the engine"
    depends_on: []
    status: captured
---

## What

Every process this engine creates now starts from a cloned SHELL instead of
a bare single-placeholder-step scaffold: an identity/initiate field block
(requestor/manager/department/branch-style fields), the section/row/column
layout that hosts them, the mandatory `Model::Appearance -> Appearance ->
Style` chain, a single `"Manager Approve"` UserTask, and `Button::Row`.
`kfforge.graph.clone_template_shell` grafts the shell onto a freshly created
process draft's own root Model (fresh Sample ids re-minted via
`kfforge.pages._instantiate` — the same clone machinery `nav.py` already
reuses from `pages.py`), then the caller adds their own fields/workflow on
top. `from_template=False` still yields the original bare
`ensure_process_def` scaffold for callers that want to start from nothing.

The shell itself (`shapes/process_template_identity_shell.json`) is a
de-identified capture of a REAL, published production process template
(280 nodes on the source tenant) — structure only, not a literal 1:1 clone:
5 `QueryDefinition` nodes (prod-tenant list/user bindings) were stripped,
the 2 `Reference` fields and 3 `User` fields they belonged to converted to
plain `Text` (each `Name` flagged with a TODO), and every
`Permission`/`Resource`/`Criteria`/`Condition`/`Expression`/`Node` (in-flight
state and the branch/validation AST) dropped outright as out of scope for an
identity shell. See `shapes/process_template_identity_shell.json`'s own
`notes` for the full de-identification story.

## Where

Engine-side only — `kfforge.graph.clone_template_shell`, wired into
`create_process` and `create_flow_any(kind="process")` in `kfforge/client.py`,
exposed through the `forge_create_process` / `kf_create_process` /
`forge_create_flow` MCP tools. There is no builder UI surface for this; it is
what those tools write BEFORE a human ever opens the draft.

## Best practice

- Leave `from_template=True` (the default) unless a caller genuinely wants
  the old bare scaffold — issue #59's decision is that every process built
  through this engine starts from the same known-good identity shape rather
  than an empty draft, so grilling/spec work stacks on a proven foundation.
- The shell's 3 retyped `Text` fields (originally `User`) are marked with a
  `(TODO: was a User field ...)` `Name` — reconnect them to `Type:"User"` +
  `Field::QueryDefinition{FlowType:"User"}` per
  `shapes/field_user_reference.json` once a dev-tenant `User`/`_employee`
  source exists to bind against (see `docs/capabilities/field.user.md`).
  Similarly for the 2 retyped `Reference` fields — reconnect a `ReferredList`
  once a real dev-tenant list exists.
- `KF_PROCESS_TEMPLATE` lets a deployment point at its OWN de-identified
  template instead of the shipped default, without touching engine code — a
  real tenant's template itself must never be committed to this repo (only a
  de-identified shape may ship here, same rule as every other `shapes/*.json`
  capture).
- Follow the engine's own CLAUDE.md Build order after cloning: members
  before assignees, assignees before a real workflow rebuild, a visibility
  matrix rebuild after any workflow rebuild.

## Gotchas

- `clone_template_shell` is idempotent the same way `ensure_process_def` is:
  called again on a draft that already has a `RootProcessDef`, it returns an
  unchanged deep copy rather than grafting a second shell on top.
- The shell has NO members and NO step assignee — `forge_create_process`'s
  own docstring already says follow with `forge_member_batch` before
  anything expects the "Manager Approve" step to be actionable (CLAUDE.md
  Members first).
- A from_template clone is NOT a substitute for `forge_doctor` /
  `forge_simulate_case` — THE RULE in CLAUDE.md still applies: cloning a
  proven shape publishing clean on the SOURCE tenant proves nothing about
  the CLONE publishing clean on a different (dev) tenant until it's actually
  verified there.
