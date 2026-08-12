---
id: field.checklist
name: Checklist field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Checklist"
shapes:
  - shapes/field_checklist.json
params:
  - name: ReferredList
    type: string
    required: true
    default: null
    constraints:
      - "an existing list-flow id in the same app — the seed items"
    depends_on:
      - "the list flow must exist before this field is written"
    status: captured
  - name: CanCreate
    type: boolean
    required: false
    default: false
    constraints:
      - "may the user ADD checklist items at runtime"
    depends_on: []
    status: captured
  - name: CanDelete
    type: boolean
    required: false
    default: false
    constraints:
      - "may the user REMOVE checklist items at runtime"
    depends_on: []
    status: captured
---

## What

A set of tickable items, `Type:"Checklist"`, seeded from a list flow
(`ReferredList`), with `CanCreate`/`CanDelete` controlling whether the user may
add or remove items at runtime.

## Where

Form builder field palette ("Checklist"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- Create the seed **list flow first** (master data before the field).
- Set `CanCreate`/`CanDelete` deliberately — a fixed compliance checklist wants
  both false; a working to-do list wants both true.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

List/Select family. A source could drive it via `forge_set_events` (trigger
family-inferred `onClick`, unverified). Any field can be a computed target.

## Gotchas

Off-list values discard silently like the other list-backed fields — read live
options before writing.
