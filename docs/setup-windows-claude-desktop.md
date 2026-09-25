# Set up Kissflow Forge in Claude Desktop (Windows)

This guide is for a Windows PC that has only **Git** and **Claude Desktop**. When you finish,
Claude Desktop can build Kissflow apps on the dev tenant with your own Kissflow key.

Everything runs on your own PC. You do not need Docker, a VPN, or a server.

Time: about 15 minutes.

## What you need before you start

- **A GitLab account** on `gitlab.cjexpress.io`, added to the project. Step 0 below shows how.
- **Your own Kissflow dev key pair**: an Access Key ID and an Access Key Secret. Create it in
  Kissflow (your profile, then Access keys) on the **dev** tenant. Treat the secret like a
  password. Never paste it into a chat, an email or a shared document.
- **The dev tenant domain and account ID.** Ask the project owner. The domain starts with `dev-`.

You do **not** need to install Python, glab, or Docker. You do not need to set a Git name or
email either: Git asks for those only when you commit, and this setup never commits.

## Step 0. GitLab first-time setup

Do this once. The repo is private, so Git must sign in to download it.

1. **Sign in to GitLab once.** Open `https://gitlab.cjexpress.io` in your browser and sign in
   with the **Microsoft (Azure)** button, using your company account.
2. **Ask to be added to the project.** Send your GitLab username to the project owner (your
   avatar, top left, shows it as `@name`). The owner adds you to
   `cjexpress/tildi/infra/ai-coe/kissflow-forge` as **Reporter** or higher. When this is done,
   the project page opens for you instead of showing "Page not found".
3. **Create an access token.** If you sign in with the Microsoft button, you have no GitLab
   password, so Git uses a token instead.
   1. In GitLab, click your avatar, then **Edit profile**, then **Access tokens**
      (also called **Personal access tokens**).
   2. Click **Add new token**. Name: `kissflow-forge`. Expiration date: as your company allows.
      Scope: tick **read_repository** only.
   3. Click **Create**. **Copy the token now.** GitLab shows it only once. Keep it like a
      password; you need it in Step 2.

## Step 1. Install uv

uv runs the server. It also downloads the correct Python for you, so you do not install Python.

1. Open the Start menu, type `PowerShell`, and open **Windows PowerShell**. Open it normally,
   not with "Run as administrator".
2. Paste this line and press Enter:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

3. **Close PowerShell and open it again.** Windows adds uv to the PATH only for new windows,
   so the same window says `uv : The term 'uv' is not recognized`.
4. Check it:

   ```powershell
   uv --version
   ```

   You see a version number, for example `uv 0.9.28`.

   If it still says "not recognized", run this line in the same window, then check again:

   ```powershell
   $env:Path = "$HOME\.local\bin;$env:Path"
   ```

## Step 2. Download the code

In PowerShell:

```powershell
cd $HOME
git clone https://gitlab.cjexpress.io/cjexpress/tildi/infra/ai-coe/kissflow-forge.git
cd kissflow-forge
```

Git asks you to sign in (Git for Windows shows a small sign-in window):

- If the window offers **Token**, choose it and paste the token from Step 0.
- If it asks for a username and password, type your GitLab username, and paste the **token**
  as the password.

Windows saves this sign-in, so `git pull` later does not ask again. When the token expires,
open **Credential Manager** from the Start menu, go to **Windows Credentials**, remove the
entry for `git:https://gitlab.cjexpress.io`, create a new token, and run `git pull` again.

The code is now in `C:\Users\<your name>\kissflow-forge`.

## Step 3. Install the packages

Still in the `kissflow-forge` folder:

```powershell
uv sync
```

The first time, this downloads Python 3.13 and all packages. It can take a few minutes.

## Step 4. Add your key to a `.env` file

1. Make your own copy of the settings file:

   ```powershell
   copy .env.example .env
   notepad .env
   ```

2. In Notepad, fill in these four lines. Keep the key names. Put your value right after `=`,
   with no quotes and no spaces:

   ```
   KF_DEV_DOMAIN=<dev tenant domain, starts with dev->
   KF_DEV_ACCOUNT_ID=<account id>
   KF_DEV_ACCESS_KEY_ID=<your access key id>
   KF_DEV_ACCESS_KEY_SECRET=<your access key secret>
   ```

   `KF_APP` is optional. Set it to one app id if you want a default app.

3. Save with **Ctrl+S** and close Notepad.

Rules for this file:

- One `KEY=value` per line. A line without `=` breaks the file.
- Keep the name `.env` exactly. If Notepad saved it as `.env.txt`, rename it.
- This file holds your secret. Never send it, commit it or share it. Git already ignores it.

## Step 5. Check your settings and files

Run this in the `kissflow-forge` folder. It checks your `.env` and reads every guide and
reference file the server gives to Claude:

```powershell
uv run python -c "from app.infrastructure.config.settings import load_settings; from app.infrastructure.playbook import PLAYBOOKS, read_playbook; from app.infrastructure.capabilities import find_capabilities; s = load_settings(); c = find_capabilities(''); print('OK', s.kf_dev_domain, '| key set:', bool(s.kf_dev_access_key_id), '| skills:', [len(read_playbook(p)['text']) for p in PLAYBOOKS.values()], '| docs:', len(c['docs']), '| errors:', c['errors'])"
```

You see one line like this (the numbers can differ):

```
OK dev-<domain> | key set: True | skills: [24474, 13421, 6123] | docs: 31 | errors: []
```

`key set` must be `True` and `errors` must be `[]`. If you see an error, go to
Troubleshooting below.

## Step 6. Connect Claude Desktop

Claude Desktop rewrites its config file while it runs, so an edit made with the app open can
be lost. A script also avoids typing paths and `\\` by hand.

**1.** **Quit Claude Desktop fully.** Right-click the Claude icon in the taskbar tray (bottom
right) and choose **Quit**. Closing the window is not enough.

**2.** In PowerShell, go to the code folder:

```powershell
cd $HOME\kissflow-forge
```

**3.** Copy this whole block, paste it into PowerShell, and press Enter. It finds uv and the
code folder by itself, adds the `kissflow-forge` entry, keeps every other setting, and saves a
backup (`claude_desktop_config.json.bak`). It works for the normal and the Microsoft Store
installs of Claude Desktop.

```powershell
@'
import glob, json, os, shutil
from pathlib import Path

uv = shutil.which("uv")
if not uv:
    raise SystemExit("uv not found. Close PowerShell, open a new one, and run this again.")
repo = str(Path.cwd())
places = [Path(os.environ["APPDATA"]) / "Claude"]
places += [Path(p) for p in glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", "*Claude*", "LocalCache", "Roaming", "Claude"))]
targets = [p for p in places if p.is_dir()] or places[:1]
for folder in targets:
    folder.mkdir(parents=True, exist_ok=True)
    cfg_file = folder / "claude_desktop_config.json"
    cfg = {}
    if cfg_file.exists():
        shutil.copy2(cfg_file, str(cfg_file) + ".bak")
        cfg = json.loads(cfg_file.read_text(encoding="utf-8-sig") or "{}")
    cfg.setdefault("mcpServers", {})["kissflow-forge"] = {
        "command": uv,
        "args": ["--directory", repo, "run", "mcp-server"],
        "env": {"PYTHONUTF8": "1"},
    }
    cfg_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("saved:", cfg_file)
print("uv:", uv)
print("code folder:", repo)
'@ | uv run python -
```

You see one or two `saved:` lines, then `uv:` and `code folder:` with your paths.

**4.** Open Claude Desktop again.

**5.** In a new chat, open the tools menu (the slider icon) and open **kissflow-forge**. Switch
**all** tools on. Claude Desktop remembers switched-off tools per server name, so if you used a
`kissflow-forge` server before, some tools can still be off.

### If the script fails: edit the file by hand

Open Claude Desktop, go to **Settings → Developer → Edit Config** to find the folder, then
**quit Claude Desktop from the tray**. Open `claude_desktop_config.json` in Notepad and add this
entry inside `"mcpServers"` (put a comma after the entry before it). Replace `<your name>`, and
write every `\` in a path as `\\`:

```json
"kissflow-forge": {
  "command": "C:\\Users\\<your name>\\.local\\bin\\uv.exe",
  "args": ["--directory", "C:\\Users\\<your name>\\kissflow-forge", "run", "mcp-server"],
  "env": {"PYTHONUTF8": "1"}
}
```

`(Get-Command uv).Source` in PowerShell shows the real uv path. Save, then open Claude Desktop.

## Step 6b. Connect Claude Code (only if you use it)

Skip this if you use only the Claude Desktop app. Chat, Cowork and the **Code** tab inside
Claude Desktop use the Step 6 setup.

If you also installed **Claude Code** (the `claude` command in a terminal), add the server there
too. Run this in PowerShell, in the `kissflow-forge` folder. It passes the paths for you, so
PowerShell cannot change them:

```powershell
uv run python -c "import shutil, subprocess, pathlib; subprocess.run([shutil.which('claude'), 'mcp', 'add', 'kissflow-forge', '-s', 'user', '-e', 'PYTHONUTF8=1', '--', shutil.which('uv'), '--directory', str(pathlib.Path.cwd()), 'run', 'mcp-server'], check=True)"
```

You see `Added stdio MCP server kissflow-forge ... to user config`. Check it:

```powershell
claude mcp list
```

The line for `kissflow-forge` ends with `Connected`. In a new Claude Code session, `/mcp` also
shows it.

If it says the server already exists, remove the old one first, then run the add line again:

```powershell
claude mcp remove kissflow-forge -s user
```

## Step 7. Check that it works

Run each test in a new chat. Allow each tool when Claude Desktop asks. Stop at the first
failure, keep the exact error text, and check Troubleshooting below.

| # | Ask Claude | Pass when |
|---|---|---|
| T1 | Open the tools menu | **kissflow-forge** is there with all its tools switched on (about 61) |
| T2 | "Use kissflow-forge to list my Kissflow apps." | Claude calls `forge_list_apps` and shows your apps |
| T3 | "Call forge_playbook with skill usage." | readable text; dashes and arrows look right, not `â€”` |
| T4 | "Call forge_capabilities with query process-template." | one doc plus its shape, `errors: []` |
| T5 | "Run forge_doctor on flow `<an existing flow id>`." | a doctor report (read-only) |

There are three guides the server gives Claude: `usage` (how to use the tools), `design` (plan
an app with you in plain words), and the default builder guide (how to build). Before you
build, ask: "Read forge_playbook with skill usage, then tell me how you will work."

## Two rules before you build anything

- **Never add a group to a role to test something.** Kissflow sends a notice to every person in
  that group, and it cannot be undone. Test with your own name only.
- **An "OK" from the API does not prove the app works.** Ask Claude to run `forge_doctor` after
  each change and to walk a real test item with `forge_simulate_case`.

## Get updates

When the project owner tells you there is a new version, run this in the `kissflow-forge` folder:

```powershell
git pull
uv sync
```

Then quit and open Claude Desktop again.

## Troubleshooting

| You see | Do this |
|---|---|
| `uv` is not recognized | Close PowerShell and open a new one. Or run `$env:Path = "$HOME\.local\bin;$env:Path"` in the same window. If it still fails, run the Step 1 install again. |
| `git clone` says `repository not found` or `HTTP Basic: Access denied` | You are not a project member yet (Step 0.2), or you typed a password instead of the token, or the token lacks `read_repository` or has expired (Step 0.3). A wrong saved sign-in: remove `git:https://gitlab.cjexpress.io` from Windows Credential Manager and try again. |
| `KF_DEV_DOMAIN is required` or `KF_DEV_ACCOUNT_ID is required` | The `.env` file is missing, is named `.env.txt`, or that line is empty. Check Step 4. |
| `refusing non-dev domain` | The server works only on the dev tenant. Use the domain that starts with `dev-`. |
| `KF_DEV_DOMAIN is not a bare hostname` | Write only the host, for example `dev-name.kissflow.com`. No `https://`, no `/` at the end. |
| `could not parse statement` | A line in `.env` has no `=`. Delete that line. |
| `UnicodeDecodeError` or `charmap` in Step 5 | Your copy of the code is old. Run `git pull` and `uv sync`, then Step 5 again. |
| The uv install or `uv sync` fails with a certificate (SSL) error | The office network checks secure traffic. In PowerShell run `$env:UV_NATIVE_TLS=1`, then run the command again. |
| A tool fails with `CERTIFICATE_VERIFY_FAILED` | The server cannot check Kissflow's certificate on this network. Send the full error to the project owner. |
| kissflow-forge is not in the tools menu | The entry did not save. Quit Claude Desktop from the tray, run the Step 6 script again, then open Claude Desktop. If it still fails, read the newest `mcp*.log` in `%APPDATA%\Claude\logs`. |
| `claude mcp list` shows kissflow-forge as failed | Run the Step 5 check. If it passes, remove the entry (`claude mcp remove kissflow-forge -s user`) and run the Step 6b line again from the `kissflow-forge` folder. |
| Only a few kissflow-forge tools show | Some tools are switched off. Tools menu → kissflow-forge → switch all on. |
| A tool says "no Kissflow key pair on this call" | `KF_DEV_ACCESS_KEY_ID` or `KF_DEV_ACCESS_KEY_SECRET` is empty in `.env`. |
| A tool returns 401 or 403 from Kissflow | The key is wrong or expired, or your Kissflow user has no rights in that app. Make a new key or ask the app admin. |
