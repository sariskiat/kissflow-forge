---
id: field.smart-attachment
name: Smart attachment field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Smart attachment"
shapes:
  - shapes/field_smart_attachment.json
params:
  - name: CaptureOnly
    type: boolean
    required: true
    default: false
    constraints:
      - "true = camera capture only, no file pick"
    depends_on: []
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

A file upload. The palette label "Smart attachment" maps to node
`Type:"Attachment"` (the same node the engine documents in
shapes/field_attachment.json). Carries `CaptureOnly`.

## Where

Form builder field palette ("Smart attachment"). Captured on a process form.
Board and dataform not yet swept.

## Best practice

- Same node as a plain Attachment — reuse the Attachment shape and rules.
- **Validation** — presence (Required) is the main lever.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

Attachment is one of the **six event-less types** — no Event tab, **cannot be a
computed source** (CLAUDE.md Field events). Can be a computed target and take
validation.
