# Set up and test Kissflow Forge locally (Mac)

This guide runs the kissflow-forge MCP server from your own clone, with your own Kissflow key.
It connects both Claude Code and Claude Desktop. Use a fresh clone so you test exactly what a
colleague gets.

For Windows, see `setup-windows-claude-desktop.md`.

## What you need

- GitLab access to `cjexpress/tildi/infra/ai-coe/kissflow-forge` (private repo), and a GitLab
  personal access token with `read_repository` if you sign in with the Microsoft button (use it
  as the password when `git clone` asks). See Step 0 of `setup-windows-claude-desktop.md`.
- Your own Kissflow dev key pair (Access Key ID + Secret), the dev tenant domain (starts with
  `dev-`) and the account ID.
- `git`, `uv` (`brew install uv`), and Claude Code and/or Claude Desktop.

## Step 1. Clone and install

```bash
cd ~
git clone https://gitlab.cjexpress.io/cjexpress/tildi/infra/ai-coe/kissflow-forge.git kissflow-forge-test
cd kissflow-forge-test
uv sync
```

## Step 2. Add your key

```bash
cp .env.example .env
open -e .env
```

Fill these four lines, one `KEY=value` per line, no quotes:

```
KF_DEV_DOMAIN=<dev tenant domain>
KF_DEV_ACCOUNT_ID=<account id>
KF_DEV_ACCESS_KEY_ID=<your access key id>
KF_DEV_ACCESS_KEY_SECRET=<your access key secret>
```

A line without `=` breaks the file. Never commit or share `.env`.

## Step 3. Check settings and files

```bash
uv run python -c "from app.infrastructure.config.settings import load_settings; from app.infrastructure.playbook import PLAYBOOKS, read_playbook; from app.infrastructure.capabilities import find_capabilities; s = load_settings(); c = find_capabilities(''); print('OK', s.kf_dev_domain, '| key set:', bool(s.kf_dev_access_key_id), '| skills:', [len(read_playbook(p)['text']) for p in PLAYBOOKS.values()], '| docs:', len(c['docs']), '| errors:', c['errors'])"
```

Pass: `OK dev-... | key set: True | skills: [...] | docs: ... | errors: []`.

## Step 4. Connect Claude Code

If an older `kissflow-forge` or `kissflow-dev` entry points at a server URL, remove it first:

```bash
claude mcp remove kissflow-forge -s user
claude mcp remove kissflow-dev -s user
```

Add the local server:

```bash
claude mcp add kissflow-forge -s user -- uv --directory $HOME/kissflow-forge-test run mcp-server
```

Start a new Claude Code session and run `/mcp`. kissflow-forge shows as connected.

## Step 5. Connect Claude Desktop

Claude Desktop rewrites its config file while it runs, so an edit made with the app open can
be lost. Quit it first.

1. Quit Claude Desktop with **Cmd+Q** (closing the window is not enough).
2. Run this in Terminal. It adds the `kissflow-forge` entry, keeps every other setting, and
   saves a backup next to the file:

   ```bash
   python3 - <<'EOF'
   import json, os, shutil
   p = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
   if os.path.exists(p):
       shutil.copy2(p, p + ".bak")
       d = json.load(open(p))
   else:
       d = {}
   d.setdefault("mcpServers", {})["kissflow-forge"] = {
       "command": "/opt/homebrew/bin/uv",
       "args": ["--directory", os.path.expanduser("~/kissflow-forge-test"), "run", "mcp-server"],
   }
   json.dump(d, open(p, "w"), indent=2)
   print("saved:", list(d["mcpServers"]))
   EOF
   ```

   It prints `saved: [..., 'kissflow-forge']`. If `which uv` is not `/opt/homebrew/bin/uv`,
   change that path in the script first.

3. Open Claude Desktop again.
4. In a new chat, open the tools menu (the slider icon) and open **kissflow-forge**. Switch
   **all** tools on. Desktop remembers switched-off tools per server name, so tools you turned
   off under an older `kissflow-forge` entry stay off, and only newer tools show.

## Step 6. Test

Run each test in a new chat, in each client. Stop at the first failure and keep the exact
error text, then check Troubleshooting below.

| # | Ask Claude | Pass when |
|---|---|---|
| T1 | `/mcp` (Code) or the tools menu (Desktop) | kissflow-forge connected, 61 tools |
| T2 | "List my Kissflow apps with kissflow-forge" | `forge_list_apps` returns your apps |
| T3 | "Call forge_playbook with skill usage" | readable guide text |
| T4 | "Call forge_capabilities with query process-template" | one doc plus its shape, `errors: []` |
| T5 | "Run forge_doctor on flow `<an existing flow id>`" | a doctor report (read-only) |
| T6 (optional, writes) | "Create a process named `zz-local-test` from the template in app `<test app>`, run forge_doctor, then delete it with forge_delete_flow" | created, doctor ok, delete verified |

Never grant a group to a role during a test. Kissflow notifies every member and it cannot be
undone.

## Update later

```bash
cd ~/kissflow-forge-test && git pull && uv sync
```

Then restart Claude Code or Claude Desktop.

## Troubleshooting

| You see | Do this |
|---|---|
| kissflow-forge is not in the Desktop tools menu | The entry did not save. Quit Desktop with Cmd+Q, run the Step 5 script again, then open Desktop. Check with `grep -A3 kissflow-forge ~/Library/Application\ Support/Claude/claude_desktop_config.json`. |
| Desktop shows only a few kissflow-forge tools (Code shows 61) | Tools are switched off in Desktop. Tools menu → kissflow-forge → switch all on. |
| Desktop says the server failed to start | Read `tail -30 ~/Library/Logs/Claude/mcp-server-kissflow-forge.log`. |
| `/mcp` in Claude Code shows kissflow-forge as failed | Run the Step 3 check in `~/kissflow-forge-test`. Check the path in `claude mcp get kissflow-forge`. |
| `KF_DEV_DOMAIN is required` or `KF_DEV_ACCOUNT_ID is required` | `.env` is missing or that line is empty (Step 2). |
| `refusing non-dev domain` | Use the domain that starts with `dev-`. |
| `could not parse statement` | A line in `.env` has no `=`. Delete it. |
| A tool says "no Kissflow key pair on this call" | The key lines in `.env` are empty. |
