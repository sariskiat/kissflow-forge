## Write path

- **Snapshot the draft before any write** to a flow you did not just create
  yourself. To restore from a snapshot, stamp the flow's CURRENT
  `_meta_version` onto the snapshot body before you PUT it back — PUTting a
  stale `_meta_version` returns a metadata-conflict error, not a silent
  overwrite. Republish afterward so the live version actually matches the
  restored draft. **`_meta_version` changes only on publish**, never on a
  plain draft save — it is not a save counter, don't treat two draft saves as
  two versions.
- **Archive before deleting a process** — deleting an unarchived process
  fails outright; archive first, then delete. Forms (non-process flows)
  delete directly, no archive step needed.
- ⚠️ **A CORRECTED BELIEF (issue #59, 2026-08-12).** This used to say a
  `User`-type field blocks publish outright and its shape was uncaptured.
  The shape is now captured off a real, PUBLISHED builder example (a real
  production process template, 3 live User fields — see
  `shapes/field_user_reference.json`): `Field{Type:"User"}` plus a sibling
  `QueryDefinition{FlowType:"User", LHSModel:"User"|"_employee", Field:<field
  id>}` (and the field's own bidirectional `Field::QueryDefinition`
  back-ref). With that sibling present, the field publishes and renders
  fine. What still blocks publish is a **bare** `Field{Type:"User"}` with no
  `QueryDefinition` at all — that half of the old belief stands, just
  narrower than originally stated. **Runtime binding on THIS engine's own
  dev tenant remains unverified** — the proof above is that the shape
  publishes/renders on the SOURCE prod tenant, not that dev has an
  equivalent `User`/`_employee` source to resolve against; don't upgrade
  "publishes clean" to "usable end to end" without a live dev-tenant item
  walk through a User field (THE RULE, restated for this shape). See
  `docs/capabilities/field.user.md`.
- **`ReferredList` wiring is CAPTURED and proven (#13, 2026-08-12 — replacing
  the old "never synthesize" rule outright).** The whole chain is three
  probed routes plus one key: create a list flow with
  `POST /flow/2/{acct}/list?_application_id={app}` body `{"Name": ...}` →
  200 `{_id, Type:"List", Status:"Live"}` (born LIVE, no publish step;
  duplicate name 400s FlowNameAlreadyExists); SET its values with
  `POST .../list/{id}/items` body `{"ListItems": [...]}` — REPLACE
  semantics, proven by a two-write probe (a bare array 403s
  TypeMissMatchError, any other dict key 400s InvalidSchemaArguments); then
  write `ReferredList:<list_id>` on the Select's Field node. Proven end to
  end on a real item: a value from the list persists, a value outside it
  PUTs 200 and silently CLEARS the field (the Select discard rule, one
  notch worse than "discards" — it wipes what was there). Lists flagged as
  holding personal data stay human-made (PDPA, D2/D9).
- **Style tokens are not validated by the write API.** A completely bogus
  token name PUTs 200, publishes 200, and reads back verbatim — and then
  fails silently at render, with no error anywhere in the chain to tell you
  it was wrong. Never guess or probe token names against the API; read the
  real token names off the builder's own style dropdown. Setting a style
  property to `None` (rather than omitting it) is the only way back to the
  platform's own default — leaving the builder's defaults alone writes
  nothing at all, since Kissflow persists only non-default style values.
