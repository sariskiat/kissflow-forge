---
id: config.computed
name: Computed field (formula builder, Field-owned Expression)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field > Settings tab > Is this a computed field? > Formula builder"
routes:
  - "GET/PUT /metadata/2/{acct}/{type}/{id}/draft?_application_id={app}"
shapes:
  - shapes/field_computed_expression.json
params:
  - name: Field::Expression
    type: list[string]
    required: true
    default: null
    constraints:
      - "one Expression node id; the Expression carries Field back-ref + ExpressionStr + Expression::Node AST"
    depends_on:
      - "every Node{Type:Field} ref must point at a real field id; back-refs maintained like all Expressions"
    status: captured
  - name: ExpressionStr
    type: string
    required: true
    default: null
    constraints:
      - "readable mirror only, never evaluated; references fields BY ID"
    depends_on: []
    status: captured
---

## What

Computed fields are first-class: the Settings tab's "Is this a computed
field?" toggle opens a Formula builder, and saving writes a **fourth
Expression owner** — the Field itself (`Field::Expression`). The AST is the
same Node family as branch conditions (Function root, Static/Field children,
`FieldRefCount`). Toggling computed DISABLES DefaultValue. This replaces the
old "no formula or computed field type" belief; field events remain a
separate script-based mechanism.

## Where

Per-field Settings tab. Function catalog captured: `rand randBetween
dateDiff calendarDays currency number if concatenate date dateTime
dateFromText dateTimeFromText now initiatedat today isBlank false true not`.

## Best practice

- Build the Node AST, not just ExpressionStr (mirror-only, id-referenced).
- Insert field refs by id; validate every referenced field exists before
  writing (the builder refuses to save unresolved refs — the API won't).
- Do not offer a computed value as runtime-proven yet: the formula did NOT
  evaluate on an admin data-plane fill (stayed null); evaluation looks
  client-side or submit-time. Verify with a real UI submit before claiming
  the value lands in stored data.

## Gotchas

The earlier one-time `=IF(...)`-in-DefaultValue sighting is best explained
as this feature — the current builder writes `Field::Expression`, never a
DefaultValue formula. Copilot asks for computed fields went 0/3 in the
config-tabs sweep (inconsistent); the deterministic path is writing this
shape directly.
