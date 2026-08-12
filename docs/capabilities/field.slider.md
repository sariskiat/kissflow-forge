---
id: field.slider
name: Slider field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Slider"
shapes:
  - shapes/field_slider.json
params:
  - name: MinValue
    type: string
    required: true
    default: "0"
    constraints:
      - "wire string; the slider's lower bound"
    depends_on: []
    status: captured
  - name: MaxValue
    type: string
    required: true
    default: "100"
    constraints:
      - "wire string; the slider's upper bound"
    depends_on: []
    status: captured
  - name: IntervalSize
    type: string
    required: true
    default: "1"
    constraints:
      - "wire string; the step between allowed values"
    depends_on: []
    status: captured
  - name: DefaultValue
    type: string
    required: false
    default: "0"
    constraints: []
    depends_on: []
    status: captured
---

## What

A number chosen on a slider, `Type:"Slider"`, bounded by `MinValue`/`MaxValue`
and stepped by `IntervalSize` (all wire strings).

## Where

Form builder field palette ("Slider"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- The **min/max/interval are the built-in range validation** — a Slider
  constrains itself, so no separate validation rule is needed for bounds.
- Set the interval to a meaningful step (whole numbers, tens) rather than
  leaving `"1"` blindly.

## Validation

Bounds are native (min/max/interval). For anything beyond bounds,
`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7); exact operators are a config-tabs sweep (#48).

## Computed

Number-family. A source could set it via `forge_set_events` (trigger
family-inferred `onSelect`, unverified). Any field can be a computed target.
