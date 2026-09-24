---
name: deploy
description: Deploy (promote) a Kissflow app between environments — dev to UAT, UAT to production — through the internal App Builder deploy API, or fix a deploy that fails. Use when the user says "deploy to prod", "deploy the app", "promote to UAT/production", "the deploy failed", or reports an "Internal.copy-application" error. Covers the undocumented /deploy endpoint sequence, the DeployTo=account-id payload, polling the job, the orphaned "All Items" report failure mode and its fix, and the read-back verification that a deploy actually landed.
---

# Kissflow — Deploy (environment promotion)

Deploying is **not** publishing. Publish (`/metadata/2/{acct}/{kind}/{id}/publish`) compiles one
flow's draft to live *inside* one environment. Deploy copies the whole app **across accounts** —
dev account to UAT account to prod account. It runs as a server-side job whose failing request id
carries the prefix `Internal.copy-application`. Everything here was captured live 2026-08-17, not
read off a schema; when the platform drifts, recapture, don't patch around it.

## THE RULE for deploys

**A `Status: "Completed"` and a Live app in the target prove nothing by themselves.**
Read back the target environment and diff it against the source — app, process, pages, members,
roles — before you call a deploy done. A deploy that silently drops assignees or pages is a
silent failure. "Completed" only means the copy job finished, not that every component landed.

## The endpoint sequence

Base = `https://{domain}`. Every request carries `?_application_id={app_id}` and the same
`X-Access-Key-Id` / `X-Access-Key-Secret` headers the rest of the engine uses — the deploy route
takes API-key auth, no browser cookies needed (verified: the UAT key drove a UAT→prod deploy).

| # | Method | Path (under `/flow/2/{src_acct}/application/{app_id}`) | Body | Returns |
|---|---|---|---|---|
| 1 | POST | `/deploy/flow/compare` | `{"DeployTo": "<target account id>"}` | `FlowComparison[]` — what is new/changed vs target |
| 2 | POST | `/deploy` | `{"DeployTo": "<target account id>", "VersionNumber": "<version>"}` | `{"_id": "<job id>"}` |
| 3 | GET | `/deploy/{job_id}` | — | poll until `Status` is `Completed` or `Failed` |
| 4 | GET | `/app/{app_id}/info` | — | app info after the deploy |
| 5 | DELETE | `/deploy/ack` | — | clear the deploy notification |

Poll step 3 on a loop (roughly every 10s). On `Failed`, the detail is in
`Deployment.Error[]` — each entry has `flow_name`, `flow_type`, and the `request_id`
(`Internal.copy-application-...`). That is the real error, not the UI's generic
"contact our support team" message.

## Payload rules (each one cost a round trip)

- **`DeployTo` is a target ACCOUNT ID, not a name.** `"Production"` / `"Prod"` / `"Live"`
  return `AccountDoesNotExist` (404). Use the target account id string.
- **`VersionNumber` is mandatory** on the deploy POST. Missing → `MissingRequiredFieldError`
  naming `VersionNumber`. Read it off `GET /flow/2/{acct}/application/{app_id}`.
- The compare step is a safe pre-deploy diff; run it first. It does not write anything.

## Environment map (this tenant)

| Env | Domain | Account id |
|---|---|---|
| Dev | `<DEV_DOMAIN>` | `<DEV_ACCOUNT_ID>` |
| UAT | `<UAT_DOMAIN>` | `<UAT_ACCOUNT_ID>` |
| Prod | `<PROD_DOMAIN>` | `<PROD_ACCOUNT_ID>` |

Keys: dev lives in `.env` (`KF_DEV_*`); UAT in `<path/to/uat-key.json>`; prod in
`<path/to/prod-key.json>` (read-only by policy — never write to prod with a guessed
payload). The real domains, account ids and key-file locations live outside this repo —
ask the repo owner or the secret store, never hardcode them here. Account ids change per
tenant; the table above is a shape to fill in, not a value to reuse. Within one deploy,
the app id and flow ids are **preserved** in the target (UAT and prod show the same flow
names as the source).

## The failure mode that ate a day (and its fix)

**Symptom:** deploy fails on component `Sample Case All Items` (Report) with
"An unexpected error has occurred. Please contact our support team." and an
`Internal.copy-application-...` request id.

**Root cause:** repeated dev→UAT deploys leave **archived duplicate flows** behind (each copy of
the process, plus stray test flows). Every archived flow drags an orphaned system
"All Items" report into the deploy's `FlowHashMap` inventory. `copy-application` tries to clone
one, hits a parent that is already `ModelArchived`, and dies with the generic error.

**Diagnose:** read the job record (`GET /deploy/{job}`) and count the `FlowHashMap` keys whose
name ends in `_All_Items`. Seven "All Items" reports for one live process is the tell. Cross-check
the source env's flow list — archived duplicates of the live flow are the culprits.

**Fix (proven):** delete the archived duplicate/junk flows in the SOURCE env, then redeploy.

```
DELETE /flow/2/{acct}/process/{flow_id}?_application_id={app_id}   # archived process (must be archived first)
DELETE /flow/2/{acct}/case/{flow_id}?_application_id={app_id}      # archived case/board
```

Verify each deletion by re-listing the flow kind (a 200 on DELETE is not proof). After removing
the junk flows, the deploy `Completed` at 100% with no error block.

## The "All Items" report is a system report, not a deployable artifact

It carries `_is_system: true`, `IsAllItemsReport: true`. It cannot be deleted or renamed, only
configured, and it auto-generates the first time the process Reports page is opened. An empty
report list on a freshly deployed process is **normal**, not a failure — the target generates its
own copy lazily. Nothing in item creation or workflow depends on it.

## Read-back verification checklist (run after every deploy)

Against the **target** env, confirm each matches the source:

```
GET /flow/2/{tgt_acct}/application/{app_id}              -> Status Live, BuildNumber, VersionNumber, LastDeployedAt
GET /flow/2/{tgt_acct}/process?_application_id={app_id}  -> the live process present + Live
GET /flow/2/{tgt_acct}/application/{app_id}/page?page_size=100  -> pages match source
GET /flow/2/{tgt_acct}/process/{flow_id}/member?_application_id={app_id}  -> members match source
```

Only declare success when every bucket matches.

## Gotchas

- The engine has no deploy tool, and `load_settings()` (`src/app/infrastructure/config/settings.py`)
  refuses any domain without `dev-`. To read UAT/prod or drive the deploy, send the requests above
  directly with that environment's own key pair. Do not route them through the engine.
- Deleting flows is irreversible. Confirm with the human before deleting, and delete only what
  is provably archived junk or a duplicate.
- A failed deploy can leave the target app as a Live **shell** with zero processes (partial
  state). Fix the source, redeploy; the next run completes it.
- `BuildNumber` increments on deploy; a failed attempt and the successful retry can share a build
  number. Don't read build number as deploy proof — read the target's actual flow list.
