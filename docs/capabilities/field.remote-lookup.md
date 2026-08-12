---
id: field.remote-lookup
name: Remote lookup field
status: captured
modules:
  process: unknown
  board: unknown
  dataform: "yes"
ui_path: "Form builder > field palette > Remote lookup"
shapes:
  - shapes/field_remote_lookup.json
params:
  - name: Field::QueryDefinition
    type: list
    required: true
    default: null
    constraints:
      - "the lookup lives in this child node; field Type is \"Reference\""
    depends_on:
      - "the referenced dataset (list flow) must exist before this field is written"
    status: captured
  - name: FlowType
    type: string
    required: true
    default: "Dataset"
    constraints:
      - "\"Dataset\" for a Remote lookup — the only difference from a Lookup (\"Process\")"
    depends_on: []
    status: captured
---

## What

Pulls values from a **dataset** (a list flow), where a plain Lookup pulls from a
Process. Captured as `Type:"Reference"` + `Field::QueryDefinition` with
`FlowType:"Dataset"`, `LHSModel` = the dataset id, `LookupField` = the columns
pulled.

## Where

Form builder field palette ("Remote lookup"). Captured on a dataform. Process
and board not yet confirmed.

## Best practice

- Build the **dataset / list flow first**.
- Same field family as Lookup and User — they differ only by
  `QueryDefinition.FlowType` (`Dataset` / `Process` / `User`).
- **Validation / computed** — the reference supplies the value; validation is
  available.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

The referenced record supplies the value. Any field can be a computed target.

## Gotchas

`Type` is `"Reference"`, not `"RemoteLookup"`. Per-field lookup runtime routes
are a known 500 dead-end (CLAUDE.md).
