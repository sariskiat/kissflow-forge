# kissflow-forge — documentation guide

<!-- hygiene:begin -->

## What this is

Kissflow is a low-code platform where people build business apps by clicking
around in a builder screen. This repo lets Claude do that clicking instead. You
describe the app you want in a chat, and the engine writes the forms, workflow
steps, approval rules, tables and pages straight into a Kissflow **dev** tenant.
Before anything is built it produces a diagram and an HTML mockup for a human to
sign off on, because it writes through Kissflow's undocumented internal builder
API and a wrong guess is expensive.

Shape: a Python package plus an **MCP server** — a small program Claude connects
to in order to gain new abilities. It runs either on your own machine or as a
container behind a URL.

## How it fits together

```text
  Claude Desktop / Claude Code
        │  MCP (stdio, or HTTP + per-user OAuth)
        ▼
  ┌──────────────┐   asks       ┌──────────────┐   diagram +
  │  server.py   │ ───────────▶ │  intake/  +  │   mockup
  │ 56 forge_*   │              │  design/     │ ─────────▶ human signs off
  │ and kf_ tools│ ◀─────────── │              │
  └──────┬───────┘   BuildPlan  └──────────────┘
         │
         │ plan the change offline (no network)
         ▼
  ┌──────────────────────────────────────────┐      reads
  │ graph.py  pages.py  nav.py  expr.py      │ ◀──────────── shapes/
  │ verify.py  types.py    the node-graph    │   85 captured JSON
  └──────┬───────────────────────────────────┘   node shapes
         │ ops
         ▼
  ┌──────────────┐   HTTPS      ┌────────────────────┐
  │  client.py   │ ───────────▶ │ Kissflow dev tenant│
  │ THE WRITE    │              │ /flow + /metadata  │
  │ PATH         │ ◀─────────── │ (undocumented API) │
  └──────────────┘   read back  └────────────────────┘
```

- **server.py** — the front door. Every tool Claude can call is defined here.
- **intake/ + design/** — turn a conversation into a spec, then into a diagram
  and mockup a human approves before a single write happens.
- **graph.py and friends** — all the thinking, done offline with no network.
  Pure functions over the node-graph, which is why most of the tests are fast.
- **shapes/** — real JSON captured from the live builder. The reference for what
  a correct node looks like. Never invented from a schema.
- **client.py** — the only file that writes to Kissflow. Refuses any domain that
  does not start with `dev-`.
- **dataplane.py** — separate path that walks a real item through a built
  process, to prove the thing actually works rather than merely publishing.

## Start here

1. [CONTEXT.md](CONTEXT.md) — the words this project uses for its own ideas.
   Read this before the code, or half the names will read oddly.
2. [../CLAUDE.md](../CLAUDE.md) — the engine manual and the build order. Starts
   with THE RULE: an HTTP 200 proves nothing.
3. [engine/](engine/) — one file per part of the manual. Open the one for the
   thing you are about to touch, every time.
4. [adr/](adr/) — five decisions already made, and why. Read before reopening one.
5. [notes/SETUP.md](notes/SETUP.md) — getting it running on a new machine.

## Where everything lives

| Path | What is inside | Read it when |
| --- | --- | --- |
| `docs/CONTEXT.md` | Domain glossary | A word in the code reads oddly |
| `docs/adr/` | 5 decision records | Before reopening a settled design choice |
| `docs/agents/` | Issue tracker, triage labels, reader and domain config | A skill cannot find the tracker or its labels |
| `docs/capabilities/` | 33 field and config capability captures | You need the exact wire shape of one field type |
| `docs/engine/` | 13 manual sections, one per topic | Before touching workflow, tables, pages, visibility |
| `docs/notes/` | Setup guide plus four field-gathering notes | Installing it, or hunting a field list |
| `docs/research/` | 2 findings from primary sources | You need a fact someone already chased down |
| `docs/connect-claude-desktop.md` | End-user connector walkthrough | A non-technical person needs to connect |
| `docs/security-findings.md` | Open security findings, with owners | Before exposing the server to anyone |
| `docs/sre-mcp-curl-repro.md` | Endpoint reproduction for the platform team | The hosted endpoint misbehaves |

## Common jobs

| You want to | Do this |
| --- | --- |
| Build something in Kissflow | Read `../CLAUDE.md` build order, then `engine/` for the part you touch |
| Know the exact shape of a field | Open the matching file in `capabilities/` |
| Set the server up on a new machine | Follow `notes/SETUP.md` |
| Connect as a non-technical user | Follow `connect-claude-desktop.md` |
| Understand why a design is the way it is | Read `adr/`, newest first |
| Debug the hosted endpoint | Run `scripts/mcp-curl-probe.sh` against two URLs and diff |

## Housekeeping

Swept 2026-08-20. 70 markdown files: 6 moved, 64 left in place, 0 errors.
Shims: `CONTEXT.md` → `docs/CONTEXT.md` (older tools read the root path).

<!-- hygiene:end -->
