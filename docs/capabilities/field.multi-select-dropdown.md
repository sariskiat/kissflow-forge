---
id: field.multi-select-dropdown
name: Multi-select dropdown field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Multi-select dropdown"
shapes:
  - shapes/field_multiselect.json
params:
  - name: ReferredList
    type: string
    required: true
    default: null
    constraints:
      - "an existing list-flow id in the same app — never invent one"
    depends_on:
      - "the list flow must exist before this field is written"
    status: captured
  - name: Required
    type: boolean
    required: false
    default: false
    constraints: []
    depends_on: []
    status: captured
---

## What

Pick MANY options from a list, `Type:"Multiselect"`. Its options live in a
separate list flow, referenced by id via `ReferredList` — the same list-backed
pattern as Select, Checkbox, and Radio.

## Where

Form builder field palette ("Multi-select dropdown"). Captured on a process
form. Board and dataform not yet swept.

## Best practice

- **Read the live options** (`GET .../list/{id}/items`) before writing any
  value — an off-list value PUTs 200 and silently clears the field.
- Create the list flow first (build order: master data before the field).
- **Validation / computed** — as with any field; usually the list itself is the
  constraint.

## Validation

`forge_add_field_validation` writes a `FieldValidation::Criteria -> Condition`
(mechanism captured, CLAUDE.md F7); exact operators for a multi-select are a
config-tabs sweep (#48), inferred until run.

## Computed

No formula type. Set from a source-field event (`forge_set_events`).
Select-family; a source is family-inferred to fire `onClick` (Select is
live-confirmed onClick; Multiselect unverified). Any field can be a target.

## Gotchas

The write API never validates a value against the list — always read back after
writing.
