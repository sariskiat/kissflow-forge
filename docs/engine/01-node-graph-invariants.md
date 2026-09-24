## Node-graph invariants

The write API enforces almost none of these. It will happily accept a graph
that is missing every one of them, return 200, and produce a flow that the
builder cannot render. These are the invariants the *builder*, not the API,
requires.

- **Every `Field` must carry a `Model` back-reference** (which model owns it)
  **plus a `CreatedAt` timestamp.** A Field missing `Model` will not render —
  the form silently drops it.
- **Node ids use capitalised prefixes**: `Field_`, `Column_`, `Row_`,
  `Resource_`. A lowercase `field_` id is wrong and will not be recognized as
  the node type it looks like.
- **Per-type keys** vary by field type and are easy to omit silently:
  - `Textarea` needs `AllowFormatting` (boolean).
  - `Number` needs `DefaultValue` and `Decimalpoint`.
  - `Attachment` needs `CaptureOnly` (boolean).
- **The style chain must exist COMPLETE on every flow**: `Model::Appearance` →
  `Appearance` → `Appearance::Style` → `Style`. A missing chain fails to
  render the page — and an INCOMPLETE one is exactly as fatal (proven live
  2026-08-12, replacing an earlier belief that only a wholly-absent chain
  breaks render): an `Appearance` whose `Appearance::Style` is EMPTY (zero
  `Style` children) throws the builder's "There was an error / Reload" for the
  whole form. doctor `ok`, publish 200, and a live item create all passed
  while the form stayed broken — only the builder UI caught it. The tell:
  Appearance-node count > Style-node count in the draft; each `Appearance`
  must own exactly one `Style`. `forge_set_styles` with a real token on the
  stranded section completes the chain and restores render.
- **A Row is a 6-unit grid.** Field columns tile `(0,2) (2,4) (4,6)` — start
  and end units along a 6-wide row, at most 3 columns per row. Overflow one
  Row (say, columns all pinned at `Start=0`, or more than 3 columns crammed
  in) and it breaks rendering for the *whole* flow, not just that row.

```
Field  { Id:"Field_Sample01", Type:"Text", Model:<root model id>, CreatedAt:"<timestamp>" }
Row    { Column:<section id>, Row::Column:[Column_Sample01, Column_Sample02, Column_Sample03] }
  Column_Sample01 { Type:"Field", Start:0, End:2 }   # tile 1 of 3, max per row
  Column_Sample02 { Type:"Field", Start:2, End:4 }   # tile 2 of 3
  Column_Sample03 { Type:"Field", Start:4, End:6 }   # tile 3 of 3 — 6 units, fully packed
```
This Row is nested inside a section, so its parent key is `Column:<section id>`; a
root-level Row that instead holds a *section* column carries `Model:<root model id>`
in that same slot.

The mandatory style chain from the bullet above lives on the **root Model**,
not on any one section or column:

```
Model      { ..., Model::Appearance:[Appearance_Sample01] }
Appearance { Id:"Appearance_Sample01", Kind:"Appearance", Model:<root model id>,
             Appearance::Style:[Style_Sample01] }
Style      { Id:"Style_Sample01", Kind:"Style", Appearance:"Appearance_Sample01" }
```

A **second, optional** Appearance/Style pair can hang off a
`Column{Type:"Section"}` instead of the root Model — that's the separate,
per-section colour-styling chain (its token rules are covered in Pages and
Build order), and it does not substitute for the mandatory Model-level chain
above:

```
Column { Type:"Section" } --Column::Appearance--> Appearance --Appearance::Style--> Style
```
