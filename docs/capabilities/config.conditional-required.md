---
id: config.conditional-required
name: Conditional-required (FieldValidation EXPRESSION rule, inline KRE string)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field > Validation tab > conditional rule"
routes:
  - "GET/PUT /metadata/2/{acct}/{type}/{id}/draft?_application_id={app}"
shapes:
  - shapes/field_conditional_required.json
params:
  - name: Operator
    type: string
    required: true
    default: null
    constraints:
      - "wire-proven value is the literal string EXPRESSION — the whole rule lives in RHSValue, not in the Operator"
    depends_on: []
    status: captured
  - name: RHSValue
    type: string
    required: true
    default: null
    constraints:
      - "an inline KRE formula STRING, NOT a Node-AST — e.g. if(${'form.Trigger'} == 'Option A', ${'form.Target'} != null, true)"
      - "fields are referenced BY NAME as ${'form.<FieldName>'}, case-sensitive, unvalidated by the write API — read the real names, never guess"
    depends_on: []
    status: captured
  - name: RHSType
    type: string
    required: true
    default: null
    constraints:
      - "wire-proven value is the literal string Value (paired with HasArguments:true)"
    depends_on: []
    status: captured
  - name: ErrorMessage
    type: string
    required: false
    default: null
    constraints:
      - "human-readable text shown when the assertion fails — carry one on every rule"
    depends_on: []
    status: captured
---

## What

Make a field required only when another field meets a condition. The platform
writes a `FieldValidation`-owned `Criteria` -> `Condition` on the target field,
where `Condition{Operator:"EXPRESSION", RHSType:"Value", HasArguments:true,
ErrorMessage, RHSValue}` and `RHSValue` is an inline **KRE formula string**:

```
if(${'form.Trigger'} == 'Option A', ${'form.Target'} != null, true)
```

The formula returns `true` (valid) when the trigger does not apply, otherwise
asserts the target is non-null. So conditional-required is modelled as a
conditional **validation rule**, not a flip of the field's own `Required` flag.

This is the **FieldValidation owner family** — the same owner key as a plain
length/range validation rule (`config.validation`) — and is DISTINCT from the
`ColumnVisibility` owner used for conditional VISIBILITY
(`config.conditional-visibility`). Same `Criteria`/`Condition` Kind names,
different owner key, different purpose. Unlike branch/goto `Expression` nodes,
the rule is a plain **string**, not a `Node` AST, and fields are referenced BY
NAME (`${'form.<FieldName>'}`), not by id.

## Where

Per-field Validation tab in the form builder, as a conditional rule. Proven on
the process form surface; board/dataform availability unknown until their
sweeps run.

## Best practice

- Read the exact field NAMES off the live draft before writing the KRE string
  — names are case-sensitive and the write API never validates them, so a
  typo'd name PUTs 200 and simply never fires (the same silent-mismatch trap
  as any literal).
- Always write an `ErrorMessage` — it is the only feedback a user gets when
  the assertion blocks a submit.
- Keep the `true` else-branch: it is what makes the field optional in the
  non-triggering case. Drop it and the field reads as always-required.
- Runtime enforcement is UNVERIFIED — a coherent graph is not proof the rule
  blocks a submit (THE RULE). Confirm with a live item walk: set the trigger,
  leave the target blank, expect a block.

## Gotchas

Copilot structural builds AUTO-PUBLISH the draft without being asked
(`PublishedAt` moves) — take snapshots expecting the flow to already be live
afterward.
