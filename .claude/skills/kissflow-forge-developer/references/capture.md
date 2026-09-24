# Capture a wire shape from the builder UI

Use this when the engine cannot build a feature, or writes a graph the builder UI does not
accept. The builder UI is the oracle: build ONE piece by hand, capture what it wrote, diff.

## Loop

1. Write the red test first: build the change against a fake and assert the nodes the graph
   must contain. The test encodes the capture, never a guess.
2. Ask the human for one capture (below). One piece per capture.
3. Read the engine's own graph back (`kf_get_flow_schema`, or a raw draft GET).
4. Diff the UI payload against the engine graph node by node, key by key.
5. Make the smallest change in `src/app/` that turns the test green.
6. Rebuild the feature on a fresh flow with `forge_*` tools only. Doctor. Simulate.
7. Save `shapes/<name>.json` (ids replaced with synthetic ones) and
   `docs/capabilities/<name>.md`.

When it still errors, do not diff the same part again. Check a layer you have not checked: the
flow's config payload, membership, a per-node key you assumed optional, or the requests the UI
sends while it loads the broken page. 403 or 500 means the route exists; only 404 means wrong route.

## What to ask the human for

1. Open the builder for the flow in Chrome. Press F12, open **Network**, tick **Preserve
   log**, filter `flow`, press Clear.
2. Do one thing (add one lookup field, set one assignee, set one formula) and save.
3. For each `PUT` / `POST` / `PATCH` row: the Request URL and method, the payload (view
   source), and the response. Or right-click → Copy → Copy as cURL.
4. Delete the `Cookie` and `Authorization` header lines before pasting.

## Handling a capture

- Read a HAR with `python3`. Never open it whole in context.
- Drop every header named `cookie`, `authorization`, `x-access-key-id`,
  `x-access-key-secret`, `x-api-key`, `x-api-secret` before you quote anything.
- Never write a raw HAR, a cURL line, a real tenant name, a real account id or a real person's
  name into the repo. `tests/test_p0_scaffold.py` fails on identity tokens.
- A shape captured on one tenant stays `captured` until an item walks through it live.
