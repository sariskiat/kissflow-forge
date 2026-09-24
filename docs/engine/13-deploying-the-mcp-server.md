## Deploying the MCP server

The process starts in `src/app/main.py`. It loads settings, opens one shared
`httpx.AsyncClient` in the lifespan, then registers 61 tools through
`create_server()`. `MCP_HTTP=1` serves streamable HTTP on `0.0.0.0:$PORT` at
`/mcp`; with `MCP_HTTP` empty it serves stdio. The image entry point is
`mcp-server`.

The process refuses a missing `KF_DEV_DOMAIN` or `KF_DEV_ACCOUNT_ID`. The
hostname must be a bare dev-tenant host. `KF_APP` selects one app by default;
without it an app-scoped call must supply `app_id`. `KF_PROCESS_TEMPLATE` is an
operator setting. `HTTP_TIMEOUT_SECONDS` controls outbound request timeouts.

### Keys and gateway

In stdio mode, the process reads `KF_DEV_ACCESS_KEY_ID` and
`KF_DEV_ACCESS_KEY_SECRET` from its environment. In HTTP mode, each tool call
needs `X-Access-Key-Id` and `X-Access-Key-Secret` request headers. The server
never falls back to its environment pair for an HTTP caller. A missing pair
fails before a Kissflow call. `AppResources` holds no key pair; adapters get
it for each request.

The server no longer runs an Entra OAuth provider. SRE's Entra gateway, when
deployed, must sign in the person, pass both key headers unchanged, and not
log them. The repo does not know that person's identity. The gateway's log
must link person to request; Kissflow sees the central key ID. The HTTP server
should not be reachable around that gateway. The current gateway setup and
public endpoint have not been checked in this refactor.

Before any HTTP deployment, resolve the two open path controls in
`docs/specs/refactor-to-mcp-boilerplate.md` section 14: the caller-chosen
`out_dir` for design files and `forge_create_flow`'s caller-chosen
`extra["template_path"]`. Both existed before this refactor. A container
filesystem rule or a path allowlist is needed before exposing those inputs to
connector users.

### Local image check

```bash
docker build -t kissflow-forge:local .
docker run --rm -i --env-file .env -e MCP_HTTP= kissflow-forge:local
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env -e MCP_HTTP=1 kissflow-forge:local
```

The stdio command waits for MCP input on stdin. The HTTP command serves
`http://127.0.0.1:8080/mcp`; a tool call needs the two key headers. Use fake
keys only for local surface checks. Never put a real key in a command line,
chat, image, or repo file.

`FORWARDED_ALLOW_IPS=*` is in the Dockerfile so an ingress that terminates
HTTPS can pass the original scheme through to the server. The prior mesh
returned an `http://` redirect for `/mcp/` when it did not trust the sidecar's
forwarded header. Check `/mcp/` at the served endpoint and require an
`https://` Location before telling a client to use it. Put this image behind
a controlled ingress; the setting trusts forwarded headers from any peer that
can connect to the container.

### Evidence needed for a deployment claim

A successful image build or push proves only that the image exists. Check the
running endpoint's image revision and call a tool whose response identifies
the new behavior before saying the deploy took. Then run `make test-live` as
the account and inspect the result in the Kissflow builder UI. The offline
suite and a successful publish do not prove the rendered flow works.

The 2026-08-13 deployment note named the SRE registry tag
`asia-southeast1-docker.pkg.dev/sre-platform-dev/ai/dev-kissflow-mcp:latest`
and a mesh-fronted endpoint. Those were historical observations, not a
verified target for this refactor. Confirm the current registry, compute
service, revision, and route with SRE before pushing or rolling it.
