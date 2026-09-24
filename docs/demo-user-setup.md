# Kissflow Forge demo setup

There is no verified shared demo URL for the current server. The older ngrok
link and no-key instructions described a past session and must not be used for
a new one.

## Local demo

Use [the Claude Desktop setup](connect-claude-desktop.md) to build the image and
start it in stdio mode. Each person supplies a Kissflow **dev-tenant** key pair
in a local `.env` file. Never paste a key in chat or a shared document. The
tools menu should show 61 Kissflow Forge tools.

Ask the client to list apps first. A real build also needs an app ID, either in
`KF_APP` or in the tool call. Creating an app or flow changes the dev tenant;
use a sample name you can identify and clean up after the demo.

## Hosted demo

SRE must confirm the current HTTPS endpoint, Entra sign-in, and forwarding of
`X-Access-Key-Id` and `X-Access-Key-Secret` before giving anyone a hosted
connector link. The server itself does not sign users in. The team's central
Kissflow pair, if used, belongs in the connector's protected settings, not in
these instructions. The two open path controls in the
[refactor spec](specs/refactor-to-mcp-boilerplate.md) must also be resolved
before HTTP access is given to connector users.

A local fake-key Docker run proved the old server's tool surface on 2026-09-23.
The switched server has passed offline checks; the live dev-tenant suite has
not run because the required local settings were absent. A hosted demo and
Claude Desktop connection have not been checked for this version.
