## Tables

**A table is a nested `Model`, not a field type.** There is no "table" field —
a table is an entire child Model hung off a host column:

```
root Model  --Model::Model-->  ["Sample_Table"]
Row --Row::Column--> Column { Type:"Model", AllowImport, Column::Model:[<table id>], MaxRow:<n> }   # host row (root-level) + host column, full row width
Model  { Id:<table id>, Model:<parent>, Column:<host>,
         Model::Row:[1 schema row], Model::Field:[...] }
child Field { ..., Model:<table id> }                                          # a normal Field, parented to the table
```

- **The row cap lives as `MaxRow` on the HOST column**, not as a validation
  rule on a child field. It's native — no scripting needed to enforce a max
  row count. Don't confuse it with a string-length rule on a child field,
  which is a different kind of condition entirely.
- Child columns are `Start=0/End=0` — the 6-unit row grid from Node-graph
  invariants does not apply inside a table; a table's own columns aren't
  positioned that way.
- **A table host cannot live inside a Section.** Wiring the host Row into a
  Section's own `Column::Row` still returns 200 on write and 200 on publish —
  and the section then renders completely empty in the builder anyway. A
  table host must sit in its own root-level Row, never nested inside a
  Section's row. The working pattern is a Section used purely as a banner
  immediately above the table, with the table's own root Row directly below
  it — not the table nested inside the section. That root Row must itself be
  **registered in the root Model's own `Model::Row` list** — the same place
  the table's own id lands in `Model::Model` — or the Row exists as a node
  but isn't actually part of the form's layout, no matter how correctly its
  own columns are wired.
- ⚠️ **CONFIRMED on the live builder oracle: a banner Section and its table host must be
  ADJACENT in root `Model::Row` — the banner row immediately followed by the table-host row.**
  `add_table` (graph.py ~592) does `root.setdefault("Model::Row", []).append(host_row)` — it
  unconditionally APPENDS the host to the END. When a banner Section was created for the table,
  appending strands the empty banner: other sections fall between it and its table, leaving a
  standalone empty Section (`Column::Row=[]`, zero fields). The builder then renders
  "There was an error / Reload" for the WHOLE form — it will not even open. An empty Section is
  renderable ONLY as a caption directly above its table (the banner→table unit in the golden
  reference); stranded, it is the render-breaker.
  - It is NOT the empty `Column::Row: []` key — removing that alone did NOT fix it (verified on
    the oracle first). The fix that rendered the form: reorder root `Model::Row` so the table host
    sits immediately after the banner (matches the golden reference).
  - The semantic comparator never caught this: its section-order check EXCLUDES the table host
    (`Column{Type:"Model"}`, not a Section), so a misordered host is invisible — the rebuild read
    as "1 gap" while being completely unrenderable. HTTP 200 + publish + doctor-clean +
    compare-clean all lied; only the builder UI told the truth.
  - **Fix landed (#10, 2026-08-12):** `add_table`/`forge_add_table` take `after_section: <banner
    name>` and INSERT the host directly after that section's root row (unknown name raises before
    any write; omitted = old append behavior). The banner Section itself stays caller-created
    (`regroup_into_sections` with an empty field list). Still owed elsewhere: the comparator must
    diff root `Model::Row` order INCLUDING the table host, not around it (#16).
- ⚠️ **A table host and its child columns take NO Permission, and never break the step-visibility
  coverage check (fix landed 2026-08-12).** A table host (`Column{Type:"Model"}`) sits in its own
  root Row, outside every Section — legitimately so. `set_step_permissions`'s "every field column
  must belong to a matrix section" rule used to reject any table-bearing flow as "field columns
  outside every matrix section", making `forge_set_visibility` and `forge_add_table` mutually
  exclusive (a live blocker on any process with a table). The coverage rule now excludes the table
  host AND the table's child columns, and the host emits no Permission (Kissflow shows/hides the
  WHOLE table, not its host cell). The child-column exclusion is detected two independent ways —
  the nested Model's `Column` back-ref OR the host column's own `Column::Model` — so a live
  read-back that drops one signal still resolves the table (`graph._table_model_ids`).
