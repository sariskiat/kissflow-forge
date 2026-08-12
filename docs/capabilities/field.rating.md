---
id: field.rating
name: Rating field
status: captured
modules:
  process: "yes"
  board: unknown
  dataform: unknown
ui_path: "Form builder > field palette > Rating"
shapes:
  - shapes/field_rating.json
params:
  - name: AllowHalf
    type: boolean
    required: false
    default: false
    constraints:
      - "whether half-star ratings are allowed"
    depends_on: []
    status: captured
  - name: DefaultValue
    type: string
    required: false
    default: "0"
    constraints:
      - "wire string"
    depends_on: []
    status: captured
---

## What

A star rating. Captured as `Type:"StarRating"` (not `"Rating"`) with
`DefaultValue` and `AllowHalf`. This closes the CLAUDE.md half-state — a Rating
shape that previously had no confirmed build path now has a captured `Type`.

## Where

Form builder field palette ("Rating"). Captured on a process form. Board and
dataform not yet swept.

## Best practice

- Enable `AllowHalf` only when half-star granularity is meaningful.
- Good for feedback/satisfaction capture; pair with a page report for a rollup.

## Validation

`forge_add_field_validation` writes a `Condition` (mechanism captured, CLAUDE.md
F7). Exact operators are a config-tabs sweep (#48).

## Computed

Number-family. A source could set it via `forge_set_events` (trigger
family-inferred `onSelect`, unverified). Any field can be a computed target.

## Gotchas

The palette says "Rating" but the node `Type` is `"StarRating"` — do not write
`Type:"Rating"`.
