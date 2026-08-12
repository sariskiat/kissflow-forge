---
id: field.aggregation
name: Aggregation field
status: captured
modules:
  process: unknown
  board: unknown
  dataform: "yes"
ui_path: "Form builder > field palette > Aggregation"
shapes:
  - shapes/field_aggregation.json
params:
  - name: Decimalpoint
    type: string
    required: false
    default: "2"
    constraints:
      - "a wire string digit count"
    depends_on: []
    status: captured
---

## What

Meant to roll up (sum / average / count) a column of a child table. Captured as
a bare `Type:"Number"` value-holder — **the aggregate binding (which table,
column, function) did NOT land on the node** in the capture, so this is a
partial capture.

## Where

Form builder field palette ("Aggregation"). Captured on a dataform. Process and
board not yet swept.

## Best practice

- Treat this as **incomplete** until the aggregate binding is captured — do not
  ship an Aggregation field claiming it sums a column without proving the
  binding lands and computes live.
- The binding location (a Property? an Expression? the host table column?) is a
  config-tabs / tables sweep (#48) that still owes this.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

The aggregate itself IS the computed behavior (once its binding is captured).
As a Number value-holder, a source event could also set it. Any field can be a
computed target.

## Gotchas

Copilot reported "sum of column X" success but wrote no binding — a textbook
THE RULE case: the reply lied, the graph is a bare Number. Verify the binding
before trusting any Aggregation build.
