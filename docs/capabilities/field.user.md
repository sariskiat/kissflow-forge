---
id: field.user
name: User field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > User"
shapes:
  - shapes/field_user.json
params:
  - name: Field::QueryDefinition
    type: list
    required: true
    default: null
    constraints:
      - "the missing piece that CLAUDE.md said blocks publish — a child node with FlowType:\"User\""
    depends_on: []
    status: captured
  - name: AutoFill
    type: boolean
    required: false
    default: false
    constraints:
      - "captured on the QueryDefinition child (false)"
    depends_on: []
    status: captured
---

## What

Picks a Kissflow user, `Type:"User"`, with a `Field::QueryDefinition` child
(`FlowType:"User"`, `LHSModel:"User"`, `AutoFill`). Same Reference/QueryDefinition
family as Lookup and Remote lookup, differing only in `FlowType`.

## Where

Form builder field palette ("User"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- The **known publish-blocker**: CLAUDE.md marked the User field's required
  shape uncaptured and said it blocks publish outright. This capture supplies
  the missing `Field::QueryDefinition` child — but that a flow with this exact
  shape actually PUBLISHES is **still unverified**. Prove it live before
  trusting it in a build.
- **Computed** — a User source is family-inferred to fire `onSelect`
  (`trigger_for`, CLAUDE.md #12), so a User pick can drive a computed field.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators for a User field are a config-tabs sweep (#48).

## Computed

No formula type. A User source drives a target via `forge_set_events`; trigger
family-inferred `onSelect`. Any field can be a computed target.

## Gotchas

`ValueType:"User"` assignees are ignored by the runtime (use AppRole) — that is
a workflow-assignee gotcha (CLAUDE.md Members first), separate from this User
FORM field. Do not conflate the two.
