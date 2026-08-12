---
id: field.scanner
name: Scanner field
status: inferred
modules:
  process: unknown
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > (Barcode)"
shapes: []
params: []
---

## What

A scan-input field. Shape **not captured**: copilot refuses the palette label
"Scanner" — it replied *"'Scanner' is not a supported field type in Kissflow.
Would you like to use 'Barcode'?"*. So the real Kissflow field type is likely
named **"Barcode"**, and "Scanner" is not it.

## Where

The real type name to build against is **"Barcode"** (per copilot's own reply).
Capture its shape off a builder-authored Barcode field, or re-drive copilot with
the label "Barcode".

## Best practice

- Do not build a "Scanner" field — use "Barcode". Capture the Barcode shape live
  before shipping (a follow-up sweep item).
- Re-driving copilot with `"Barcode"` is the cheap next step to capture it.

## Validation

Unknown until the Barcode shape is captured (config-tabs sweep #48 + a live
Barcode drive owe this).

## Computed

Unknown until captured.
