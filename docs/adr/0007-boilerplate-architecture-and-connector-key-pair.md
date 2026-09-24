# Use the boilerplate layout and connector key pair

Approved 2026-09-22 for the Kissflow Forge refactor. The reference is the
local `mcp-server-python-boilerplate` clone at the commit recorded in
`docs/specs/refactor-to-mcp-boilerplate.md`.

The server keeps the existing 61-tool surface but moves each tool to a thin
MCP adapter, one use case, typed request and response data, and ports for
outside calls. Kissflow ports and adapters are grouped by API family. Domain
code stays pure. A single lifespan opens the shared HTTP client. The
boilerplate's folder roles and checks are the rule; every deliberate difference
is recorded in `tests/fixtures/tooling_deltas.toml`.

Entra sign-in belongs to SRE's gateway, outside this repo. The server does not
run an OAuth provider or learn the person's Entra identity. In HTTP mode the
connector sends a Kissflow key pair in `X-Access-Key-Id` and
`X-Access-Key-Secret` on each tool call. The gateway must forward the pair
unchanged and must not log it. The team may use one central Kissflow identity
for the deployed connector; local stdio tests may use a personal dev pair.
`KF_DEV_DOMAIN` and `KF_DEV_ACCOUNT_ID` keep the server on a dev tenant. A
Kissflow production tenant is outside this decision.

The Dockerfile and SRE CI chain remain during this refactor. Live tests stay
out of CI and run on the engineer's machine. A new Dockerfile or SRE gateway
change needs its own review. The gateway header path and the current endpoint
must be checked before a hosted release.

Rejected: keeping the in-repo OAuth proxy, passing a shared key pair through
process settings in HTTP mode, and keeping the old 61 tool bodies around a new
settings class. Those would leave two sign-in layers, make connector keys hard
to change, or retain the old write ordering. A single wide Kissflow port was
also rejected because the API families have distinct calls and failure rules.

The local checks are `make verify`, coverage, the architecture scans, and the
boilerplate conformance test. They do not prove that a flow works in Kissflow's
builder UI. The live dev-tenant suite and a UI readback remain separate proof.
