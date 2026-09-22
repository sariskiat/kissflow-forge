# developer guide — for the Claude that works in a colleague's branch

**Audience: you, Claude (Claude Code or Desktop), running on a colleague's machine
with a clone of this repo.** Your human tells you a Kissflow feature they want. You
build it with the `forge_*` / `kf_*` tools, and when the engine cannot build it,
you get the missing wire shape from the human's own browser and add it to the
engine. The repo you clone is our GitHub copy; you open a pull request back to it
and we review every one. Nothing you do can break our trunk.

Read `skills/kissflow-forge-builder/SKILL.md` first (or call `forge_playbook`).
This file adds only what a branch-and-send-back contributor needs on top of it.

## Truth condition

A feature is done when ALL of these hold, in this order:

1. A test in `tests/` is red before your change and green after it.
2. `forge_doctor` on the live flow reports no broken reference.
3. `forge_simulate_case` walks a real item through the feature and the item lands
 where the feature says it should.
4. The wire shape is saved as `shapes/<name>.json` + `docs/capabilities/<name>.md`.

"The API returned 200" and "publish succeeded" are not on this list. THE RULE in
`CLAUDE.md`: they prove only that the bytes were accepted.

## Setup (once)

```bash
git clone <our github url> kissflow-forge && cd kissflow-forge
cp kf.env.example .env        # fill it, see below; never commit it
uv --version || curl -LsSf https://astral.sh/uv/install.sh | sh
uv run pytest -q   # must be green before you touch anything
claude mcp add kissflow-forge -- sh -lc "cd '$(pwd)' && set -a; . ./.env; set +a; exec uv run mcp-server"
```

Ask the human for the five secrets over a private channel. Explain one step in one
plain sentence; never make them run commands.

### `.env`: which tenant

Same `/flow` and `/metadata` endpoints on every tenant. Only the domain and the
credentials change.


| Target                             | Fill                                                                                                                  | Guard                      |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------- |
| dev tenant                         | `KF_DEV_DOMAIN`, `KF_DEV_ACCOUNT_ID`, `KF_DEV_ACCESS_KEY_ID`, `KF_DEV_ACCESS_KEY_SECRET`, `KF_APP`                    | domain must contain `dev-` |
| any other tenant (prod playground) | leave every `KF_DEV_*` empty; fill `KF_DOMAIN`, `KF_ACCOUNT_ID`, `KF_ACCESS_KEY_ID`, `KF_ACCESS_KEY_SECRET`, `KF_APP` | none                       |


If your checkout predates the `KF_*` set (`grep -n _tenant_env src/app/infrastructure/kissflow/client.py`
finds nothing), the engine refuses every non-dev domain at
`KfConfig.from_env` / `from_user` in `src/app/infrastructure/kissflow/client.py` and `_validate_pair` in
`src/app/infrastructure/kissflow/auth.py`. Pull `develop` first; only if you cannot, make the same change
yourself: read `KF_DEV_*` when `KF_DEV_DOMAIN` is set (keep the `dev-` refusal),
else read `KF_*` with no refusal, and keep the exact error string
`missing env var KF_DEV_DOMAIN` when neither is set (`tests/test_mcp_boundary.py`
asserts it).

The Kissflow key the human gives you bounds what you can touch. Even so: snapshot
the draft before any write to a flow you did not create this session
(`docs/engine/10-write-path.md`), and never add `everyone` or any broad group to a
role. That write has no undo (`skills/kissflow-forge-builder/SKILL.md`, refuse table).

## Plan before build

Write the plan as lines of `step → verify: <check>` and show it to the human before
the first write. Cheap moves first:

1. State the truth condition for THIS feature as a testable rule ("an item whose
 `Amount` &gt; 1000 lands on step Manager, otherwise on step Done").
2. Check what already exists: `forge_capabilities("<field or config name>")`,
 `ls shapes/ docs/capabilities/`. Many "cannot build" cases are a tool not using a
 shape that is already captured.
3. Pick the one seam you will change. One feature, one branch, one seam.
4. Design the check before the code: which test file, which `forge_simulate_case`
 walk, which two items must diverge.

Skip the plan only for a one-field change the tools already cover.

## Build loop: TDD on the engine, capture from the browser

```text
 human names feature
        │
        ▼
 try forge_* tools ──► forge_doctor ──► forge_simulate_case ──► green? ── done
        │ tool refuses / graph wrong / item lands wrong
        ▼
 write the RED test (what the graph must contain)
        │
        ▼
 human builds ONE piece in the builder UI, DevTools Network open
        │
        ▼
 human pastes PUT/POST payload + response (secrets stripped)
        │
        ▼
 diff UI graph vs engine graph, node by node, key by key
        │
        ▼
 smallest engine change that makes the test green
        │
        ▼
 rebuild on a fresh flow with forge_* only ──► doctor ──► simulate ──► save shape
```

### Red first

Before touching `src/app/`, add one test that fails now and passes when the engine
writes the right shape. The pattern already in `tests/test_client.py`: build the
change against `FakeClient`, then assert on the nodes in `c.draft`. A real one to
copy, `test_delete_fields_deletes_a_user_field_cluster_rather_than_refusing_it`
(`tests/test_client.py:2441`):

```python
c = FakeClient(_form_with(FieldSpec(name="Owner", type=FieldType.USER)))
rep = delete_fields(c, "F1", ("Owner",), kind="form")
assert not [
    v for v in c.draft.values() if isinstance(v, dict) and v.get("Kind") == "QueryDefinition"
]
```

For a new shape you invert it: apply the field, then assert the node the capture
showed IS present with the keys the capture showed. A `FieldType` value that does
not exist yet (`src/app/domain/types.py`) is part of the change; add it in the same
commit. The test encodes the capture; it must not encode a guess.

### Capture request (what to ask the human for)

Ask for exactly this, one piece at a time:

1. Open the builder for the flow in Chrome, press `F12`, tab **Network**, tick
 **Preserve log**, filter `flow`, press Clear.
2. Do one thing (add one lookup field, set one assignee, set one computed formula),
 press save.
3. For every `PUT` / `POST` / `PATCH` row: Headers → Request URL + Method; Payload
 → view source; Response. Or right-click → Copy → Copy as cURL.
4. Delete the `Cookie` and `Authorization` header lines before pasting.

If they send a HAR, read it with `python3`, never open it whole in context; drop
every header named `cookie`, `authorization`, `x-access-key`, `x-access-secret`
before you quote any of it. Never write the raw HAR, the cURL, or any real tenant
name into the repo (`tests/test_p0_scaffold.py` sweeps every `.md` for identity
tokens and fails the suite).

### Diff, then change

- Read the engine's own graph back with `kf_get_flow_schema` or a raw
`GET` of the draft. Diff against the UI payload node by node, key by key.
- Do not re-diff a part you already checked. When it still errors, move to the
layer you have not looked at: the flow's config payload, membership, a key you
assumed optional, the requests the UI fires while loading the broken page.
- Change the smallest thing in `src/app/` that makes the red test green. Types on
every signature, frozen dataclasses, no bare `except`, explicit error returns.
- Rebuild the feature on a fresh flow using only `forge_*`. Read back. Doctor.
Simulate with two items that must land on different steps.

### Save the shape

- `shapes/<name>.json`: the captured node(s), real ids replaced by synthetic ones.
- `docs/capabilities/<name>.md`: copy `docs/capabilities/TEMPLATE.md`, status
`captured` until a real item walked through it on a live tenant, then
`proven-live`. `tests/test_capability_docs.py` validates the front matter.

## The three pieces a cloned app usually lacks


| Piece    | Where the human clicks                                | Node(s) to expect in the payload                                                                     | Already in the repo                                                                                               |
| -------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| assignee | Workflow → step → Assignee → save                     | the step's `Activity` node gains an assignee key; the user must already be a member or publish fails | `docs/engine/02-workflow.md`, `docs/engine/09-members-first.md`, `forge_member_batch`, `forge_build_workflow`     |
| computed | Field → Computed → formula → save                     | `Event` + `Field::Event` on the SOURCE field, expression node for the formula                        | `docs/engine/07-field-events.md`, `docs/capabilities/config.computed.md`, `shapes/field_computed_expression.json` |
| lookup   | Field palette → Lookup → source flow + columns → save | `Field{Type:"Reference"}` + `Field::QueryDefinition{FlowType:"Process", LHSModel:<flow id>}`         | `docs/capabilities/field.lookup.md`, `shapes/field_lookup.json`                                                   |


Build order matters: members before assignees, the source flow before a lookup,
the source field before its computed target (`CLAUDE.md` &gt; Build order).

## Gates before you hand back

```bash
uv run pytest -q    # 2253 passed, 31 skipped on develop 2026-08-26
ruff check . && ruff format .
mypy src/app/<files you touched>
```

Every batch you ran against the tenant ends with counted buckets: added / skipped /
verified / missing. A record in no bucket is the bug.

## Send back

```bash
git checkout develop && git pull
git checkout -b feat/<feature>
# ... work ...
git push -u origin feat/<feature>
gh pr create --base develop --fill      # or open the PR in the GitHub web UI
```

We review every PR. The branch carries: one-sentence what; the shape + capability
doc; the doctor and simulate results as text in the PR body; at least one test that
is red if the new code breaks. Never the `.env`, a HAR, a raw cURL, or a real
tenant name.

Commit messages: plain Conventional Commits, no AI footer of any kind.

## Open questions you must not guess on

- The exact assignee key name on `Activity` for this tenant: capture it, do not
copy it from memory.
- Whether a shape captured on dev renders identically on the prod playground:
`captured` status until an item walks through it there.
- Anything the refuse table in the builder skill marks as having no proven live
shape: say so to the human and stop, do not build around it.

