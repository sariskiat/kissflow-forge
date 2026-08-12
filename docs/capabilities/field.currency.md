---
id: field.currency
name: Currency field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Currency"
shapes:
  - shapes/field_currency.json
params:
  - name: CurrencyTypes
    type: list
    required: true
    default: null
    constraints:
      - "a LIST of currency codes (captured: [\"USD\"]), never a bare string"
    depends_on: []
    status: captured
  - name: Decimalpoint
    type: string
    required: false
    default: "2"
    constraints:
      - "a wire STRING holding a digit count, not a number"
    depends_on: []
    status: captured
  - name: DefaultValue
    type: string
    required: false
    default: "0"
    constraints:
      - "a wire STRING, not a JSON number"
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

A money value. Carries a currency set (`CurrencyTypes`, a list of codes such as
`["USD"]`) and a fixed number of decimal places (`Decimalpoint`). Copilot's own
default build sets `DefaultValue:"0"`, `Decimalpoint:"2"`, `CurrencyTypes:["USD"]`.

## Where

Form builder field palette ("Currency"). Captured on the process form. Board
and dataform availability not yet swept.

## Best practice

Offer the user more than a bare money box:
- **Validation** — cap or floor the amount with a field validation rule (see
  below), so a bad number is caught on the form, not downstream.
- **Computed** — if the amount is derived (quantity × unit price, a running
  total), compute it with an event on the source field instead of asking the
  user to type it.
- Set the currency set deliberately; leaving `["USD"]` may be wrong for the
  business.

## Validation

Attach a rule with `forge_add_field_validation` — it writes a
`FieldValidation::Criteria -> Condition{Operator, RHSValue}` subtree on the
field. The mechanism is captured live (CLAUDE.md F7). The exact operator set
valid for a Currency field (a max amount, a min amount) is a config-tabs sweep
(#48) not yet run, so treat specific operators as `inferred` until then.

## Computed

Kissflow has no formula field. A computed Currency value is set by a script on
a **source** field via `forge_set_events` (`Field::Event{Trigger, Script}`).
The trigger is a function of the source field's type. Currency itself is not
yet in `trigger_for`; as a source it is family-inferred to fire `onSelect`
(the Number family), unverified live. Any field can be a computed **target**.

## Gotchas

`CurrencyTypes` is a list — a bare string silently misconfigures the field.
`DefaultValue`/`Decimalpoint` are wire strings, not numbers.
