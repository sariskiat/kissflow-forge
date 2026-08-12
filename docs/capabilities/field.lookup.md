---
id: field.lookup
name: Lookup field
status: captured
modules:
  process: unknown
  board: unknown
  dataform: "yes"
ui_path: "Form builder > field palette > Lookup"
shapes:
  - shapes/field_lookup.json
params:
  - name: Field::QueryDefinition
    type: list
    required: true
    default: null
    constraints:
      - "the lookup lives in this child node, not in the field Type (which is \"Reference\")"
    depends_on:
      - "the referenced flow must exist before this field is written"
    status: captured
  - name: FlowType
    type: string
    required: true
    default: "Process"
    constraints:
      - "\"Process\" for a Lookup — this is the only thing that separates it from a Remote lookup (\"Dataset\")"
    depends_on: []
    status: captured
---

## What

Pulls values from a record in another flow. Captured as `Type:"Reference"` with
a `Field::QueryDefinition` child whose `FlowType` is `"Process"`. `LHSModel` is
the referenced flow id; `LookupField` lists the columns pulled across.

## Where

Form builder field palette ("Lookup"). Captured on a dataform. Process and board
availability not yet confirmed (copilot built it into a form when asked).

## Best practice

- Build the **referenced flow first** (build order: master data before the
  field that looks it up).
- Choosing Lookup vs Remote lookup is one value: `FlowType` `Process` vs
  `Dataset` — pick by whether the source is a process or a dataset/list.
- **Validation / computed** — usually the reference itself supplies the value;
  a validation rule on the field is available if needed.

## Validation

`forge_add_field_validation` writes a `Condition` on the field (mechanism
captured, CLAUDE.md F7). Exact operators are a config-tabs sweep (#48).

## Computed

The referenced record supplies the value; a computed override via a source-field
event is possible but unusual. Any field can be a computed target.

## Gotchas

`Type` is `"Reference"`, not `"Lookup"`. Per-field lookup/reverse-lookup runtime
routes are a known 500 dead-end (CLAUDE.md) — do not probe them.
