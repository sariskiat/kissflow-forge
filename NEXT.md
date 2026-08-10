# NEXT — fix the empty-banner render bug (matt cycle)

Handoff, 2026-08-10. Root cause is CONFIRMED on the live builder oracle — a fix, not an
investigation. (App-specific ids/captures live in the orchestrator repo's memory, kept out of this
tree by the blindness rule.)

## What broke
A rebuilt app published clean, doctor-clean, and the semantic comparator said "1 gap" — yet it
**did not render** in the builder ("There was an error / Reload", would not even open). An earlier
rebuild WITHOUT a banner section rendered fine.

## Root cause (proven — see CLAUDE.md Tables section)
An empty **banner Section** (`Column::Row:[]`, zero fields) is renderable ONLY as a caption
directly above its table — the golden reference keeps the banner row immediately followed by the
table-host row in root `Model::Row`. `graph.add_table` (~592) does
`root.setdefault("Model::Row", []).append(host_row)` — it APPENDS the host to the END. When a
banner was created for that table, appending strands the empty banner (other sections fall between
it and its table) → the whole form fails to render.

- NOT the empty `Column::Row:[]` key — removing it first did NOT fix it (tested on the oracle).
- The fix that rendered the form: reorder root `Model::Row` so the table host sits right after the
  banner. The live app is hand-patched this way; the ENGINE still emits the broken order, so a
  fresh rebuild reproduces the bug.

## The fix (TDD, red first)
1. **Red test** — `tests/test_graph.py`: build a draft with a banner Section, call `add_table(...,
   after_section=<banner name>)`, assert the host row is at `Model::Row.index(banner_row) + 1`.
   Fails today (no `after_section`; the host is appended last).
2. **Green** — `kfforge/graph.py add_table` (~524): add `after_section: str | None = None`. When
   set, find that Section's root row in `Model::Row` and INSERT the host row right after it; else
   append (backward compatible). `kfforge/server.py forge_add_table` (:392): thread the param
   through.
3. The rebuild driver (in the orchestrator repo) then passes `after_section=<banner name>`.

## Does NOT live here — the oracle + proof stay in the orchestrator repo
- The semantic comparator missed this because its section-order check EXCLUDES the table host
  (`Column{Type:"Model"}`). Separate fix, in the orchestrator repo: diff root `Model::Row` order
  INCLUDING the table host. A forge-only session cannot do this.
- End-to-end render proof = rebuild through the MCP from the orchestrator repo (its loop dir +
  golden captures + comparator all live there). Plan two hops: engine + unit test HERE, then back
  to the orchestrator repo for the render-proof.

## matt setup note
`CONTEXT.md` + `docs/` are untracked here — matt scaffolding may be incomplete. If
`/to-spec`/`/to-tickets` need the tracker/labels, run `/setup-matt-pocock-skills` once here first.

## Also owed (bigger, separate)
PAGES parity: the loop builds a PROCESS flow only (zero page calls); the comparator has no page
dimension. App dashboards/UI are entirely unmeasured. That is its own design round, not this fix.
