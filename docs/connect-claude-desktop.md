# Connect Claude Desktop to Kissflow Forge

For the person who will use this to build Kissflow apps by chatting. No coding needed.
Takes about five minutes, once.

## What you are doing

You are giving Claude Desktop your own Kissflow key, so that anything it builds is built
**as you**. Nobody shares a key. Whatever you are allowed to do in Kissflow is exactly
what Claude can do for you — no more.

## Step 1 — get your own Kissflow key

1. Sign in to the Kissflow dev site.
2. Open your account settings and find **Access Keys** (sometimes called API keys).
3. Create a new key. You get two values:
   - an **Access Key ID** — shortish, looks like `Akc5b...`
   - an **Access Key Secret** — much longer

Copy both somewhere safe for a minute. The secret is shown once. Treat it like a
password: never paste it into a chat, a shared document, or an email.

## Step 2 — add the connector in Claude Desktop

1. Open Claude Desktop → **Settings** → **Connectors** → **Add custom connector**.
2. **Name**: `Kissflow Forge`
3. **URL**: ask whoever runs the server for it. It ends in `/mcp`.
4. Open **Advanced settings**. Two boxes appear:
   - **OAuth Client ID** → paste your Access Key **ID**
   - **OAuth Client Secret** → paste your Access Key **Secret**
5. Click add. A browser window opens, you may be asked to sign in with your company
   Microsoft account, and then it closes by itself. That is the connection being made.

Those two boxes are labelled "OAuth" because that is the standard way an app proves who
it is. Here, your Kissflow key *is* that proof. Same two values, nothing extra to create.

## Step 3 — check it worked

Start a new chat and ask: **"list my Kissflow apps"**. You should get a list back.

## If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| Sign-in window never closes | The connection did not finish | Close it, remove the connector, add it again |
| "not authenticated — paste your own Kissflow access-key ID..." | One of the two boxes is empty or wrong | Remove the connector and re-add it with both values |
| "Invalid client" when connecting | The key ID and secret do not match, or the key was deleted in Kissflow | Make a fresh key in Kissflow and use the new pair |
| It worked yesterday, not today | Your Kissflow key was rotated or revoked | Make a fresh key and re-add the connector |

## Things worth knowing

- **Your key stays yours.** The server never stores it. It travels with each request and
  is thrown away.
- **Sessions expire after an hour** and renew themselves quietly. You will not notice.
- **To cut access off**, delete the access key in Kissflow. That stops it everywhere,
  within the hour.
- **This only ever touches the dev site.** The server refuses to write anywhere else, and
  that is fixed in the server, not something a chat can talk it out of.
