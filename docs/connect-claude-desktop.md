# Connect Claude Desktop to Kissflow Forge

There are two ways to connect. Way 1 is the one to use on your own machine. Way 2 is
the shape the SRE gateway will use in front of the deployed server.

For local use, Claude uses the Kissflow key pair you provide. A deployed team
connector may use a central key pair, so Kissflow will see that shared identity.
The server works only on the dev tenant.
It refuses any domain whose first label does not start with `dev-`.

## Before you start

- Docker Desktop is running.
- You have your own Kissflow dev key pair: an **Access Key ID** and an **Access Key
  Secret** (Kissflow account settings, Access Keys). Treat the secret like a password.
  Never paste it into a chat, a shared document or an email.

## Step 1. Build the image

From the repo root:

```bash
docker build -t kissflow-forge:local .
```

## Step 2. Fill the env file

Copy `.env.example` to `.env` and fill these values. Docker reads this file as plain
`KEY=value` lines: no quotes, and no comment on the same line as a value.

```
KF_DEV_DOMAIN=<your dev tenant host, for example dev-yourco.kissflow.com>
KF_DEV_ACCOUNT_ID=<your account id>
KF_DEV_ACCESS_KEY_ID=<your access key id>
KF_DEV_ACCESS_KEY_SECRET=<your access key secret>
```

`KF_APP` is optional: set it to one app id if you want a default app.

## Way 1. Claude Desktop starts the container (stdio)

1. Open Claude Desktop, then **Settings**, **Developer**, **Edit Config**. This opens
   `claude_desktop_config.json`.
2. Add this entry under `mcpServers`. Keep the entries you already have. Put the
   absolute path of your `.env` in place of the example path.

   ```json
   {
     "mcpServers": {
       "kissflow-forge": {
         "command": "/usr/local/bin/docker",
         "args": [
           "run", "-i", "--rm",
           "--env-file", "/ABSOLUTE/PATH/TO/kissflow-forge/.env",
           "-e", "MCP_HTTP=",
           "kissflow-forge:local"
         ]
       }
     }
   }
   ```

3. Quit and reopen Claude Desktop. The tools menu lists 61 Kissflow Forge tools.

Why the flags:

- `-e MCP_HTTP=` makes the server talk over stdin and stdout, which is what Claude
  Desktop expects. The image default is HTTP.
- In this mode the server reads your key pair from the env file.
- Claude Desktop starts Docker with a short `PATH`, so the command is the full path of
  `docker`. Check yours with `which docker`.

## Way 2. The container serves HTTP

Start the server:

```bash
docker run --rm -p 127.0.0.1:8080:8080 --env-file .env -e MCP_HTTP=1 kissflow-forge:local
```

- The endpoint is `http://localhost:8080/mcp`.
- In this mode the server does **not** use the key pair in the env file. Every request
  must carry the caller's own pair in two headers: `X-Access-Key-Id` and
  `X-Access-Key-Secret`. A call without them fails with "no Kissflow key pair on this
  call".
- `-e MCP_HTTP=1` wins over an empty `MCP_HTTP=` line in the env file.

The server also accepts the same pair under two other names, for clients that may
only send pre-approved header names (Anthropic's custom connector refuses unapproved
custom names such as `x-access-key-id`):

- `X-Api-Key: <access key id>` and `X-Api-Secret: <access key secret>` (recommended:
  both names are on Anthropic's approved list, and `Authorization` stays free for the
  SRE gateway's own sign-in token);
- `Authorization: Bearer <access key id>:<access key secret>` (split on the first colon).

The first complete pair wins, in this order: `X-Access-Key-*`, `X-Api-*`, Bearer. Two
sources are never mixed.

In a Claude custom connector: choose **No sign-in**, then add two request headers, picked
from the approved list: `x-api-key` with your access key id and `x-api-secret` with your
access key secret. The values are sent exactly as entered, with no scheme word. The
connector calls from Anthropic's cloud, so the endpoint must be public HTTPS.

Claude Desktop's local MCP config cannot add request headers by itself. To reach this endpoint
from Claude Desktop, add a bridge that adds them, for example `mcp-remote` (it needs
Node.js):

```json
{
  "mcpServers": {
    "kissflow-forge-http": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "http://localhost:8080/mcp",
        "--header", "X-Access-Key-Id:${KF_KEY_ID}",
        "--header", "X-Access-Key-Secret:${KF_KEY_SECRET}"
      ],
      "env": {
        "KF_KEY_ID": "<your access key id>",
        "KF_KEY_SECRET": "<your access key secret>"
      }
    }
  }
}
```

For a deployed connector, the SRE gateway sits in front of the endpoint and signs
the person in with Entra. The connector sends the team's central key pair in the
two request headers; the gateway must forward them unchanged and must not log
them. That forwarding remains an open SRE check (section 14 of
`docs/specs/refactor-to-mcp-boilerplate.md`).

## Check it worked

Start a new chat and ask: **"list my Kissflow apps"**. You get a list back.

## If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| No Kissflow Forge tools in Claude Desktop | Claude Desktop could not start the container | Check the `docker` path and the `.env` path in the config. Check that Docker Desktop runs. |
| "no Kissflow key pair on this call" | The key pair did not arrive | Way 1: fill both key lines in `.env`. Way 2: send both headers. |
| The server stops at start with an error that names a key | A required value is missing or wrong | Fill `KF_DEV_DOMAIN` and `KF_DEV_ACCOUNT_ID`. The domain must be a bare host that starts with `dev-`. |
| An error with "401" or "403" from Kissflow | Kissflow refused the key pair | Make a fresh key pair in Kissflow and put it in `.env` (Way 1) or the headers (Way 2). |

## Things worth knowing

- **The server does not store the pair.** In HTTP mode it travels with each
  request and is dropped after the call. A team connector may hold a central
  pair in its own settings; follow your team's access rules for that pair.
- **To cut access off**, delete the access key in Kissflow. That stops it everywhere.

## What was tested, and what was not (2026-09-23)

Tested on 2026-09-23 with a throwaway env file that held fake values, before
the Stage E switch to `create_server()`:

- The image builds from this repo.
- Stdio (Way 1, run by a script the same way Claude Desktop runs it): 61 tools listed,
  and the offline tools `kf_list_field_types` and `forge_playbook` answered.
- HTTP (Way 2): 61 tools listed, and the same two tools answered. `forge_list_apps` with
  no headers failed with "no Kissflow key pair on this call". With the two headers it got
  past the key check. The fake secret appeared in no error and in no container log line.

The switched server passed offline tests. The live suite collected 31 tests
but skipped all 31 because the local dev app and key settings were unset. A
live call with a real key pair, Claude Desktop itself, and the `mcp-remote`
bridge have not been tested on the switched server.
