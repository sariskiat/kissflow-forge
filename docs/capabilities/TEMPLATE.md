---
id: TEMPLATE
name: Select field (sample entry — copy this file, replace every value)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Dropdown"
routes:
  - "GET /flow/2/{acct}/list/{list_id}/items"
shapes:
  - shapes/field_select.json
params:
  - name: ReferredList
    type: string
    required: true
    default: null
    constraints:
      - "must be an existing list-flow id in the same app — never invent one"
    depends_on:
      - "the list flow must exist before this field is written"
    status: captured
  - name: Required
    type: boolean
    required: false
    default: false
    constraints: []
    depends_on: []
    status: proven-live
---

<!--
Schema (decided on ticket #43, map #42 — enforced by tests/test_capability_docs.py):

- id: relative path under docs/capabilities/ minus .md (this file: TEMPLATE).
- status: doc rollup = the WEAKEST param status.
    proven-live  — runtime-verified end to end on the dev tenant
    captured     — read off a built graph (copilot/builder), runtime unverified
    inferred     — never observed, family-inferred
- modules: one of "yes" / "no" / differs / unknown per process/board/dataform.
  QUOTE yes/no (bare yes/no parse as YAML booleans; the validator normalizes,
  but quoting keeps the file honest). Any `differs` requires a "## Module
  diffs" prose section.
- shapes: links into shapes/*.json, required unless status is inferred.
  Every path must exist.
- params: name = the Kissflow node key verbatim (e.g. CurrencyTypes).
  constraints / depends_on are free-text strings — carried to the MCP layer
  as description text, not machine-evaluated.
- Real-tenant names never enter this dir — de-identify to synthetic names
  first (tests/test_p0_scaffold.py's blindness scan sweeps every .md here).

Prose sections below: What / Where / Best practice are required headings.
Module diffs required iff any module is `differs`. Gotchas optional.
-->

## What

Single-select field whose option values live in a separate list flow,
referenced by id via `ReferredList`. The write API never validates a value
against the options — a value outside the list PUTs 200 and silently clears
the field.

## Where

Form builder field palette ("Dropdown"). Available on the process form
surface; board/dataform availability unknown until their sweeps run.

## Module diffs

None captured yet — board and dataform are `unknown`, not `differs`.

## Best practice

Read the live option values (`GET .../list/{list_id}/items`) before writing
any literal that must equal one — expression literals and item-fill values
both fail silently on mismatch. Always read back after writing a Select.

## Gotchas

A blank optional Select never equals any literal — gate loops on a Boolean
field instead (see CLAUDE.md, Gate polarity).
