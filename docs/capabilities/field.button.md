---
id: field.button
name: Button (not a form field)
status: inferred
modules:
  process: unknown
  board: unknown
  dataform: unknown
ui_path: "App page builder > widget palette > Button (NOT a form field)"
shapes: []
params: []
---

## What

**Button is not a form field at all** — it is a page WIDGET. Copilot refuses to
add a "Button" field, replying *"'Button' is not a standard field type"*, which
is correct. There is no field-node shape to capture because none exists.

## Where

Buttons live on **app pages**, not on a form. See the Pages section of CLAUDE.md
— `general/button` is a page widget bound through `caption`/`size`/`type`/
`iconPosition` Properties.

## Best practice

- When a designer asks for a "button field", steer them to a **page button
  widget** (or a workflow action / submit), not a form field.
- This entry exists to record the finding so nobody re-sweeps it as a field.

## Validation

Not applicable — not a form field.

## Computed

Not applicable — a page button widget carries an `EventMapping` (on_click)
action, which is page-level behavior, not a computed field value.
