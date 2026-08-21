## Deploying the MCP server

The engine ships as a hosted MCP. Get the deploy TARGET right or you ship into a
void, exactly as happened 2026-08-13: an image built and pushed "clean" to the
wrong registry, reported deployed, while the live endpoint kept running
months-old code — a retest then read every fix as still broken. The bytes
landing somewhere is not the same as the endpoint serving them.

- **Live endpoint**: `dev-kissflow-mcp.cjexpress.info`, fronted by an
  **Istio/Envoy service mesh + Azure Entra oauth2-proxy** at the edge
  (`server: istio-envoy`, a private RFC-1918 IP; the proxy 302s browsers to
  Microsoft login but lets programmatic `/mcp` POSTs through). `type:http`
  direct for Claude Code; a uvx `fastmcp-remote` bridge for Desktop.
- **The image the deploy actually targets**:
  `asia-southeast1-docker.pkg.dev/sre-platform-dev/ai/dev-kissflow-mcp:latest`
  (the **SRE** project `sre-platform-dev`, repo `ai`). Prior working deploys
  and the 2026-08-13 one all push `:latest` here; the mesh serves off that tag.
  ⚠️ **UNCONFIRMED**: whether the backend compute behind the mesh is GKE pods
  or a Cloud Run service *inside* `sre-platform-dev` — only that this SRE
  registry tag is the deploy target and the endpoint is mesh-fronted. Do not
  upgrade either guess to fact without a live check.
- **A DECOY to ignore**: there is a SEPARATE Cloud Run service `kissflow-forge`
  in project `ai-coe-dev` (registry `.../ai-coe-dev/cloud-run-source-deploy/
  kissflow-forge`) that is NOT the live endpoint — no domain mapping points the
  cjexpress host at it, and its newest revision fails readiness (the runtime
  compute SA lacks `secretmanager.secretAccessor` on the wired secrets), so it
  serves a stale revision regardless. Never reason about "what's live" from
  this service's digest — that mistake cost a whole deploy round.
- **Who can push**: the SRE repo needs `artifactregistry.writer` on
  `sre-platform-dev/ai`. A human org account (the owner's own `gcloud`) has it;
  the `ai-coe-dev` Cloud Build SA does NOT — so `gcloud builds submit --tag
  <sre-path>` builds fine but **fails on the push**, and `--project
  sre-platform-dev` fails earlier on `serviceusage.services.use`. Build where
  you have Cloud Build (or locally), then push with a permitted account.
- **Working recipe** (build local amd64, push with the owner's account):
  ```bash
  docker build --platform linux/amd64 \
    -t asia-southeast1-docker.pkg.dev/sre-platform-dev/ai/dev-kissflow-mcp:latest .
  docker push asia-southeast1-docker.pkg.dev/sre-platform-dev/ai/dev-kissflow-mcp:latest
  ```
  Then the mesh rolls; if it does not auto-roll,
  `kubectl rollout restart deployment/dev-kissflow-mcp -n <namespace>` (needs a
  kubectl context this repo does not carry — that step is the mesh owner's).
- **THE RULE, for deploys**: a successful `docker push` proves the bytes
  landed, NOTHING about what serves. The only oracle that a new build is
  actually live is a **behavioral tell in the running endpoint** — e.g. a
  field the new code emits that the old one never did. When shipping a fix,
  leave such a tell and read it back through the live endpoint before claiming
  the deploy took.

### Serving over HTTP — the wire contract

`MCP_HTTP=1` runs `streamable-http` at `/mcp` (fastmcp 3.4.7). Every request needs
`Content-Type: application/json` **and** `Accept: application/json, text/event-stream` —
both media types, comma-joined. One of them alone returns the app's own 406,
`Not Acceptable: Client must accept both application/json and text/event-stream`; that
error is the app talking, never the proxy. Request `Content-Type` is **always**
`application/json` — the body you send is JSON, never a stream. The *response* comes
back `content-type: text/event-stream` even for a plain `POST`: a body of
`event: message` / `data: {...}` lines, not bare JSON. A client that assumes JSON on a
POST reply parses nothing. Only the error paths (406, 400) answer `application/json`.
`POST initialize` mints the session and returns it as the `mcp-session-id` **response**
header; every later call, including `GET` and `DELETE`, must send it back as
`Mcp-Session-Id` or get `400 Bad Request: Missing session ID`. `GET /mcp` is the
server-push stream: 200, `content-type: text/event-stream`, `x-accel-buffering: no`,
then it holds open with no bytes — that silence is health, not a hang.
`scripts/mcp-curl-probe.sh <url>` runs the whole seven-check sequence; run it against
two URLs and diff.

### The proxy trap: a 307 that downgrades to `http://`

`/mcp/` (trailing slash) redirects to `/mcp`, and uvicorn builds that `Location` from
the scheme it *believes* the request used. It honours `X-Forwarded-Proto` only from
`forwarded_allow_ips`, which defaults to `127.0.0.1` alone — fastmcp never sets the
value, and uvicorn reads `os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")`. Behind
the Istio sidecar, inbound arrives from `127.0.0.6`, untrusted, so the header is
dropped and the mesh answers `location: http://dev-kissflow-mcp.cjexpress.info/mcp` on
**every** method — GET, POST, DELETE alike. MCP clients refuse that downgrade, which is
why Claude Desktop cannot add the URL while curl against `/mcp` (no slash) works fine.
Fix is one deployment env var, `FORWARDED_ALLOW_IPS=*`; acceptance check is
`curl -sSD- -o /dev/null https://<host>/mcp/ | grep -i location` returning `https://`.

**ngrok is the free A/B rig.** Same image, tunnelled from loopback, is trusted by
uvicorn and answers `https://` — so anything that works over ngrok and fails on the
mesh is a proxy-layer difference, never a code difference. Reproduce the untrusted case
with no cluster at all: hit the local server on `127.0.0.1` (trusted, `https` Location)
versus its LAN IP (untrusted, `http` Location). Verified 2026-08-18; a full SRE-facing
writeup of that run is at `docs/sre-mcp-curl-repro.md`.

CORS is **not** part of this: `OPTIONS /mcp` returns 405 with no `Access-Control-*`
headers on the mesh and over ngrok identically, so it never explains a Desktop failure.
It blocks browser-based clients only.

### Per-user Kissflow credentials, carried in over OAuth

Over HTTP the server holds **no** shared Kissflow key. Each caller pastes their **own**
access-key pair into Claude Desktop's connector dialog — key ID into `OAuth Client ID`,
key secret into `OAuth Client Secret` — and `kfforge/auth.py` turns that pair into the
credential every `forge_*` call spends. Kissflow's own role model, not ours, then bounds
what each person can do, and no key needs an admin to mint.

Those two dialog fields are **not** a pipe for two loose strings. Desktop spends them in a
real OAuth 2.1 authorization-code exchange, so the server has to be an authorization
server for the pair to arrive at all. Enable it with `MCP_OAUTH_BASE_URL` (the public
`https://` origin) plus `MCP_OAUTH_SIGNING_KEY` (≥32 chars of entropy, **identical on
every replica** — a per-process key breaks refresh and breaks multi-pod). Leave
`MCP_OAUTH_BASE_URL` unset and the endpoint stays exactly as unauthenticated as before,
warned about at startup.

`/token` itself is unauthenticated and unthrottled by design — each POST validates a
pasted Kissflow key pair and its 200-vs-401 response is a live oracle for guessing one —
so the Entra/oauth2-proxy + Istio mesh edge in front of this server is the required
shield (rate limiting and access control both live there, no rate limiter lives in the
code); never expose this endpoint raw to the internet without that edge.

Everything is **stateless**: auth codes, access tokens and refresh tokens are all Fernet
blobs sealed with a key derived from `MCP_OAUTH_SIGNING_KEY`. Nothing is kept in memory,
so a pod restart or a second replica changes nothing. Sealed rather than merely signed
because the tenant secret rides inside the token, and a token in a log must not leak a
Kissflow key.

Four wire facts, each probed live against fastmcp 3.4.7, none of them guessable from the
docs:

- **The `/token` request body is unreadable from `get_client`.** fastmcp's request
  contextvar hands back a *different* `Request` object than the one the SDK's
  `TokenHandler` already drained, so `await req.form()` there dies with `Receive channel
  has not been made available`. Headers survive; the body does not. That is the entire
  reason `CaptureTokenBody` exists — an ASGI middleware that drains `/token` once, stashes
  the parsed form in a contextvar, and replays it downstream.
- **`validate_scope` refuses any scope the client was not "registered" with**, and there
  is no registration step to register one in (DCR is deliberately off — that is *why* the
  connector shows manual fields). The provider echoes the requested scope straight back
  onto the client record. Scopes carry no authorization meaning here.
- **`redirect_uris` must hold at least one entry** or the pydantic model raises and the
  route 500s. The `refresh_token` grant sends no redirect at all, so that leg gets a
  placeholder that is never redirected to; a redirect outside the allowlist returns `None`
  from `get_client` (a clean invalid-client), never an empty list.
- **`fastmcp.server.middleware.Middleware` and `starlette.middleware.Middleware` collide.**
  Importing the Starlette one unaliased into `server.py` silently re-parents
  `_CoerceJsonStringArgs` and every tool call dies with `'_CoerceJsonStringArgs' object is
  not callable`. It is imported as `ASGIMiddleware`.

`/authorize` is a **browser** hit, so the Entra proxy in front may bounce it through
Microsoft login first. That is fine — and arguably a second layer — **provided the proxy
preserves the query string** across the bounce; OAuth dies without `state`,
`redirect_uri` and `code_challenge`. Check before deploying, from a machine that can
reach the host:

```bash
curl -sS -D- -o /dev/null \
  "https://dev-kissflow-mcp.cjexpress.info/authorize?state=PROBE123&foo=bar" \
  | grep -i "^HTTP\|^location"
```

A 404 is a pass — it proves the proxy let the request reach the app. If `PROBE123` is
missing from the `location` header, the mesh owner must exempt `/authorize`, `/token` and
`/.well-known/*` from the Entra redirect. **UNVERIFIED as of 2026-08-19**: this probe has
not been run; the repo host has no route to that endpoint.

Ceilings, stated rather than hidden. A stateless auth code is replayable inside its 60s
TTL, unlike a consumed one — PKCE binds it to the caller's verifier and `/token`
re-validates the Kissflow secret, so a replay needs both, but there is no single-use
table. A stateless token cannot be revoked; rotate the key in Kissflow instead, which a
refresh notices within the hour. `tests/test_oauth_per_user.py` proves the flow end to end
against a real spawned server — offline unit tests of the provider would have proven none
of it.
