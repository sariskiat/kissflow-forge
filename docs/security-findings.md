# Security findings — dev-kissflow-mcp deployment

**Status: historical record and remediation note.** Finding A described the former unauthenticated
HTTP deployment. The application now fails closed in HTTP mode unless Entra configuration and the
OAuth signing key are present; the deployment wizard supplies those values through Secret Manager.
Finding B remains a credential-rotation action for the tenant administrator.

| | Finding | Recorded | Owner | Status |
|---|---|---|---|---|
| **A** | Deployed MCP endpoint answers unauthenticated callers | 2026-08-19 | Saris Kiattithapanayong (`@saris.kia`) | Open — decision route below |
| **B** | Azure client secret pasted into a chat window | 2026-08-19 | Saris Kiattithapanayong (`@saris.kia`), routing to the Azure tenant administrator | Rotation **PENDING** |

Tracker: GitLab issue
[#3](https://gitlab.cjexpress.io/cjexpress/tildi/infra/ai-coe/kissflow-forge/-/work_items/3),
parent spec [#2](https://gitlab.cjexpress.io/cjexpress/tildi/infra/ai-coe/kissflow-forge/-/work_items/2).

**Rule for this file and for the tracker: identifiers only.** The client secret value and the
access token value are never written into this repository, into any issue, or into any commit
message. Anything below that could identify a credential is an application id, a tenant id, or a
registration name — never a secret.

---

## Finding A — the deployed endpoint answers strangers

`https://dev-kissflow-mcp.cjexpress.info/mcp` accepts an MCP `initialize` from a caller that
presents no credential of any kind. It returns HTTP 200, mints a working MCP session, and that
session can list and call the tool surface — including every tool that writes to the live Kissflow
tenant. There is no app-level authentication in front of it.

### Evidence

Collected 2026-08-19 against the running deployment. Three checks, in order.

**1. Neither OAuth discovery document is served.** An MCP client that wanted to authenticate has
nothing to discover:

```bash
$ curl -s -o /dev/null -w "%{http_code}\n" \
    https://dev-kissflow-mcp.cjexpress.info/.well-known/oauth-authorization-server
404
$ curl -s -o /dev/null -w "%{http_code}\n" \
    https://dev-kissflow-mcp.cjexpress.info/.well-known/oauth-protected-resource
404
```

**2. An unauthenticated `initialize` mints a session.** No `Authorization` header, no cookie, no
client certificate:

```bash
$ curl -s -i -X POST https://dev-kissflow-mcp.cjexpress.info/mcp \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
         "protocolVersion":"2025-06-18","capabilities":{},
         "clientInfo":{"name":"issue-3-evidence","version":"1"}}}'
HTTP/2 200
date: Wed, 19 Aug 2026 11:09:53 GMT
server: istio-envoy
content-type: text/event-stream
mcp-session-id: dc03d154410944d78077764e65a0427d
x-envoy-upstream-service-time: 3

event: message
data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18", ...
      "serverInfo":{"name":"kissflow-forge","version":"3.4.7"}}}
```

The response names the service (`kissflow-forge`). The `3.4.7` alongside it is the **fastmcp
library version**, not a build number of this engine — `kfforge/server.py` constructs
`FastMCP("kissflow-forge")` with no explicit version, so the framework's own version is what gets
echoed (confirmed locally: `fastmcp 3.4.7`). It is still a version fingerprint handed to an
unauthenticated caller; it just names the framework rather than the app.

**3. The session reaches the live-tenant write surface.** Continuing on that same unauthenticated
session id, `notifications/initialized` returned `202` and `tools/list` returned the full surface:

```
tool_count: 56
write tools present: kf_apply_field_change, kf_create_process, kf_publish,
                     forge_create_process, forge_create_app_role, forge_delete_app_role,
                     forge_apply_fields, forge_apply_layout, forge_create_list,
                     forge_publish, forge_create_page, forge_create_app
```

Only `tools/list` was called. No tool was invoked, so nothing was created, changed, or deleted on
the tenant during this verification. The point of the check was reachability of the write surface,
and reachability is what it shows: creation, publication, and deletion tools are all callable by
whoever holds that session.

The container carries the tenant's own Kissflow access key pair in its environment
(`KF_DEV_ACCESS_KEY_ID` / `KF_DEV_ACCESS_KEY_SECRET`, read in `kfforge/client.py:83-85`), so an
anonymous caller does not need any Kissflow credential of their own. They inherit the server's.

### This is known, intentional, and written down in the code

Nothing here is a surprise to the codebase. It is the documented consequence of commit `6f70b40`
("remove Google OAuth from HTTP mode; rely on network-layer protection"):

- `kfforge/server.py:1828-1834` prints a loud stderr warning on every HTTP start: *"MCP_HTTP
  serving WITHOUT app auth — the live-tenant write API is open to anyone who can reach this URL.
  Protect it at the network layer."*
- The `Dockerfile` header says the same thing in its first three lines.

The design bet was that the network layer would be the only thing able to reach the container. The
finding is that this bet has not been verified to hold, and that nothing in the app fails closed
if it does not.

### What is verified, and what is inherited

Stated precisely, because the two halves have different evidence behind them:

- **Verified 2026-08-19 by the checks above: the endpoint requires no authentication.** Reproduced
  directly, output above.
- **Inherited from issue #2, not re-run today: reachability from an arbitrary machine on the
  public internet.** The verification above ran from the repository owner's laptop, which has
  active VPN interfaces (`utun0`–`utun7`), and from that host the name resolves to `172.25.0.71`
  — an RFC1918 private address. So this run proves *unauthenticated*, and proves it from inside
  the corporate network; it does not itself prove *publicly reachable*. The public-internet claim
  rests on the off-network test recorded in issue #2.

**Open verification step, owned by the same owner as the finding:** re-run check 2 above from a
machine with no VPN and no corporate DNS, and record the result here. If it 200s, the finding is
"open to the internet". If it fails to resolve or connect, the finding narrows to "open to
everyone on the corporate network", which is materially smaller but still an unauthenticated write
path to a live tenant. Both outcomes are worth writing down; neither is worth guessing.

### One more fact, easy to miss

The per-user Kissflow credential path referred to in issues #2 and #3 as `kfforge/auth.py` **is not
in git**. On `develop` at `035adcf` the file does not exist, and `git log --all -- kfforge/auth.py`
returns nothing. It exists only as an untracked file in the owner's main working tree
(`git status` reports `?? kfforge/auth.py`), where an equally untracked edit to `server.py` wires
it in (`from .auth import provider_from_env`, `FastMCP("kissflow-forge", auth=_oauth)`).

That path is gated on the `MCP_OAUTH_BASE_URL` environment variable: `provider_from_env()` returns
`None` when it is unset, "which leaves the endpoint unauthenticated exactly as it is today". So
the deployment is unauthenticated for either of two independent reasons — the code was never
committed, or the variable was never set — and the served `404`s on both well-known paths are
consistent with both. Do not plan work on the assumption that this feature merely needs switching
on; first get it committed, then decide whether it is the path being taken at all (see the
decision below).

### Decision route

- **Owner:** Saris Kiattithapanayong (`@saris.kia`), as the person who routes it to the team that
  controls the mesh and ingress.
- **Route:** raise with the SRE team that owns the Istio mesh in front of this service, as part of
  the issue #2 handover. User story 10 of issue #2 already commits to telling SRE plainly that the
  endpoint has no authentication in front of it, so the handover conversation is where this lands.
- **Decision required of them:** whether the mesh policy restricts who can reach this service, and
  whether that restriction is enforced rather than assumed.
- **Not decided here:** the choice between an Azure-fronted proxy and the per-user credential
  path. See below.

---

## Finding B — an Azure client secret was pasted into a chat window

The client secret belonging to the Azure app registration below was shared in plain text in a chat
window, together with a live access token minted from that secret.

| Item | Identifier |
|---|---|
| App registration name | `tildi-sre-oauth2-proxy-dev` |
| Application (client) id | `050eb0b0-3c37-49eb-9be7-ae7b33c2e048` |
| Directory (tenant) id | `47ae80c1-67e8-4e84-bcf6-96d15fafaf76` |

**The secret value and the token value are not reproduced here, and must never be written into
this repository, the tracker, a commit message, or a pull request.** The identifiers above are
enough to act on: they are what an administrator needs to find the registration in Entra ID.

### Evidence

The paste itself. No command reproduces this finding and none should be written — reproducing it
would mean handling the secret again. What is recorded is the shape of the exposure:

- A client secret for `tildi-sre-oauth2-proxy-dev` was transmitted in plain text through a chat
  interface, on 2026-08-19 or earlier.
- A bearer access token minted from that secret was transmitted alongside it.
- Chat transcripts persist. Assume the secret is retained wherever that conversation is stored,
  for as long as that store retains it, reachable by anyone who can read it.

### Why the two halves are not equally urgent

**The token expires by itself. The secret does not.** An Azure access token carries a short
lifetime and stops working when it elapses, with no action from anybody. A client secret stays
valid until its configured expiry date — typically months or years out — or until a human
explicitly rotates it. Waiting is a remedy for the token and is not a remedy for the secret.

Anyone holding the secret can mint fresh tokens for this app registration at will, for as long as
the secret remains valid. Whatever that registration is authorised to do, they can do. The blast
radius is whatever `tildi-sre-oauth2-proxy-dev` has been granted in tenant
`47ae80c1-67e8-4e84-bcf6-96d15fafaf76`; establishing that scope is part of the owner's action
below, not something this document asserts.

### Rotation — PENDING

Rotation has **not** been completed and is recorded here as pending, per the acceptance criteria
of issue #3.

- **Owner:** Saris Kiattithapanayong (`@saris.kia`), as the person routing the request to the
  administrator of tenant `47ae80c1-67e8-4e84-bcf6-96d15fafaf76`.
- **Why it is not done in this body of work:** rotating a secret requires administrative access to
  the Azure tenant. Nobody working this issue has it, and no such access should be improvised to
  close a ticket. The request is routed to the person who does hold it.
- **The request, stated so it can be forwarded as-is:**
  1. In Entra ID, open app registration `tildi-sre-oauth2-proxy-dev`
     (client id `050eb0b0-3c37-49eb-9be7-ae7b33c2e048`) in tenant
     `47ae80c1-67e8-4e84-bcf6-96d15fafaf76`.
  2. Create a new client secret. Deliver it through a secret manager or a credential store —
     never through chat, email, or a ticket comment.
  3. Update every consumer of the old secret to the new one. The registration's name says its
     consumer is an OAuth2 proxy; confirm the full consumer list before step 4, because deleting
     first and discovering consumers afterwards is an outage.
  4. **Delete the old secret.** Rotation is not complete until the old secret is deleted. Adding a
     new secret alongside it leaves the leaked one valid.
  5. Review the sign-in and audit logs for this application over the exposure window for
     authentications that are not the proxy itself.
- **Recording completion:** when the old secret is deleted, update the status line in this
  document's table to `Rotated <date>`, name who performed it, and note it on issue #3. Record the
  fact, never the new value.

---

## No fix ships in this body of work

Neither finding is fixed here, and that is a deliberate scope decision rather than an omission.

**Finding B is not fixed here** because rotating the secret needs Azure tenant administration
rights that this work does not have and should not acquire. Writing it down with a named owner and
a forwardable request is the whole of what this work can honestly do.

**Finding A is not fixed here** because fixing it means choosing between two different products,
not applying a patch. Both options close the hole. They hand the end user different things:

| | Azure-fronted proxy | Per-user credential path (`kfforge/auth.py`) |
|---|---|---|
| Who authenticates | The corporate identity provider, in front of the service | The MCP server itself, per caller |
| What the end user does | Signs in with their corporate account when adding the connector | Pastes their own Kissflow access-key pair into the connector's OAuth client id / client secret fields |
| Whose Kissflow credential is used | The server's, shared by everyone who gets through the proxy | The caller's own — each user acts as themselves against the tenant |
| Tenant-side attribution | Every action looks like one service account | Each action traces to the person who took it |
| State of the code today | Deployed shape, no app auth, `6f70b40` | Untracked in the owner's working tree; not on `develop`; gated off by `MCP_OAUTH_BASE_URL` |
| What it costs to get there | Mesh and proxy configuration, owned by SRE | Commit the file, set the variable, and document a connector setup a non-technical user can follow |

They are not mutually exclusive — a proxy in front and per-user credentials behind is a coherent
end state — but shipping either one changes what a non-technical end user has to do to add the
connector in Claude Desktop, which is the outcome issue #2 cares about (user stories 11 and 12).
That makes it a product decision with a named owner and a conversation, not a change to be slipped
in while writing down a finding. It is recorded here so the decision is taken deliberately, with
both options and their consequences visible, rather than settled by whichever branch happens to
merge first.

Until that decision is taken and shipped, the endpoint stays as commit `6f70b40` describes it:
unauthenticated, and protected only by whatever the network layer is actually enforcing.
