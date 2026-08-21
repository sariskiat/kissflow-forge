# Kissflow Forge — Demo Setup (Claude Code tab)

Connect Claude Code (the **Code** tab in the Claude Desktop app) to the Kissflow
Forge demo server. Takes about 2 minutes. The server is live only during the
demo session, then it shuts off.

**Demo server URL:** `https://bronze-grouped-turret.ngrok-free.dev/mcp`

No login and no key is needed for this demo. Everyone shares one demo identity
on the **dev tenant only** — nothing you do here can touch production.
Please don't share the link outside the demo group.

---

## Step 0 — Check your network first (30 seconds)

We're on a corporate network (GlobalProtect VPN, proxies). Some of them block
tunnel domains like `ngrok-free.dev`. Check before changing any settings.

Open a terminal and run:

```bash
curl -m 10 -s -o /dev/null -w '%{http_code}\n' \
  -X POST https://bronze-grouped-turret.ngrok-free.dev/mcp \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"check","version":"0"}}}'
```

- **`200`** → you're good, go to Step 1.
- **`000`, timeout, or a TLS/certificate error** → the VPN or proxy is blocking
  the tunnel. Easiest fixes, in order:
  1. Disconnect GlobalProtect for the demo (if your policy allows), or
  2. Use your phone's hotspot for this session, or
  3. Tell the presenter — we'll pair you with someone who's connected.
- **Any other number (403, 502, …)** → a proxy is answering instead of our
  server. Same fixes as above.

---

## Step 1 — Add the server to Claude Code

Open a terminal and run one command:

```bash
claude mcp add --transport http --scope user kissflow-forge https://bronze-grouped-turret.ngrok-free.dev/mcp
```

That's it. (`--scope user` makes it available in every folder you open.)

**If the command isn't found** (no `claude` CLI on your PATH), edit the file
`~/.claude.json` instead and add this inside it (create the `mcpServers` block
if it doesn't exist):

```json
{
  "mcpServers": {
    "kissflow-forge": {
      "type": "http",
      "url": "https://bronze-grouped-turret.ngrok-free.dev/mcp"
    }
  }
}
```

Windows path for the same file: `C:\Users\<you>\.claude.json`.

---

## Step 2 — Verify inside the Code tab

1. Open the Claude Desktop app → **Code** tab → start a session in any folder.
2. Type `/mcp` — you should see **kissflow-forge** listed as connected,
   with about 57 tools.
3. Ask: **"list my Kissflow apps"** — you should get a real list back.

If `/mcp` shows the server as failed: quit and reopen the app once, then
re-check Step 0 (network) — that's the cause almost every time.

---

## Step 3 — Try it

Ask things like:

- "Create a Kissflow template app named **\<your name\> Demo**"
- "List my Kissflow apps"
- "Run forge_doctor on the process in my new app"

Creating a template app takes about a minute — it builds a full app (form,
computed fields, workflow) and gives you back a builder link.

---

## Rules for the session

- Dev tenant only — the server refuses anything else by design.
- Everyone shares one demo identity, so name your app after yourself to avoid
  collisions. Duplicate names are rejected loudly, just pick another.
- The link dies when the demo ends.
