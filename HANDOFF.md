# Handoff — Kissflow Forge, NL→app MCP proven (2026-08-13)

Repo: `/Users/saris.kia.adm/Desktop/kissflow-forge`, trunk `develop`. Dev tenant only.
Suite: **930 passed, 26 skipped** (`uv run --with pytest --with 'fastmcp>=3' --with pyyaml --no-project pytest -q` — never drop the fastmcp dep, loses ~96 tests). Trunk deterministically green.

## What this session did (the thesis, proven)
Natural language → working Kissflow app, through the MCP tools ONLY (Cowork = Claude driving `forge_*`/`kf_*`, no build code). Two raw inputs in `~/Downloads` (`AI_Clinic_Case_flow.drawio`, `requester-pages-design.html`) became a LIVE app on dev.

- **App** `AI_Clinic_Operations_Hub_COWORK_Pr_A00` (published, ALIVE — do not delete; the boss opens it to inspect).
  - **Process** `AI_Clinic_Case_A14`: 59 fields / 9 sections, FDE Log child table, 4 roles + members + acting user in each role, 3-way "Service Level" Parallel split (Self-serve/Light-touch/Full clinic), 2 Boolean-gated rework loops (`Done`, `Canvas Done`), full visibility matrix. **doctor ok:true, published Live, two items walked and DIVERGED** (Full clinic→4c, Light-touch→4b).
  - **Pages** `Submit_AI_Use_Case_10` + `My_AI_Cases_Dashboard_9`: built via `forge_build_page`, then **copilot-polished** to mockup quality (green hero band, 3-card row, primary CTA with scroll on_click, live `view/form` embed; dashboard KPI tiles + live `view/table` + `metrics` stepmetrics). Polish verified by GRAPH READ-BACK, never copilot's reply (both `forge_copilot_ask` returned `conversation_id:null` yet the redesign landed ~70s later — the "reply lags the graph" doctrine).

## Tracker (github sariskiat/kissflow-forge) — ALL closed except #60
- `#42` map CLOSED (rollup). `#45-52` sweeps, `#28` harness, `#55` surface, `#56` intake, `#59` template — all CLOSED.
- `#57` conditional-required = shape captured; `#58` dataform page-widget = shape captured + `forge_dataset_records` update/delete/name→id added — CLOSED.
- **`#60` OPEN** — the ONE irreducibly builder-UI (Chrome) capture: conditional-STYLING wire shape + dataform-widget pixel render + `flow_id` id-form (name-slug vs `_A00`). Needs a session that can drive Chrome / read the studio network tab. This machine could not.

## What got built (cite these, don't re-derive)
- **MCP surface** (#55): 46 `forge_*` tools. `forge_create_process(from_template=True default, #59)`, `forge_apply_fields` (whole-field: validation+ErrorMessage / computed Field::Expression / conditional_visibility / default), `forge_grant_tier`, `forge_add_role_users` (the Users-write/Members-read asymmetry), `forge_create_flow`, `forge_dataset_records` (now create/list/update/delete + name→id), `forge_sweep`, `forge_capabilities`, `forge_copilot_ask`/`forge_copilot_check`, `forge_playbook`.
- **Driving skill** = the brain. Local: `~/.claude/skills/kissflow-forge-builder/SKILL.md`. VENDORED in-repo: `skills/kissflow-forge-builder/SKILL.md` (kept byte-identical). Served at runtime via the `forge_playbook` MCP tool so the brain deploys WITH the server (a remote user gets hands+brain). CLAUDE.md is the deeper manual; capability docs in `docs/capabilities/` (26+); shapes in `shapes/`.
- **Engine fixes this session** (each a commit, suite-green): create_flow ProcessDef scaffold; rich-text captured-not-refused; `forge_simulate_case` accepts field NAMES; `set_visibility` excludes table-host column; `set_visibility` resolves a section-owner name to the Section node not a same-named table host; doctor sparse-count excludes table host; dataform record CRUD; goto-equality flaky-test clock freeze (`1f09721`).

## Key gotchas learned live (now in CLAUDE.md + skill)
- `forge_apply_fields` re-layout AFTER `forge_add_table` strands the child schema row + dumps columns into "Other" → publishes+walks but the builder FORM shows "error/Reload". Order: ALL fields+FINAL layout in as few apply_fields calls as possible → table LAST → workflow → conditions → gotos → visibility → publish. No corrective re-layout after a table.
- A banner Section must NOT share its Name with its table (both "FDE Log" collided; set_visibility shadowed the banner). Distinct names.
- App-level publish (`forge_publish_app`) is separate from per-flow publish AND from the builder's **Deploy** button (Deploy = dev→UAT prod promotion — NEVER click on dev).
- Copilot: can build most things but slow + inconsistent + sometimes returns `conversation_id:null` while still landing ~70s later, and sometimes fabricates success — NEVER trust the reply, always graph-diff (`forge_copilot_check`).

## The two operating rules the user enforced (carry these)
1. **Driving the MCP must need ZERO build code.** Any python written while building = a MISSING TOOL. Turn every such workaround into a real engine tool/fix (hand engine code to a subagent). "Consult copilot" for visual/layout polish.
2. Building the ENGINE = code correct (in a subagent). Driving = tools only. Verify by graph read-back + a real item walk; a 200/publish/reply proves nothing (THE RULE).

## Env / how to drive
- MCP server config: `.mcp.json` sources `.env` (has `KF_DEV_*` + `KF_APP`). The running server reads `KF_APP` at launch — to target a different app either edit `.env` + reconnect (`/mcp` → kissflow-forge → reconnect) OR spawn a fresh stdio `python -m kfforge.server` with `env["KF_APP"]` overridden (this is how mid-session app switches + fix-reloads were done). `.env` currently points `KF_APP=AI_Clinic_Operations_Hub_COWORK_Pr_A00`.
- Prod key `~/Downloads/prodkey.json` was used READ-ONLY once (template capture, account `AcWvoSGX0Cjf`); prod = GET only, all builds dev.

## Next session
- The user is about to hand "the hardest test." Invoke `/kissflow-forge-builder` (or the MCP `forge_playbook`) and drive it MCP-only.
- Optionally close `#60` if Chrome/studio access exists.
- Eval-repo captures (out-of-repo, blindness): `~/Desktop/kissflow-forge-eval/captures/` (ai_clinic_*.md, residuals_r*.md, browser_round_findings.md).

## Suggested skills
- `kissflow-forge-builder` — THE playbook for any Kissflow build/edit via the MCP. Invoke first.
- `caveman` / `ponytail` — already auto-loaded (comms + laziness discipline).
