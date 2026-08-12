---
id: field.email
name: Email field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: "yes"
ui_path: "Form builder > field palette > Email"
shapes:
  - shapes/field_email.json
params:
  - name: Required
    type: boolean
    required: false
    default: false
    constraints: []
    depends_on: []
    status: captured
---

## What

A single email address, `Type:"Email"`. No extra per-type key beyond the
standard envelope was captured in copilot's default build.

## Where

Form builder field palette ("Email"). Captured on a dataform (and driven on the
process form). Board not yet swept.

## Best practice

- **Validation** — Kissflow likely enforces address format natively; add an
  explicit rule only for extra constraints (a required domain).
- **Computed** — pre-fill an email from a related record with a source-field
  event rather than re-typing it.

## Validation

`forge_add_field_validation` writes a `FieldValidation::Criteria -> Condition`
(mechanism captured, CLAUDE.md F7). Whether Email carries built-in format
validation and which extra operators apply is a config-tabs sweep (#48) — treat
as inferred until run.

## Computed

No formula type. Set the value from a script on a **source** field
(`forge_set_events`). Email is Text-family; a source is family-inferred to fire
`onChange` (unverified live). Any field can be a computed target.
