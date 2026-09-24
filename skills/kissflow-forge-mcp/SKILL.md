---
name: kissflow-forge-mcp
description: How to drive the kissflow-forge MCP (the forge_* / kf_* tools) safely and efficiently in any session. Use at the start of every session that has these tools, and when a result looks wrong, a call is refused, or the MCP will not connect. Covers session start, which skill to load for the task, evidence rules, reading results, token use, and reporting. It does not hold the build order (forge_playbook) or the design interview (forge_playbook(skill="design")).
---

# Kissflow Forge — using the MCP

The kissflow-forge MCP writes real Kissflow apps on a DEV tenant through an undocumented
builder API. This skill is how to drive the tools. Two other skills hold the task content:

| The user wants to… | Load |
|---|---|
| work out WHAT to build ("I have a messy process", "help me design X") | `forge_playbook(skill="design")` |
| build, change, wire, or fix something in Kissflow | `forge_playbook()` (the builder playbook) |
| know how to use these tools, or a call behaves oddly | this skill |

If a local copy of a skill is loaded, use it. Otherwise fetch it with `forge_playbook`. The
server version is the one that matches the tools you have.

## Session start

1. Fetch the playbook you need (table above). Do not build from memory of an older session.
2. Find the target app. `forge_list_apps` lists apps. `app_id` defaults to the server's
   configured app; pass it explicitly when the user named one. Work on ONE app at a time.
3. `forge_sweep(scope=..., app_id=...)` before you design or change anything. It reads what
   already exists and ends in a read / error / skipped audit. Always scope it to the app: an
   unscoped list can show another app's flows.
4. `forge_capabilities("")` once for the index of captured shapes. After that, query one id or
   word at a time (`forge_capabilities("field.lookup")`). An empty result means "not proven",
   not "yes".

The server works only on a dev tenant. Every Kissflow call uses the caller's own key pair.
When no key reaches the server, live tools refuse with "no Kissflow key pair on this call".
The offline tools still work: playbook, capabilities, intake, and render.

## Evidence: what counts as "it works"

- An HTTP 200, a clean publish, and a confident copilot reply prove NOTHING. The builder UI
  checks more strictly than the write API does.
- After every edit, run `forge_doctor(flow_id=...)`. `ok: true` with `problems: []` is clean.
- Read back what landed, not what you asked to land. The write tools report counted buckets.
  Every record you sent must be in one of them. A record that is in no bucket is the bug.
- The end proof is `forge_simulate_case`: a real item walked from create to completion. A
  split is proven only when two items with different deciding values land on different steps.
- Write tools default to `publish=false`. Batch the draft edits, run doctor, then publish once
  with `forge_publish`. An app also needs `forge_publish_app`.

## Safety: actions you cannot take back

- **Never grant a group** to a role or to app membership to test anything. Kissflow notifies
  every member, and membership writes are add-only. Grant one named person
  (`forge_add_role_users(user_query="<name>")`). Set `confirm_group_notification=True` only
  after a human confirms the real recipient list.
- **A human may have edited the draft in the builder.** Before you write to a flow you did not
  create in this session, read it again. Compare it with what you expect, and tell the user
  about any difference before you write over it.
- **Before a destructive build**, show a picture and get a yes: `forge_render_flow_diagram`,
  `forge_render_schema_diagram`, `forge_render_mockups`, or `forge_request_confirmation`.
- `forge_delete_flow` cannot be undone. Delete only what the user named or confirmed.
- The builder's **Deploy** button moves an app to UAT or prod. Never use it from a dev build.

## Reading results

| You see | It means | Do |
|---|---|---|
| `isError: true` or a refusal naming a reason | the engine refused a shape it cannot build correctly | tell the user the reason; do not send the same call again unchanged |
| `changed_ignored` (apply_fields) | the field already exists; nothing changed | use `forge_rename_fields`, `forge_set_required`, or delete + re-add |
| `uncovered` (branch conditions) | an option value matches no branch; items with it skip the split | claim every real option |
| `uncovered_sections` (visibility) | a section is editable at no step | add it to `owners` |
| `missing` | a record that did not land | fix it before you report success |
| `unverified` (events) | the write landed but the trigger pair is not proven live | say so in the report |
| doctor `problems` | a broken reference in the live draft | fix before you publish |

Live API errors: a 403 or 500 means the route exists and the request is wrong. Only a 404
means the wrong route. When the user says "it still errors", do not check the same part again.
Check the layer you have not checked: config, membership, per-node keys.

## Tokens

- Query `forge_capabilities` for one id at a time. Do not ask for the full body of every doc.
- `forge_set_visibility` returns counts and rollups by default. Pass `include_pairs=true` only
  when you need the raw pairs.
- Do not paste whole flow schemas into the chat. Quote the nodes that matter.

## Copilot

`forge_copilot_ask` drives Kissflow's own builder assistant. It is slow and inconsistent, and
its reply can claim changes that did not happen. Use it only as a fallback. Always check with
`forge_copilot_check` and a read-back across the whole app, and clean up objects it scattered.

## When the MCP does not connect

Say that the server failed to connect, and give the error text. Do not conclude that a tool
does not exist or that the user has no access. Ask the user to reconnect or check the URL
and key.

## Reporting to the user

End each piece of work with: what changed (flow, step, field names), the check that proved
it (doctor, read-back, simulate), and what was not tested. Use plain words. Do not report
success on a 200.
