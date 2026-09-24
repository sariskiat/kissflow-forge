---
name: kissflow-forge-developer
description: Develop the kissflow-forge MCP server itself — change engine code, add or change a forge_* tool, capture a new Kissflow wire shape, fix a failing test, or edit the served skills and the engine manual. Use when the work is on this repository's code, tests, shapes or docs. Not for building a Kissflow app with the tools (use the builder playbook for that).
---

# Kissflow Forge — developing the engine

You change the engine, not a Kissflow app. The engine writes an undocumented builder
graph, so every shape it writes must come from a live capture, never from a guess.
Read `CLAUDE.md` (the engine manual index) and `code_architecture.md` before a first change.

## When an engine feature is done

All four hold, in this order:

1. A test in `tests/` fails before the change and passes after it.
2. `forge_doctor` on a live dev flow reports no broken reference.
3. `forge_simulate_case` walks a real item through the feature, and the item lands where the
   feature says it should. For a split, two items with different values land on different steps.
4. The wire shape is saved as `shapes/<name>.json` and `docs/capabilities/<name>.md`
   (copy `docs/capabilities/TEMPLATE.md`; status `captured` until an item walked it live, then
   `proven-live`; `tests/test_capability_docs.py` checks the front matter).

A 200 or a clean publish is not on this list. A skipped live suite is not a pass.
Steps 2 and 3 need a live tenant; when you cannot run them, say so in the report.

## Layers

Dependencies point inward: `infrastructure → application → domain`. `make architecture`
(import-linter, contracts in `pyproject.toml`) fails the build if an edge turns around.

- `src/app/domain/` — the graph model and pure operations. Stdlib only. Closed vocabularies
  (`Literal` aliases) live in `domain/value_objects/kinds.py`.
- `src/app/application/` — one use case per tool, request/response models (pydantic, frozen,
  `extra="forbid"`), and ports in `interfaces/`. Never imports infrastructure, httpx or fastmcp.
- `src/app/infrastructure/` — Kissflow HTTP adapters, the MCP tools (thin: build request →
  use case → response via `_shared.run_use_case`), settings, filesystem readers.
- `src/app/resources.py` is the one filesystem anchor for `shapes/`, `docs/capabilities/`
  and `skills/`, which stay at the repo root.

For the full file chain of a new or changed tool, read
[references/add-a-tool.md](references/add-a-tool.md).

## Commands

```bash
uv sync                 # from uv.lock; never pip
make test               # offline tests; live suites skip
make lint               # ruff format --check, ruff check, import-linter, ty — all blocking
make verify             # lint + tests with coverage >= 90%
make test-live          # hits the real dev tenant; needs .env and KF_APP
make format             # ruff --fix + format
uv run pytest -k <name> # one test
```

The local stop hooks may be off. Run `make verify` yourself before you report a change done,
and report the pass and skip counts.

## Capturing a shape the engine does not have yet

When a tool refuses, or the graph it writes differs from what the builder UI writes, get the
real shape from a human's browser and diff it. Read [references/capture.md](references/capture.md)
for the request to send the human and how to handle the capture safely.

## Rules that tests enforce

- No tenant names, real ids, keys or cookies in any tracked text file.
  `tests/test_p0_scaffold.py` sweeps `.py/.json/.md/.toml/...` for identity tokens.
- `CLAUDE.md` stays under 20000 chars and keeps the headings and marker phrases that
  `tests/test_engine_doc.py` requires. Detail goes in `docs/engine/*.md`. Move a section; never
  delete its content.
- The MCP surface is frozen in `tests/fixtures/tool_surface.json`. Change it only on purpose,
  and read the diff after `uv run python tests/test_tool_surface_snapshot.py --write`.
- A tool description that says "X is refused" needs a triggerable refusal in
  `tests/test_tool_claims.py`.
- The served skills (`skills/kissflow-forge-builder`, `skills/kissflow-help-design`,
  `skills/kissflow-forge-mcp`) reach remote users through `forge_playbook(skill=...)`
  (`src/app/infrastructure/playbook.py`, `PLAYBOOKS`). `tests/test_skill_tool_refs.py` fails if
  one names a tool that is not on the surface. When you rename or remove a tool, or change a
  behavior a skill describes, update the skill in the same change.

## Live tenant safety

- The server refuses any domain without `dev-` (`load_settings()` in
  `src/app/infrastructure/config/settings.py`). Keep that guard.
- Never grant a group to a role or app membership in a test. Kissflow notifies every member
  and there is no removal route. Use one named developer.
- A human may have edited a draft in the builder. Read it again and snapshot it before a write
  to a flow you did not create in this session.

## Git and review

- Trunk is `develop`. Work on a branch. Issues and merge requests are on GitLab via `glab`
  (`docs/agents/issue-tracker.md`).
- Commit, push and merge each need the user's explicit approval.
- No agent trailers, session ids or generated-by footers in commits or merge requests.
- A change carries: the red-then-green test, the shape and capability doc if new, and the
  doctor and simulate results as text, or a clear note that they were not run.
