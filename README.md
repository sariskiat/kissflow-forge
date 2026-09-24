# Kissflow Forge

Kissflow Forge serves 61 MCP tools for building apps, flows, pages, and items on a
Kissflow **dev tenant**. It can show a diagram or page mockup before a build. A
successful API response does not prove a flow works; use the live checks and the
builder UI to verify it.

## Start locally

1. Run `uv sync`.
2. Copy `.env.example` to `.env`. Set `KF_DEV_DOMAIN` and
   `KF_DEV_ACCOUNT_ID`. Set `KF_APP` to select one app by default.
3. For local stdio calls, set `KF_DEV_ACCESS_KEY_ID` and
   `KF_DEV_ACCESS_KEY_SECRET` in `.env`.
4. Run `make start`.

`MCP_HTTP=1` serves `/mcp` on `PORT` (8080 by default). In HTTP mode each tool
call needs `X-Access-Key-Id` and `X-Access-Key-Secret` headers. The server does
not use the process key pair for HTTP calls. An Entra gateway, if used, sits in
front of this server and must forward those headers without logging them.

## Checks

```bash
make verify         # lint, types, architecture, offline tests, 90% coverage
make test-coverage  # offline tests with coverage
make test-live      # writes to the real dev tenant; needs local credentials
```

Live tests stay out of CI. They create and clean up sample app data. A skipped
live suite does not prove tenant behavior.

See [the architecture](code_architecture.md), [Claude Desktop setup](docs/connect-claude-desktop.md),
and [the engine manual](CLAUDE.md). The approved refactor and its remaining
release checks are in [the spec](docs/specs/refactor-to-mcp-boilerplate.md).
