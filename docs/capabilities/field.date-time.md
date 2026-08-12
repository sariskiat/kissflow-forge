---
id: field.date-time
name: Date & Time field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: "yes"
ui_path: "Form builder > field palette > Date & Time"
shapes:
  - shapes/field_datetime.json
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

A calendar date plus time-of-day, one node `Type:"DateTime"`. Copilot's default
build writes no extra per-type key beyond the standard field envelope.

## Where

Form builder field palette ("Date & Time"). Captured on both a process form and
a dataform. Board not yet swept.

## Best practice

- **Validation** — bound the date with a field validation rule (no past dates,
  within a window) so bad dates are caught on the form.
- **Computed** — derive a date (a due date = submitted + N days) with an event
  on the source field rather than asking the user to compute it.

## Validation

`forge_add_field_validation` writes a `FieldValidation::Criteria -> Condition`
on the field (mechanism captured, CLAUDE.md F7). The exact operators for a date
range are a config-tabs sweep (#48), treat as inferred until run.

## Computed

No formula type. A computed date value is set by a script on a **source** field
(`forge_set_events`). A DateTime source fires **`onSelect`** (live-confirmed,
CLAUDE.md #12). Any field can be a computed target.
