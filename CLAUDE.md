# RULE

remember: generalise. the eval comparison cases are just eval, not the build target!

# Kissflow Forge — Engine Manual

This file is the manual a fresh-context agent needs to build **any** Kissflow app
through this engine. It builds/edits Kissflow apps via the **undocumented**
internal `/flow` + `/metadata` builder API — not the documented public API, and
not anything published in Kissflow's own docs. Every rule below was captured
empirically, by building something in the Kissflow builder UI and reading back
what it actually wrote to the graph, never by guessing from a schema or from
what "should" be true. Treat every shape in this file as a proven capture, not
a spec: if the platform changes and a capture stops matching reality, recapture
it, don't patch around the mismatch.

The engine is dev-tenant by default (`KF_DEV_*` refuses any domain without
`dev-`; the plain `KF_*` set is the explicit no-guard opt-in for another tenant,
see `kf.env.example`) and targets one app at a time via
config — no default app, no writing to anything that isn't the one explicitly
configured domain. Before any destructive build, produce a confirmation artifact (a
diagram or an HTML mockup of the intended shape) for a human to sign off on —
building blind against an undocumented API is how sessions get lost.

Read the sections in order; they're ordered the way a real build proceeds,
from "how do I know this worked" through node shapes, workflow, gating,
tables, computed fields, visibility, membership, the write-path gotchas, the
runtime item API, and finally app pages. The closing section is the proven
build order end to end.

## THE RULE

**An HTTP 200 and a clean publish prove nothing about whether the flow actually
works.** The Kissflow builder UI is a second, stricter validation layer on top
of whatever the write API accepted. A flow can accept every write, publish
clean, report itself live, and still render to an end user as nothing but an
error screen. Do not treat a 200 response, or a publish that returns success,
as evidence of anything beyond "the API accepted the bytes."

- Never claim a build works because the API returned 200. That is not
  evidence of a working flow, only of a syntactically acceptable write.
- The only reliable oracle is a **UI-built artifact to diff against**. When you
  are unsure whether a shape is right, build the equivalent piece by hand in
  the builder (or ask a human to), then diff your generated graph against that
  UI-built reference node by node, key by key. Guessing round after round is
  reliably slower than one real diff.
- When told "it still errors," do not re-diff the part of the graph you
  already checked. Stop and go find the layer you have not checked yet: the
  flow's own config payload, its membership, per-node keys you assumed were
  optional, or the UI's own network requests while it loads the broken page.

## Commands

This is a `uv` project: `pyproject.toml` + `uv.lock` own every dependency, and
`uv run` resolves them. There is no `requirements.txt` and no `--with` flag any
more — the old per-run form silently dropped 1073 tests whenever the `--with
'fastmcp'` argument was forgotten, and a lockfile removes that failure mode
entirely. FastMCP is pinned EXACTLY (`fastmcp==4.0.2`) because the OAuth-proxy
seam in `src/app/infrastructure/kissflow/auth.py` reaches into
`fastmcp.server.auth` internals that semver does not cover.

```bash
uv sync                  # create/refresh .venv from uv.lock

make test                # unit + integration — 2284 passed, 31 skipped (verified 2026-09-17).
                         # The 31 skips are the live suites, excluded by default (conftest.py).
make lint                # ruff format --check + ruff check + import-linter + ty check .
                         # All four are GREEN and blocking, over src/ AND tests/.
make architecture        # import-linter alone — the layer rules, enforced
make verify              # lint + test, the pre-push gate (coverage gate: 90%)
make format              # ruff --fix + ruff format

# one file / one test by name
uv run pytest tests/test_pages.py
uv run pytest -k step_permissions

# live acceptance — hits the REAL Kissflow dev tenant (KF_APP) via direct in-process
# calls to app.infrastructure.mcp.server's own tool functions. Opt in, or these skip.
make test-live

make start               # the MCP server (= uv run mcp-server = python -m app.main)
```

`tests/test_engine_doc.py` is a contract test over **this file plus every
`docs/engine/*.md`**: it requires every `##` heading listed in its `HEADINGS`,
2–4 marker phrases inside each section's own text, and a corpus over 8000
chars. The manual is mandatory by test, not by accident — a section may move
between this file and `docs/engine/`, but its content must never be deleted.
The same test caps this file at 20000 chars: it reloads on every message, so
detail goes in `docs/engine/`, never here.

## Layout

Clean Architecture: dependencies point **inward**, and that is a check, not a
docstring — `make architecture` (import-linter) fails the build if an edge ever
turns around. See `code_architecture.md` for the layer rules.

```
src/app/
  main.py          # composition root: transport + port, nothing else
  resources.py     # the ONE filesystem anchor (shapes/, docs/capabilities/, skills/)
  domain/          # the node-graph model + pure ops. No HTTP, no fastmcp, no I/O clients.
    types.py       # frozen structs, closed enums — the typed core
    graph.py       # pure offline ops on the normalized node-graph
    expr.py        # Expression/Node AST for branch conditions + GotoTask gates
    pages.py       # pure offline ops on the app-PAGE graph
    nav.py         # pure offline ops on the app-level navigation graph
    coverage.py    # the coverage contract — which shapes may be built, refused by row
  application/     # use cases over the domain. May import domain, never infrastructure.
    engine.py      # offline planning; apply/publish orchestration lands here later
    tools.py       # framework-agnostic tool logic (dict in / dict out)
    verify.py      # health check: every reference that would break the form
    compare.py     # draft-vs-draft diffing
    querybank.py   # copilot probe-prompt catalog
    design/        # confirm.py (approval protocol) · diagram.py (draw.io XML) ·
                   # mockup.py (self-contained HTML for the business owner)
    intake/        # schema.py (11-dimension AppSpec) · questions.py (grilling
                   # script) · compile.py (AppSpec → ordered BuildPlan) · serde.py
  infrastructure/  # adapters onto the outside world. May import anything inward.
    kissflow/      # client.py — THE WRITE PATH (dev tenant only) · auth.py (Entra +
                   # per-user OAuth) · dataplane.py (/process API) · pages_live.py
    mcp/server.py  # the FastMCP adapter — thin: tool surface, no business rules
    capabilities.py / playbook.py   # docs + vendored-skill readers (filesystem)
shapes/            # 85 captured JSON node shapes (2026-08-20) — the proven-capture reference
tests/             # pytest suites + fixtures/ + live_helpers.py
scripts/           # mcp-curl-probe.sh — 7-check HTTP-transport probe, run per URL and diff
docs/adr/          # 5 ADRs (2026-08-19) — locked decisions, don't re-litigate
CONTEXT.md         # domain glossary
```

`shapes/`, `docs/capabilities/` and `skills/` stay at the REPO ROOT, not inside
the package: `docs/capabilities/*.md` cross-references its captures as
repo-relative `shapes/...` strings. Everything resolves them through
`src/app/resources.py` — one anchor, not four modules each climbing `..` on
their own.

Trunk is `develop`. `CONTEXT.md` and `docs/` are **tracked**, ADRs included
(verified 2026-08-19) — a clone carries the whole manual, not just this file.

## Engine manual — section index

The detail lives one file per section under `docs/engine/`. **Read the file for
the section you are about to touch — do not build from memory of it.** Every
shape in them is a proven capture off the live builder, not a spec.
Code comments that say `CLAUDE.md > <Section>` mean the row below.

| Section | File |
|---|---|
| `Node-graph invariants` | `docs/engine/01-node-graph-invariants.md` |
| `Workflow` | `docs/engine/02-workflow.md` |
| `Expressions` | `docs/engine/03-expressions.md` |
| `Gate polarity` | `docs/engine/04-gate-polarity.md` |
| `Conditional routing` | `docs/engine/05-conditional-routing.md` |
| `Tables` | `docs/engine/06-tables.md` |
| `Field events` | `docs/engine/07-field-events.md` |
| `Visibility` | `docs/engine/08-visibility.md` |
| `Members first` | `docs/engine/09-members-first.md` |
| `Write path` | `docs/engine/10-write-path.md` |
| `Item data plane` | `docs/engine/11-item-data-plane.md` |
| `Pages` | `docs/engine/12-pages.md` |
| `Deploying the MCP server` | `docs/engine/13-deploying-the-mcp-server.md` |

`tests/test_engine_doc.py` is a contract test over CLAUDE.md **plus** every
`docs/engine/*.md`: mandatory headings, marker phrases inside their own
section, total size, and no leaked identity tokens. Splitting a section out is
fine; deleting its content is not.

## Build order

The proven end-to-end sequence, most foundational first:

1. **Create the flow** (process, form, or list as needed). **A process now
   seeds the identity shell by default (issue #59)**: `create_process` /
   `create_flow_any(kind="process")` clone the process-template identity/
   initiate shell (`shapes/process_template_identity_shell.json`,
   `from_template=True` by default) instead of the bare single-step scaffold
   — the identity/initiate field block, layout, mandatory style chain, and a
   "Manager Approve" step arrive pre-built; callers add their own
   fields/workflow on top. Pass `from_template=False` for the old bare
   scaffold. See docs/capabilities/process-template.md.
2. **Members** — before anything else gets built on top, or every later
   publish involving assignees fails (see Members first).
3. **Fields and sections** — the node-graph invariants apply from the first
   field onward (see Node-graph invariants).
4. **Tables**, if any — as their own nested Model, in their own root Row,
   never nested in a Section (see Tables).
5. **Workflow** — ProcessDef, Activities, any GotoTask loops (see Workflow). A
   `Parallel` gateway built here is UNCONDITIONAL — every branch always runs
   — until step 7's branch conditions attach (see Conditional routing).
6. **Assignees** — only once members exist (see Members first).
7. **Goto gates and branch conditions** — the loop conditions on any backward
   edges, gated on a Boolean, fail-closed (see Expressions, Gate polarity); a
   `Parallel`'s branches, made conditional on a deciding field's real values,
   never guessed (see Conditional routing). A per-branch goto gate is placed
   with `add_goto_task`'s `branch_process_def_id` / `forge_add_goto_gate`'s
   `branch_name`, last within its own branch, never cross-branch.
8. **Visibility matrix** — section-level where a whole section shares a rule,
   field-level otherwise; re-run this step after any later workflow rebuild,
   since a rebuild silently deletes every Permission (see Visibility).
9. **Events** — computed fields, wired onto their source fields (see Field
   events).
10. **Styles** — token refs only on form sections; pages take raw CSS strings
    for every dimensional value and either raw hex or a token ref for color
    (see Node-graph invariants, Pages).
11. **Publish.**
12. **Verify** — a read-only health check of the live flow, run after every
    single builder edit, not just at the end.
13. **Simulate items** — walk a real item through create → fill → submit →
    every gate → completion, using the runtime item API (see Item data
    plane), to prove the thing actually works end to end, not just that it
    published.

The standing discipline behind every one of those steps, and every future
script that touches this API: **snapshot → dry-run → apply → read-back verify
→ publish → audit.** Snapshot the draft first (see Write path). Dry-run the
change and inspect the diff before sending it. Apply. Read back what actually
landed, not what you asked to land. Publish. Audit.

**Every batch operation ends with an output-invariant audit**: added /
skipped / verified / missing — every single record you touched must land in
one of those counted buckets. A record that's just silently absent from all
four buckets is the bug, every time; never report a batch as successful while
anything is unaccounted for.

When probing for a route that might not exist: search whatever API reference
material you have first, then sweep suffix, prefix, an `admin/` variant, and
header variations before concluding it's not there. **403/500 = the route
exists, keep digging. Only 404 means wrong door.** A response that looks like
a hard failure is very often evidence you're close, not evidence you're
blocked.

Finally: treat any inherited inventory or manifest document — including this
one — as desired state, not proven state. A note that says a piece "exists"
or "is done" is a claim to verify by a live read, not a fact to build on
directly. Absence of some behavior in one captured sample is likewise not
proof of its absence from the API generally — a single sample that never
exercised a feature looks identical to a sample proving the feature doesn't
exist. When a belief here gets corrected by a live capture, replace it
outright and say so, rather than leaving the old belief to mislead the next
read.

## Agent skills

### Builder playbook

The fresh-context builder brain (THE RULE, the numbered build order, the intent→tool map, the
refuse-loudly table, the copilot fallback) is vendored at `skills/kissflow-forge-builder/SKILL.md`
so it version-controls with the codebase and ships with the MCP — `~/.claude/skills` is local-dev
only and does NOT deploy. It is served over the wire by the `forge_playbook` tool
(`src/app/infrastructure/playbook.py`), so a remote user's Claude fetches the doctrine at runtime with no local
file; deep wire shapes it references live in `forge_capabilities(<id>)`.

### Issue tracker

GitLab Issues via the `glab` CLI, inferred from this repo's `origin` remote
(`cjexpress/tildi/infra/ai-coe/kissflow-forge` on `gitlab.cjexpress.io`). Blocking edges use
GitLab's native linked issues (`--link-type is_blocked_by`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default 5 canonical roles, label string equals role name. See
`docs/agents/triage-labels.md`.

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at repo root, already in place.
See `docs/agents/domain.md`.

### Reader skill

Turn the two input files (a `.drawio` flow capture + an HTML page design) into
spec JSON, consumed via the existing `forge_update_spec` → `forge_approve_spec`
→ `forge_plan_app` surface — the engine never parses `.drawio` (D5). Ask on any
blocking gap, never enrich a guess; validate every routing literal against the
LIVE word list; refuse any `app.domain.coverage` shape marked `refuses-loudly`,
naming the row. Token discipline: never open the XML whole, analyze with
`python3`. See `docs/agents/reader.md`; its output boundary is proven by
`tests/test_reader_boundary.py`.
