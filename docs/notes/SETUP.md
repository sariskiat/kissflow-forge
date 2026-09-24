# SETUP — for Claude, setting this repo up for a non-technical owner

**Audience: you, Claude, running on this person's computer (Claude Desktop or Claude Code),
with a repo clone in front of you.** The human who owns you is non-technical, has no Python,
and does not know git or repos. Do NOT ask them to run commands or explain jargon. **You** do
every technical step below, in the terminal, and only ask them for the thing marked
**ASK THE HUMAN**. Explain what you're doing in one plain sentence per step, no jargon.

This is the only setup document in this repo root. Two neighbours cover different audiences:

- `docs/connect-claude-desktop.md` — for the **end user** of the already-hosted server. If
  someone just wants to *use* Kissflow Forge and a server is already running somewhere, send
  them there instead; nothing below is needed.
- `docs/engine/13-deploying-the-mcp-server.md` — for whoever **deploys** the hosted server.

Goal here: get the **kissflow-forge MCP** running locally so this person can build Kissflow
apps by chatting with you. It's a small server on their machine; you start it, connect
yourself to it, and the `forge_*` tools appear in your tools list.

---

## What this is (one line)
A local tool-server. You launch it from this folder; Claude talks to it; it edits a Kissflow
dev tenant. No cloud, no account setup — just this folder + a secrets file + you.

---

## Step 0 — find this folder
This file lives in the repo folder (e.g. `~/Desktop/kissflow-forge` or wherever they saved it).
Note its full path — call it `REPO`. Every command below runs from `REPO`.

## Step 1 — install `uv` (this also gives you Python; nothing else needed)
Check if it's already there: `uv --version`.
If missing:
- **macOS/Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh` then reopen the terminal.
- **Windows:** `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.

You do NOT need to install Python separately — `uv` handles it. Run `uv sync` once to build
`.venv` from `uv.lock`; after that every command is a plain `uv run ...` or `make ...`.

## Step 2 — create the secrets file `.env`  ← **ASK THE HUMAN**
The server needs 5 secret values. There is a template at `.env.example`. Copy it to `.env`
in `REPO`:
```bash
cp .env.example .env
```
Then fill these 5 keys in `.env`:
```
KF_DEV_DOMAIN=          # the Kissflow dev URL (e.g. dev-kissflow.xxxx.co.th)
KF_DEV_ACCOUNT_ID=      # the account id
KF_DEV_ACCESS_KEY_ID=   # a secret
KF_DEV_ACCESS_KEY_SECRET=  # a secret
KF_APP=                 # which app to build in
```
The engine only ever talks to a dev tenant: `KF_DEV_DOMAIN` must be a plain hostname that
contains `dev-`, and the server refuses to start on anything else. There is no non-dev
opt-out — every tenant this engine ever builds against is a `dev-` one.
**ASK THE HUMAN to get these 5 values from the person who gave them this folder** (send them
privately — a DM or password manager, never a public chat). Paste the values in and save.
⚠️ `.env` holds live credentials. It is already git-ignored — never commit it, never paste the
keys into any shared document or chat.

## Step 3 — smoke-test the server (proves it boots + the tools exist)
Run this from `REPO`:
```bash
set -a; . ./.env; set +a
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| uv run mcp-server 2>/dev/null
```
Success = a big JSON blob listing tools whose names start with `forge_` and `kf_`.
(First run is slow — it downloads the dependency once. If it errors, the `.env` values are
probably wrong — re-check Step 2 with the human.)

## Step 4 — connect yourself to the server
Pick the one that matches how you're running:

### If you are **Claude Desktop**
Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) — create it if
missing — and add a server entry. **Use the real absolute `REPO` path**:
```json
{
  "mcpServers": {
    "kissflow-forge": {
      "command": "sh",
      "args": ["-lc", "cd 'REPO' && set -a; . ./.env; set +a; exec uv run mcp-server"]
    }
  }
}
```
If the file already has other servers, add `kissflow-forge` inside the existing `mcpServers`
object — don't delete what's there. Then **fully quit and reopen Claude Desktop**.

### If you are **Claude Code** (the CLI)
From `REPO`, run:
```bash
claude mcp add kissflow-forge -- sh -lc "cd '$(pwd)' && set -a; . ./.env; set +a; exec uv run mcp-server"
```
Then restart the session (or run `/mcp` and reconnect).

## Step 5 — verify it works
In a new chat, run the `/mcp` command (or check the tools list) — you should see
`kissflow-forge` connected with `forge_*` / `kf_*` tools.
Then do a live check: call **`forge_list_apps`**. If it returns a list of apps, everything works.

---

## Alternative to Steps 1–4: run it from the Docker image
Use this when the machine has Docker but you'd rather not install `uv`, or when handing the
server to a colleague who has no clone. Same stdio transport, same tools.

```bash
docker build -t kissflow-forge:local .          # one-time, in REPO
# ship it: docker save kissflow-forge:local | gzip > kissflow-forge.tar.gz
# receive:  docker load < kissflow-forge.tar.gz
```

Then `cp .env.example kf.env`, fill the same 5 secrets, and point the MCP config at Docker
instead (`.mcp.json` for a project, or `~/.claude.json`), with the absolute path to `kf.env`:

```json
{
  "mcpServers": {
    "kissflow-forge": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "MCP_HTTP=", "--env-file", "/abs/path/to/kf.env", "kissflow-forge:local"]
    }
  }
}
```

- `-e MCP_HTTP=` blanks the Dockerfile's `MCP_HTTP=1`, forcing stdio. Leave it in — HTTP mode
  is for the hosted deployment, not a local session.
- `-i` keeps stdin open for the MCP handshake; `--rm` cleans up per session.
- Smoke-test it exactly as in Step 3, piping the same three JSON lines into
  `docker run -i --rm -e MCP_HTTP= kissflow-forge:local 2>/dev/null`.
- ⚠️ Every colleague sharing `KF_APP` writes to the SAME live dev tenant. Fine for a demo,
  risky if two people build at once.

---

## Daily use (tell the human this)
Once Step 4 is done, it's automatic: every time they open Claude, you auto-start the server and
the tools are ready. They just chat — "build me a Kissflow process that…", "add a field…",
"why doesn't my form render…" — and you drive the `forge_*` tools. There's a full playbook in
`skills/kissflow-forge-builder/SKILL.md`; read it before building anything, and follow **THE
RULE**: a 200/publish proves nothing — always verify by reading the graph back (`forge_doctor`)
and walking a real item (`forge_simulate_case`).

## If something breaks
- Tools missing → the server isn't connecting. Re-run Step 3's smoke test; if it fails, the
  `.env` is wrong (Step 2).
- A tool hangs or errors → run `forge_doctor` on the flow and read what it says; never trust a
  bare success.
- Still stuck → tell the human to ping the person who gave them this folder.

**Never** paste the `.env` values into a chat, commit them, or put them in this file.
