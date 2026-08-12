---
id: field.image
name: Image field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Image"
shapes:
  - shapes/field_image.json
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

Holds an image upload, `Type:"Image"`. Carries `CaptureOnly` (boolean) — the
same per-type key Attachment uses.

## Where

Form builder field palette ("Image"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- Set `CaptureOnly:true` when the business needs a fresh photo (proof at the
  scene), false when an existing file is fine.
- **Validation** — presence (Required) is the main lever.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

Image is one of the **six event-less types** (Attachment, Image, Rich text,
Signature, Sequence number, Geolocation) — the builder offers no Event tab, so
it **cannot be a computed source** (CLAUDE.md Field events). It can still be a
computed target and take validation.
