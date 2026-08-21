# kissflow-forge — documentation guide

<!-- hygiene:begin -->

## What this is

Kissflow is a low-code platform where people build business apps by clicking
around in a builder screen. This repo lets Claude do that clicking instead. You
describe the app you want in a chat, and the engine writes the forms, workflow
steps, approval rules, tables and pages straight into a Kissflow **dev** tenant.
It can also clone an existing template process wholesale in one call
(`forge_create_template_app`). Before anything is built it produces a diagram
and an HTML mockup for a human to sign off on, because it writes through
Kissflow's undocumented internal builder API and a wrong guess is expensive.

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
  │ 61 forge_*   │              │  design/     │ ─────────▶ human signs off
  │ and kf_ tools│ ◀─────────── │              │
  └──────┬───────┘   BuildPlan  └──────────────┘
         │
         │ plan the change offline (no network)
         ▼
  ┌──────────────────────────────────────────┐      reads
  │ graph.py  pages.py  nav.py  expr.py      │ ◀──────────── shapes/
  │ verify.py  types.py    the node-graph    │   85 captured JSON
  └──────┬───────────────────────────────────┘   node shapes
         │   (transplant_template clones a whole captured process)
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

## Who is allowed in (the auth gate)

The server runs in one of two modes, and the mode decides who acts as whom:

```text
  stdio (local)                         HTTP (hosted / shared)
  ─────────────                         ──────────────────────
  Claude ── pipe ──▶ server            Claude ─ https ─▶ [ network edge ] ─▶ server
       one shared KF_DEV_* key              each user pastes THEIR OWN
       from the .env / --env-file           Kissflow access-key pair into the
       (every caller is that key)           connector's OAuth fields; the
                                            server runs each call as that user
```

- **stdio** (`kfforge/server.py`, no `MCP_HTTP`): the tools run under the single
  `KF_DEV_*` credential in the environment. Fine for one operator on their own
  machine; everyone shares one identity.
- **HTTP + per-user OAuth** (`kfforge/auth.py`): set `MCP_OAUTH_BASE_URL` and a
  32-char `MCP_OAUTH_SIGNING_KEY`, and each connector carries the caller's own
  Kissflow **Access Key ID / Secret** in its OAuth Client ID / Secret fields.
  The server validates the pair once against Kissflow, then runs every call as
  that person — nobody shares a key, and Kissflow's own roles bound each caller.
  Tokens are stateless, Fernet-sealed, and never stored. Leaving
  `MCP_OAUTH_BASE_URL` unset serves the endpoint **unauthenticated** (it logs a
  loud warning) — only safe behind a network edge.
- **Always on:** `client.py` refuses any domain without `dev-` in it, in either
  mode, before any read or write. There is no way to point the engine at prod.
- **One caveat worth knowing:** the `/token` endpoint validates a pasted key
  pair by hitting Kissflow, so it is a credential-testing oracle. In the hosted
  deployment the **Azure Entra / oauth2-proxy + Istio mesh edge is the shield**
  in front of it — there is no in-code rate limiter by design. See
  `engine/13-deploying-the-mcp-server.md` and `security-findings.md`.

## The SRE / hosted view

The same image runs unchanged behind the platform team's mesh:

```text
  user ─ https ─▶ dev-kissflow-mcp.cjexpress.info
                   │  Istio/Envoy mesh + Azure Entra oauth2-proxy (the edge)
                   ▼
                 kfforge container (amd64)  ── HTTPS ──▶ Kissflow dev tenant
```

- Built locally (`docker build --platform linux/amd64`) and pushed to
  `asia-southeast1-docker.pkg.dev/sre-platform-dev/ai/dev-kissflow-mcp:latest`
  with a human's `artifactregistry.writer` account, then the mesh rolls.
- Wire contract, the `FORWARDED_ALLOW_IPS` proxy trap, and the ngrok A/B rig
  are all in `engine/13-deploying-the-mcp-server.md`.
- To reproduce an endpoint problem, run `scripts/mcp-curl-probe.sh` against the
  mesh URL and an ngrok tunnel of the same image, and diff — that isolates a
  mesh/edge fault from a server fault. Full walkthrough in
  `sre-mcp-curl-repro.md`.

## Start here

1. [CONTEXT.md](CONTEXT.md) — the words this project uses for its own ideas.
   Read this before the code, or half the names will read oddly.
2. [../CLAUDE.md](../CLAUDE.md) — the engine manual and the build order. Starts
   with THE RULE: an HTTP 200 proves nothing.
3. [engine/](engine/) — one file per part of the manual. Open the one for the
   thing you are about to touch, every time.
4. [adr/](adr/) — six decisions already made, and why. Read before reopening one.
5. [notes/SETUP.md](notes/SETUP.md) — getting it running on a new machine.
6. [demo-user-setup.md](demo-user-setup.md) — the handout for demo users
   connecting the Claude Code tab to the shared server (with a VPN preflight).

## Where everything lives

| Path | What is inside | Read it when |
| --- | --- | --- |
| `docs/CONTEXT.md` | Domain glossary | A word in the code reads oddly |
| `docs/adr/` | 6 decision records | Before reopening a settled design choice |
| `docs/agents/` | Issue tracker, triage labels, reader and domain config | A skill cannot find the tracker or its labels |
| `docs/capabilities/` | 32 field and config capability captures | You need the exact wire shape of one field type |
| `docs/engine/` | 13 manual sections, one per topic | Before touching workflow, tables, pages, visibility |
| `docs/notes/` | Setup guide plus four field-gathering notes | Installing it, or hunting a field list |
| `docs/research/` | 2 findings from primary sources | You need a fact someone already chased down |
| `docs/connect-claude-desktop.md` | End-user connector walkthrough | A non-technical person needs to connect |
| `docs/demo-user-setup.md` | Demo handout for the Claude Code tab, with VPN preflight | Onboarding demo users to the shared server |
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
| Clone the template process into a fresh app | Call `forge_create_template_app(name)` — see `adr/0006` and `CONTEXT.md` "Template cloning" |
| Understand who acts as whom | Read "Who is allowed in (the auth gate)" above |
| Deploy or debug the hosted server | Read "The SRE / hosted view" above, then `engine/13` |
| Debug the hosted endpoint | Run `scripts/mcp-curl-probe.sh` against two URLs and diff |

## Housekeeping

Swept 2026-08-22. 74 markdown files: 0 moved, 74 left in place, 0 errors.
Shims: `CONTEXT.md` → `docs/CONTEXT.md` (older tools read the root path).

<!-- hygiene:end -->
