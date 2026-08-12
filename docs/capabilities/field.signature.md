---
id: field.signature
name: Signature field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Signature"
shapes:
  - shapes/field_signature.json
params:
  - name: AllowDraw
    type: boolean
    required: true
    default: true
    constraints: []
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

Captures a drawn signature, `Type:"Signature"`. Carries `AllowDraw` (boolean,
captured true).

## Where

Form builder field palette ("Signature"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- Use for sign-off steps; pair with a step permission so it is editable only at
  the approving step.
- **Validation** — presence (Required) is the lever.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

Signature is one of the **six event-less types** — no Event tab, **cannot be a
computed source** (CLAUDE.md Field events). Can be a computed target.
