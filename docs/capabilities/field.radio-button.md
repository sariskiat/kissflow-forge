---
id: field.radio-button
name: Radio button field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Radio button"
shapes:
  - shapes/field_radio.json
params:
  - name: Type
    type: string
    required: true
    default: "Select"
    constraints:
      - "captured as \"Select\" — a Radio is a single-select, not its own node type"
    depends_on: []
    status: captured
  - name: Widget
    type: string
    required: true
    default: "Radio"
    constraints:
      - "\"Radio\" is what makes a Select render as radio buttons instead of a dropdown"
    depends_on: []
    status: captured
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

Pick ONE option from a list, rendered as radio buttons. Captured as
`Type:"Select"` + `Widget:"Radio"` — a Radio is a single-select whose display
widget is radio, not a distinct node type. Options come from a list flow via
`ReferredList`.

## Where

Form builder field palette ("Radio button"). Captured on a process form. Board
and dataform not yet swept.

## Best practice

- Same underlying field as a dropdown Select — choose Radio (`Widget:"Radio"`)
  only for a short option set the user should see at once.
- Create the list flow first; read live options before writing values.
- **Validation / computed** — as with any field; the list is usually the
  constraint.

## Validation

`forge_add_field_validation` writes a `FieldValidation::Criteria -> Condition`
(mechanism captured, CLAUDE.md F7); exact operators are a config-tabs sweep
(#48), inferred until run.

## Computed

No formula type. Set from a source-field event (`forge_set_events`). A Select
source fires **`onClick`** (live-confirmed, CLAUDE.md #12). Any field can be a
computed target.
