# Exercising every tool: `scripts/exercise_every_tool.py`

The delivery artifact that proves a deployed Kissflow Forge MCP server can run all
61 tools of `docs/specs/refactor-to-mcp-boilerplate.md` Appendix A against a real
app on the dev tenant. It is a standalone MCP client — it never imports `app.*` and
never reads a secret from the server's own process; it drives the server the way
Claude Desktop or Claude Code would, over the wire.

**Never print a real Kissflow access-key ID or secret.** Every example below uses a
placeholder. The script itself never logs the pair either — see
`build_http_headers`/`resolve_key_pair` in the script.

## 1. Build the image

```bash
docker build -t kissflow-forge-mcp .
```

This is the same `Dockerfile` the deployed server runs (see
`docs/engine/13-deploying-the-mcp-server.md` for the real deploy target). The image
defaults to HTTP mode (`MCP_HTTP=1`, port 8080); the script's `--stdio-docker` flag
overrides that back to stdio for a local run (below).

## 2. Run the container

Two ways to reach the same server, and the script supports both:

**HTTP**, for `--url` (the default transport):

```bash
docker run --rm -p 8080:8080 kissflow-forge-mcp
```

Then point the script at it — the server reads the caller's own Kissflow key pair
off two request headers on every call, never from its own environment:

```bash
uv run scripts/exercise_every_tool.py --url http://localhost:8080/mcp
```

`KF_DEV_ACCESS_KEY_ID` / `KF_DEV_ACCESS_KEY_SECRET` must be set in the shell
environment, or in a `.env` file at the repo root (`cp .env.example .env`, then
fill the two keys) — the script reads `.env` with `dotenv_values` only when the
environment variables are not already set, and never once prints either value.

**stdio**, for `--stdio-docker` (no server process to start by hand):

```bash
uv run scripts/exercise_every_tool.py --stdio-docker kissflow-forge-mcp \
  --env-file .env
```

The script itself spawns the container as a subprocess, piping MCP over stdio:

```bash
docker run -i --rm --env-file .env -e MCP_HTTP= kissflow-forge-mcp
```

`--env-file` points at a file holding `KF_DEV_DOMAIN`, `KF_DEV_ACCOUNT_ID`,
`KF_DEV_ACCESS_KEY_ID`, and `KF_DEV_ACCESS_KEY_SECRET` — stdio mode has no request
headers to read the key pair from, so the container needs it in its own
environment (`app.infrastructure.config.settings.load_settings`). `-e MCP_HTTP=`
(empty) is what selects stdio over the image's own HTTP default.

## 3. Run the script

```bash
uv run scripts/exercise_every_tool.py --url http://localhost:8080/mcp
```

Useful flags:

| Flag | Meaning |
|---|---|
| `--url <url>` | streamable-http server URL (default `http://localhost:8080/mcp`) |
| `--stdio-docker <image>` | run the server as a docker container over stdio instead |
| `--env-file <path>` | the `.env` fallback for HTTP mode, and the `--env-file` docker passes in stdio mode (default `<repo root>/.env`) |
| `--app-id <id>` | exercise against an existing application instead of creating one |
| `--keep` / `--cleanup` | leave the created application in place (default), or delete it at the end |
| `--user-query <name-or-email>` | a real Kissflow user to exercise `forge_add_role_users` with — **never** a group; see CLAUDE.md's group-notification warning |
| `--log-path <path>` | where to write the JSON log (default `exercise_log.json`) |

Without `--app-id`, the run creates its own application with
`forge_create_template_app` and builds everything else inside it — a process,
fields, a workflow with a conditional gateway and a loop-back gate, a page, a word
list, a dataset, and a simulated item walk. Every throwaway object the run made
along the way that is not part of that application (a second, empty application
made only to prove `forge_create_app`/`forge_delete_flow` work; a bare process made
only to prove `kf_create_process` works) is deleted at the end regardless of
`--keep`/`--cleanup` — only the fate of the one application the run is built around
follows that flag.

## 4. Read the log

The script prints a fixed-width table (tool, outcome, seconds, detail), then the
one-line summary:

```
58 ok, 0 error, 3 skipped of 61
```

and writes `exercise_log.json`:

```json
{
  "summary": {"ok": 58, "error": 0, "skipped": 3, "total": 61},
  "rows": [
    {
      "name": "forge_create_template_app",
      "arguments": {"name": "ExerciseTool-20260923010203-App"},
      "outcome": "ok",
      "error": null,
      "skip_reason": null,
      "duration_seconds": 4.21,
      "ids": {"app_id": "...", "template_flow_id": "..."}
    }
  ]
}
```

`arguments` is exactly what was sent over the wire for that row — it never
contains a credential (the key pair travels as transport headers or container
environment, never as a tool argument). `ids` names whatever that call produced
that a later step needed (an app id, a role id, a flow id, ...). A `"skipped"` row
always carries a `skip_reason`; an `"error"` row always carries `error`. The
process exits `1` if any row is `"error"`, `0` otherwise — a `"skipped"` row never
fails the run.

Three tools are commonly `"skipped"` on a fresh run, each for a stated reason:

- `forge_create_template_app`, when `--app-id` was given — an existing app is being
  reused, so there is nothing to bootstrap.
- `forge_add_role_users`, when `--user-query` was not given — there is no
  MCP-visible route on this 61-tool surface that discovers an existing human member
  of a role without one (`forge_list_app_roles` never returns `Members`), and this
  tool refuses to guess at a person to grant.
- `forge_share_report`, always — it needs a flow report id, and nothing on this
  surface creates or discovers one.

Any other `"skipped"` or `"error"` row is a real finding worth reading `error`/
`skip_reason` for before trusting the deploy.

## The two ways Claude Desktop can reach this same server

- **A remote connector.** Settings → Connectors → Add custom connector, pointed at
  the deployed `/mcp` URL, with the caller's own Kissflow access-key ID and secret
  pasted into the connector's **Request headers** as `X-Access-Key-Id` /
  `X-Access-Key-Secret` — the same two headers this script sends over
  `--url`. No OAuth flow: the key pair itself is the credential FastMCP reads off
  the request.
- **A local `docker run -i` stdio entry.** A command-based MCP server entry running
  `docker run -i --rm --env-file <path> -e MCP_HTTP= <image>` — the same command
  this script runs under `--stdio-docker`. The key pair and tenant settings come
  from the container's own environment (the `--env-file`), never from a header,
  because stdio has no request to attach one to.
