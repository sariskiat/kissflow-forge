---
id: field.geolocation
name: Geolocation field
status: inferred
modules:
  process: unknown
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Geolocation"
shapes: []
params: []
---

## What

Captures a location (a real Kissflow field type — one of the six event-less
types listed in CLAUDE.md). Shape **not captured**: the copilot capture path
refuses it — copilot replied *"Location field type is not supported"* and offered
to substitute Text. So this is a real copilot limitation, not proof the type is
absent.

## Where

Form builder field palette ("Geolocation"). Copilot calls it "Location". The
capture path for this type is the **builder UI** (build one by hand, read back),
not copilot.

## Best practice

- Do not let copilot build a Geolocation field — it will silently substitute
  Text. If a build needs one, capture the real shape off a builder-authored
  example first (CLAUDE.md THE RULE: build the equivalent by hand, then diff).
- Geolocation is event-less — it cannot be a computed source.

## Validation

Unknown until the shape is captured — a config-tabs sweep (#48) plus a builder
capture owe this.

## Computed

One of the six event-less types (no Event tab) — cannot be a computed source.
Can be a computed target once the shape is known.
