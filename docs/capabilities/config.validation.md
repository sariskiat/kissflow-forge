---
id: config.validation
name: Validation rules tab (Condition Operator/RHSValue/ErrorMessage)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field > Validation tab"
routes:
  - "GET/PUT /metadata/2/{acct}/{type}/{id}/draft?_application_id={app}"
shapes:
  - shapes/field_validation_criteria.json
params:
  - name: Operator
    type: string
    required: true
    default: null
    constraints:
      - "wire-proven: MAX_LENGTH, CONTAINS, GREATER_THAN (Number), AFTER (Date)"
      - "reply-claimed only, each needs a live write before use: MIN_LENGTH, EQUAL_TO, NOT_EQUAL_TO, NOT_CONTAINS, STARTS_WITH, ENDS_WITH, regex, LESS_THAN, BETWEEN, BEFORE, Is Today/Future/Past"
    depends_on: []
    status: captured
  - name: RHSValue
    type: string
    required: true
    default: null
    constraints:
      - "always string-typed on the wire, even for numbers (\"0\")"
      - "\"Today\" is a platform relative-date keyword (also valid as a DefaultValue) — read literals, never guess casing"
    depends_on: []
    status: captured
  - name: ErrorMessage
    type: string
    required: false
    default: null
    constraints:
      - "human-readable failure text per Condition; the engine's add_field_validation cannot write it yet (gap)"
    depends_on: []
    status: captured
---

## What

The Validation tab writes `FieldValidation`-owned `Criteria` → `Condition`
nodes on the field: `Condition{Operator, RHSValue, HasArguments: true,
ErrorMessage}`. The platform creates ONE Criteria PER RULE — a field with two
rules owns two Criteria nodes (falsifies the engine's "one Criteria per
field" docstring as a platform description; the engine's additive reuse
still functions). "Must not be empty" is not a rule at all — the platform
flips the field's own `Required: true`.

## Where

Per-field Validation tab in the form builder, all form-bearing flows
(process proven; board/dataform unknown).

## Best practice

- Route "not empty" asks to `Required`, never to a synthesized Condition.
- Only the four wire-proven operators are safe to write; everything else in
  the Q&A list is a claim — capture a live write first.
- Always write an `ErrorMessage` — the platform's own builds carry one on
  every Condition; a rule without one shows the user nothing useful.
- Runtime enforcement of a written rule is unverified until an item walk
  fails on it — graph landing ≠ enforcement (THE RULE).

## Gotchas

Copilot structural builds AUTO-PUBLISH the draft without being asked
(`PublishedAt` moves) — take snapshots expecting the flow to already be live
afterward.
