---
id: field.checkbox
name: Checkbox field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Checkbox"
shapes:
  - shapes/field_checkbox.json
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

A list-backed MULTIPLE-choice group, `Type:"Checkbox"` — tick any of the options
that come from a list flow (`ReferredList`). This is **not** a single on/off
toggle: for a true boolean use the Boolean field (`Type:"Boolean"`,
shapes/field_boolean.json).

## Where

Form builder field palette ("Checkbox"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- Reach for the **Boolean** field, not this, when you need one true/false value
  (a loop gate must be a Boolean — CLAUDE.md Gate polarity).
- Create the list flow first; read live options before writing values.
- **Validation / computed** — as with any field.

## Validation

`forge_add_field_validation` writes a `FieldValidation::Criteria -> Condition`
(mechanism captured, CLAUDE.md F7); exact operators are a config-tabs sweep
(#48), inferred until run.

## Computed

No formula type. Set from a source-field event (`forge_set_events`).
Select-family; source family-inferred `onClick` (unverified). Any field can be a
computed target.

## Gotchas

Do not confuse this list-backed `Type:"Checkbox"` with the boolean
`Type:"Boolean"` — they are different node types with different uses.
