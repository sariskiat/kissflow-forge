## Item data plane

The runtime item walk, on the documented (non-builder) API:

```
create   POST /process/2/{acct}/{flow}                          -> _id + first activity-instance id
fill     PUT  /process/2/{acct}/admin/{flow}/{iid}              -> {field_id: value, ...}
submit   POST /process/2/{acct}/{flow}/{iid}/{aiid}/submit      -> advance one step
reject   POST /process/2/{acct}/{flow}/{iid}/{aiid}/reject      -> {"Comment": "..."}; sets status Rejected
detail   GET  /process/2/{acct}/admin/{flow}/{iid}              (the non-admin path 404s)
fields   GET  /process/2/{acct}/{flow}/fields                   -> all runtime fields, no option values
options  GET  /flow/2/{acct}/list/{list_id}/items               -> bare array of valid option strings
lists    GET  /flow/2/{acct}/list?page_size=100                 -> inventory of every list in the app
```

⚠️ **The raw `fill` PUT is keyed by field ID (`Field_ed539546e3`), never field NAME — a name
returns `KISSFLOW_ERROR_01003 FieldNotFound`.** But `forge_simulate_case` no longer forces the
caller to hand-resolve: each step's `values` KEYS may be a field NAME ("Business Unit ID") OR an
id, mixed freely, and the tool translates names→ids off the flow's live draft
(`dataplane.field_name_index`) before the fill. Only the KEY is resolved — a Select `value` is
still the exact option literal, unchanged. An unknown name fails that step loud, listing every
available field name (a Cowork user with only the MCP surface can't hand-resolve, so the tool must
and does). Resolution is scoped to ROOT-model fields on purpose: a child-table field can share a
display name with a root field, and a top-level admin fill only ever addresses root fields — a
table's rows go through the `Table::<child model id>` key below.

⚠️ **The `lists` route needs `_application_id` scoping too, the SAME leakage
class the flow-list route already has (see Members first)** — confirmed live
2026-08-07: `GET /flow/2/{acct}/list?page_size=100` with no `_application_id`
returned 100 lists (paginated) from an UNRELATED app in the same account;
adding `&_application_id={app_id}` to the SAME call returned the true,
correctly-scoped count for KF_APP (0, on the tenant checked).
`KfClient.list_lists` now wraps this route with the scoping baked in (#13);
`KfClient.get_list_items` is scoped by a specific `list_id` and has no
leakage risk — this note stays so nobody hand-rolls the unscoped URL and
reads, or later writes against an id sourced from, a DIFFERENT app's list.

- **The aiid trap:** the activity-instance id returned by a "my items"-style
  listing is the initiator's already-CONSUMED instance — submitting or
  rejecting against it fails with an "already used" style error. Never
  resurrect a myitems-style id as a fallback for anything below — that trap
  is exactly what the two-phase rule's own fallback (next paragraph) is NOT.

  ⚠️ **A CORRECTED BELIEF on "always fetch detail, use that id," captured
  live 2026-08-07 walking a real item from its start step through to
  completion.** The rule used to say the live activity-instance id is
  *always* `detail._current_context[0]._context_activity_instance_id` — true
  from the SECOND submit on, but wrong for the very first one. An item still
  sitting at its start step, never yet submitted, has no `_current_context`
  at all; the only usable id for THAT submit is the one the CREATE call's own
  response returned. The real rule is **two-phase**:

  | hop | step (example)  | ctx activity-instance id | id actually used   | result |
  |-----|------------------|--------------------------|---------------------|--------|
  | 1   | start step       | absent                   | the CREATE response's id | 200 |
  | 2   | 1st user step    | present                  | detail's context id | 200 |
  | 3   | 2nd user step    | present                  | detail's context id | 200 |
  | 4   | last user step   | present                  | detail's context id | 200 |
  | 5   | (none)           | —                        | —                    | status = Completed |

  So: fetch detail and use `_current_context[0]._context_activity_instance_id`
  whenever it is present — that part of the old rule still holds on every hop
  past the first. Only when it is genuinely absent, and only on the very
  first submit right after create, fall back to the id the create call
  itself returned. A missing context id on any LATER hop is still a real
  problem, not a second excuse to reuse the create-time id — reusing it
  there would recreate exactly the "stale/consumed id" failure mode this
  whole trap exists to avoid.
- **Select values PUT 200 and silently discard when the value isn't in the
  field's option list** — the write succeeds, and a read-back shows the field
  as empty. **Always read back after writing a Select**, and validate the
  value against the live option list before you ever write it (see
  Expressions for the identical trap on literals).
- Child-table rows surface in the item detail under a key shaped
  `Table::<child model id>` — the key is present only when rows actually
  exist; its absence means no rows, not "no such table." Rows are written
  through the same admin fill route, keyed by the child fields' own ids.
  `PUT {"Table::<id>": []}` returns 200 and clears nothing — an empty-array
  write is not how you delete rows; deleting the child schema is the only
  proven way to purge orphaned ones.
- Submit permission follows the step's AppRole assignment — the acting API
  user must actually be a member of that role (see Members first); there is
  no API route that grants role membership itself, only the builder UI does.
- A handful of routes are confirmed dead ends, worth knowing so nobody
  re-probes them: a legacy list-flow path is pure front-end with no
  API behind it; per-field lookup/reverse-lookup routes 500 on any editable
  Select; and no API route exists to reassign an in-flight activity to a
  different user. ⚠️ A CORRECTED BELIEF (2026-08-12, #50): this list used to
  claim "a dataset-style product surface 403s outright (account tier)" — WRONG
  for flow creation. The `dataset` flowtype (Dataforms) works cleanly:
  `POST /flow/2/{acct}/dataset` creates one born Live, records live on their
  own `/dataset/2/{acct}/{flow_id}` route family, no members needed, no
  publish route at all. See docs/capabilities/module.dataform.md +
  shapes/dataform_dataset_skeleton.json. The old 403 note likely described an
  analytics-shaped surface, not this flowtype.
