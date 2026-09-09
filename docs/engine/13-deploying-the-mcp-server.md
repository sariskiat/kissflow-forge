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

The combined provider is intentionally narrow. FastMCP 3.4.7's AzureProvider keeps the Entra
PKCE, CSRF/state, callback, upstream token validation, refresh rotation, and JTI mappings. The
Kissflow extension only does the following:

1. Static `get_client` synthesizes a `ProxyDCRClient`; it never falls through to DCR storage or
   CIMD. `/authorize` needs the key ID and redirect only. `/token` requires a presented secret but
   does not validate it during lookup.
2. `exchange_authorization_code` runs only after FastMCP has loaded the code and checked redirect
   binding plus PKCE. A failed Kissflow check consumes that code. A successful check calls the
   AzureProvider exchange, then reissues only the access JWT with the same JTI, client, scopes,
   and remaining expiry.
3. `exchange_refresh_token` runs only after FastMCP has found the stored refresh-token metadata.
   It validates the pair before upstream refresh, calls the parent exchange, leaves the parent's
   rotated refresh token unchanged, and binds the newly issued access JWT again.
4. The encrypted pair is merged into `upstream_claims`; existing Entra claims such as `oid` and
   `sub` remain. The raw secret is absent from JWT text. The visible OAuth `client_id` is the
   caller's Kissflow key ID, which is an identifier rather than a secret.

HTTP startup requires `MCP_OAUTH_BASE_URL` (or `AZURE_BASE_URL`), `MCP_OAUTH_SIGNING_KEY`
(≥32 chars of entropy), `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`,
`AZURE_REQUIRED_SCOPES` with at least one application scope, and a complete Kissflow tenant
domain/account. A partial set aborts startup; there is no unauthenticated HTTP mode and no
`KF_*` fallback. Stdio does not construct the provider and keeps its process-env path. Istio is
not required by this authentication layer.

`ALLOWED_EMAIL_DOMAINS` is optional. When configured, the provider reads only email-shaped claims
from the validated Azure upstream claims (`preferred_username`, `email`, or `upn`), normalizes the
domain, and rejects missing or disallowed values. `oid` and `sub` are preserved. This allowlist
checks directory claims only; the two-gate exchange does **not** prove that the Entra account owns
the Kissflow account. That stronger directory-to-Kissflow identity comparison would require a
captured Kissflow identity lookup and is deliberately not added here.

Redirects use FastMCP's component-aware validator with explicit defaults:
`http://localhost:*`, `http://127.0.0.1:*`, `http://[::1]:*`, `https://claude.ai/*`, and
`https://*.claude.ai/*`. Configured patterns reject userinfo, unsafe schemes, encoded or literal
dot-segments, and non-HTTPS remote callbacks; the same list protects authorization and the
upstream callback. `/register` and CIMD metadata are absent. Metadata still advertises the
configured application scopes and `client_secret_post`/`client_secret_basic` methods.

The default FastMCP encrypted disk store contains transactions, authorization codes, encrypted
upstream token sets, JTI mappings, and refresh metadata. It is safe for exactly one active replica.
An ephemeral-disk restart loses sessions and requires re-login; add shared client storage before
scale-out. No Firestore, proxy, or tool argument carries a secret.

`CaptureTokenBody` preserves the 3.4.7 request-body seam for static lookup and returns an empty 413
before accumulating more than 64 KiB. It never logs or echoes a malformed or oversized body.
`tests/test_oauth_per_user.py` uses a local ASGI harness with fake identity and Kissflow services;
it does not call live Entra or Kissflow. Its contract checks include authorize redirect ordering,
code consumption, refresh rotation, encrypted-claim tampering, DCR/CIMD absence, redirect
bypasses, bounded token bodies, startup failure, and HTTP refusal of process keys.

Four wire facts, each probed against FastMCP 3.4.7:

- The SDK's `TokenHandler` drains `/token` before `get_client`; `CaptureTokenBody` is the bounded
  replay seam. It preserves headers, never logs the form, and returns an empty 413 over 64 KiB.
- `validate_scope` still runs on the synthetic static client, so configured application scopes stay
  correct even though DCR is disabled.
- `redirect_uris` must contain a placeholder entry for the Pydantic model. Actual callbacks are
  checked by FastMCP's component-aware patterns, and refresh uses a never-redirected placeholder.
- `fastmcp.server.middleware.Middleware` and `starlette.middleware.Middleware` remain distinct;
  `server.py` imports the latter as `ASGIMiddleware`.

`/authorize` is a **browser** hit and the AzureProvider sends it to Microsoft Entra. Any optional
edge in front must preserve the query string across a bounce; OAuth dies without `state`,
`redirect_uri` and `code_challenge`. Check before deploying, from a machine that can reach the host:

```bash
curl -sS -D- -o /dev/null \
  "https://dev-kissflow-mcp.cjexpress.info/authorize?state=PROBE123&foo=bar" \
  | grep -i "^HTTP\|^location"
```

A 404 is a pass — it proves the edge let the request reach the app. If `PROBE123` is missing from
the `location` header, the edge owner must preserve `/authorize`, `/token`, and `/.well-known/*`
without dropping their query strings. This repository has not run that live probe.

Ceilings, stated rather than hidden. FastMCP's encrypted file store is one-replica state: an
ephemeral-disk restart loses transactions, codes, upstream tokens, JTI mappings, and refresh
metadata, so sessions require re-login. Access-token revocation follows the upstream Kissflow
pair; shared storage is required before scale-out. The offline ASGI tests do not call live Entra or
Kissflow.
