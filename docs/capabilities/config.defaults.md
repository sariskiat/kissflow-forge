---
id: config.defaults
name: Default values (static literal + relative-date keyword)
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field > Settings tab > Default value"
routes:
  - "GET/PUT /metadata/2/{acct}/{type}/{id}/draft?_application_id={app}"
shapes:
  - shapes/field_validation_criteria.json
params:
  - name: DefaultValue
    type: string
    required: false
    default: null
    constraints:
      - "static literal written verbatim on the Field node (Text \"N/A\" proven; Number already known)"
      - "\"Today\" = platform relative-date keyword for Date fields — same literal also valid as a validation RHSValue; read it, never guess casing"
      - "formula defaults (=IF(...)) seen ONCE in an earlier session, unreproduced since, runtime UNVERIFIED — do not offer as a capability yet"
    depends_on: []
    status: captured
---

## What

Two default mechanisms, both a plain `DefaultValue` key on the Field node:
a static literal written verbatim (Text/Number), and platform-recognized
relative keywords (`"Today"` on Date — not an ISO date, not a formula). No
Expression AST is involved in either.

## Where

Per-field Settings tab. The engine's `_TYPE_DEFAULTS` already writes
Number's `DefaultValue`; Text and the `"Today"` keyword extend the same key.

## Best practice

- Offer defaults as part of the whole field (build doctrine layer 4) — a
  static default costs one key.
- Treat `"Today"` as the only proven relative keyword; others (e.g.
  "Now", "CurrentUser") are guesses until captured.
- The suspected formula-default capability (`=IF(...)` on DefaultValue) is
  a one-time unreproduced sighting with no runtime proof — refuse to offer
  it until an item walk shows the formula actually evaluating.

## Gotchas

The computed-field toggle ask went 0/3 this probe (inconsistent). The one
prior `=IF(...)` capture remains the only sighting — top open item on the
config-tabs sweep, queued for builder-UI capture.
