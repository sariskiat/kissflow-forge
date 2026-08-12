---
id: config.conditional-visibility
name: Conditional visibility tab (ColumnVisibility Criteria family)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field > Visibility tab (condition builder)"
routes:
  - "GET/PUT /metadata/2/{acct}/{type}/{id}/draft?_application_id={app}"
shapes:
  - shapes/criteria_column_visibility.json
params:
  - name: IsHidden
    type: boolean
    required: true
    default: null
    constraints:
      - "static hide on the TARGET column; the Criteria's Condition true reveals it"
    depends_on: []
    status: captured
  - name: LHSOwnField
    type: string
    required: true
    default: null
    constraints:
      - "points at the TRIGGER field's COLUMN id — not a Field id, not a page LHSVariable dot-path"
    depends_on:
      - "bidirectional back-ref: trigger column gains LHSOwnField::Condition"
    status: captured
  - name: IsOR
    type: boolean
    required: false
    default: false
    constraints:
      - "AND/OR combiner on the Criteria; multi-condition behavior uncharacterized (single-condition capture only)"
    depends_on: []
    status: captured
---

## What

Form-level conditional visibility (distinct from per-step Permission nodes
AND from page Container Criteria) — a THIRD `Criteria` owner family:
`ColumnVisibility`. The target column gets static `IsHidden: true` plus
`ColumnVisibility::Criteria` → `Criteria{IsOR}` → `Condition{Operator:
"EQUAL_TO", HasArguments: false, LHSOwnField: <trigger column>, RHSValue}`.
Boolean trigger values ride as the string `"true"`.

## Where

Per-field Visibility tab's condition builder. Coexists with the per-step
Permission matrix — two independent visibility layers.

## Best practice

- Distinguish the three Criteria families by owner key before interpreting
  any Criteria node: `Container` = page, `FieldValidation` = validation
  rule, `ColumnVisibility` = form-level conditional visibility.
- `HasArguments` differs by family (false here, true in validation) — copy
  the family's own capture, never a sibling's.
- Runtime toggle behavior is graph-verified only — walk a live item before
  claiming the show/hide actually fires (THE RULE).

## Gotchas

Conditional REQUIRED went 0/2 in the same probe (recorded inconsistent, not
impossible) — a sibling `ColumnRequired`-style family plausibly exists but
is uncaptured. Retry with "IsRequired"-flavored wording or capture from the
builder UI network tab.
