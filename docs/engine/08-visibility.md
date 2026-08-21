## Visibility

Per-step visibility has **two independent levers**, and both write the same
node shape:

```
Permission { Id, Kind:"Permission", Column:<column id>, Activity:<activity id>,
             Permission:"Editable"|"ReadOnly"|"Hidden" }
```

Back-references are bidirectional (`Column::Permission[]` and
`Activity::Permission[]`). Neither `GotoTask` nor a `Parallel` gateway nor
`SendBackToInitiator` carries any Permissions — they render no form, so there
is nothing to gate.

- **`Column` may be a SECTION column, not just a field column.** "Hide this
  whole section at this step" writes exactly one Permission whose `Column` is
  the *section's* column, not one Permission per field inside it. Using the
  section-level lever instead of one Permission per field per step is roughly
  an order of magnitude cheaper in node count for the same visible effect —
  prefer it whenever an entire section shares one visibility rule.
- Both layers can coexist on the same flow — field-level Permissions on
  individual fields, section-level Permissions on their container — without
  either overwriting the other. **Precedence between a section-level Hidden
  and a field-level Editable on a field inside that section is unverified** —
  don't rely on one silently overriding the other until you've captured which
  wins.
- Hidden columns (for example the host column behind a sequence-number style
  auto-generated field) and sequence-number columns themselves take no
  Permissions at all — a hidden column has no per-step visibility to set, so
  its absence from the matrix is not a gap.
- **`StartEvent` is position 0.** The very first section a user sees must
  list `Start` as one of its owning steps, or the submission form renders
  empty — there is nothing conceptually wrong with the form in that case, it
  is simply not visible at the step the user is standing on.
- **Required is scoped by per-step visibility.** A step's submit validation
  only enforces the Required fields that are actually visible at that step —
  marking a later-step field Required does not block submission of an earlier
  step. The inverse is the dangerous direction: **a Required field that is
  Hidden at its own step is still fatal** — nothing can ever satisfy it, and
  nothing downstream can submit past it either.

Any full workflow rebuild deletes every Permission node (see Workflow) — treat
"just rebuilt the workflow" as an automatic cue to rebuild the visibility
matrix next, every time, not just when something looks visibly wrong.
