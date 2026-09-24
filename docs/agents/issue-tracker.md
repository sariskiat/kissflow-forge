# Issue tracker: GitLab

Issues and specs for this repo live as GitLab issues. Use the `glab` CLI for all operations.
`glab` infers the project and host from the `origin` remote when run inside the clone
(`cjexpress/tildi/infra/ai-coe/kissflow-forge` on `gitlab.cjexpress.io`), same as `gh` did for
GitHub — no `-R`/`--host` needed in-repo.

GitLab issues and merge requests have **separate** number spaces: `#42` is always an issue,
`!42` is always a merge request. No cross-resolution needed (unlike GitHub's shared space).

## Conventions

- **Create an issue**: `glab issue create -t "..." -d "..."`. `-d -` opens an editor; for a
  scripted multi-line body pass `-d "$(cat <<'EOF' … EOF)"` or `--no-editor -d "..."`.
- **Read an issue**: `glab issue view <number> --comments` (labels + notes included).
- **List issues**: `glab issue list --state opened -O json` (machine-readable), with `-l <label>`
  (repeatable / comma-separated) and `--assignee`/`--milestone` filters. `--state` is
  `opened`/`closed`/`all` (GitLab spelling, not `open`).
- **Comment on an issue**: `glab issue note <number> -m "..."` (GitLab calls comments *notes*).
- **Apply / remove labels**: `glab issue update <number> --label "a,b"` / `--unlabel "c"`.
- **Close**: `glab issue close <number>` (add a closing comment first with `glab issue note`).

## Blocking / dependencies — `relates_to` link + a "Blocked by" body section

⚠️ **This project's GitLab tier REJECTS directional blocking links.** `blocks` and
`is_blocked_by` both come back `HTTP 400 {"error":"link_type does not have a valid value"}` —
directional links are a paid-tier feature. Only `relates_to` is accepted. Verified 2026-08-19
against `projects/4971` (this repo) by POSTing all three values to the `links` API. Do not
re-probe: a 400 here is the tier, not a malformed call.

So the DAG edge is carried in **two** places, and both are needed:

1. **`relates_to` link** — undirected, but UI-visible on both issues, so a reader lands on the
   related ticket from either side.
2. **A `## Blocked by` section in the child's own body** — this is where the *direction* lives.
   One line per blocker, naming the issue: `Blocked by #4 — Get the suite green`. Machine-read
   it with a grep over the body, not the links API.

- **At creation**: `glab issue create -t "child" --linked-issues <blocker-iid> --link-type relates_to`
  (`relates_to` is also the default, so `--link-type` may be omitted). Put the `## Blocked by`
  section in the `-d` body.
- **After creation** (add an edge): `glab api --method POST \
  "projects/:id/issues/<child-iid>/links" -f target_project_id=<numeric-project-id> \
  -f target_issue_iid=<blocker-iid> -f link_type=relates_to`. Get the numeric project id once
  with `glab api "projects/cjexpress%2Ftildi%2Finfra%2Fai-coe%2Fkissflow-forge"` (`.id`; it is
  `4971` for this repo). Re-POSTing an existing pair returns `HTTP 409 Issue(s) already
  assigned` — harmless, treat it as already-linked.
- **Read edges**: `glab api "projects/:id/issues/<iid>/links"` returns the linked issues with
  their `link_type` (always `relates_to` here) and `state`. `blocking_issues_count` stays 0 on
  this tier — it counts directional links, so it is never a usable gate.
- **Is a ticket unblocked?** Read the `## Blocked by` lines out of its body, then check each
  named issue's `state` with `glab issue view <n>`. Every one `closed` = unblocked. The links
  API alone cannot answer this, because `relates_to` carries no direction.

## Pull requests (merge requests) as a triage surface

**MRs as a request surface: no.** _(Set to `yes` if this repo treats external MRs as feature
requests; `/triage` reads this flag.)_

When set to `yes`, MRs run through the same labels and states as issues, using the `glab mr`
equivalents:

- **Read an MR**: `glab mr view <number> --comments` and `glab mr diff <number>`.
- **List MRs for triage**: `glab mr list --state opened -O json`, then keep only MRs whose author
  is not a project member (filter by `author.username` against the member list, or by the MR's
  source being a fork).
- **Comment / label / close**: `glab mr note`, `glab mr update --label`/`--unlabel`, `glab mr close`.

## When a skill says "publish to the issue tracker"

Create a GitLab issue (`glab issue create`).

## When a skill says "fetch the relevant ticket"

Run `glab issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog
  body. `glab issue create --label wayfinder:map -t "..." -d "..."`.
- **Child ticket**: an issue whose body starts with `Part of #<map-iid>` and which is linked to the
  map (`--linked-issues <map-iid> --link-type relates_to`). Labels: `wayfinder:<type>`
  (`research`/`prototype`/`grilling`/`task`). Once claimed, assign it to the driving dev.
- **Blocking**: use the two-part edge above — create the child with
  `--link-type relates_to --linked-issues <blocker-iid>` (UI-visible on both issues) AND a
  `## Blocked by` section in its body carrying the direction. The body section is the gate;
  the link is only for navigation.
- **Frontier query**: `glab issue list --state opened -l wayfinder:task -O json` scoped to the
  map's children; for each, read its `## Blocked by` lines and drop it if any named issue is
  still open, or if it has an assignee; first in map order wins.
- **Claim**: `glab issue update <n> --assignee @me` — the session's first write.
- **Resolve**: `glab issue note <n> -m "<answer>"`, then `glab issue close <n>`, then append a
  context pointer (snippet + link) to the map's Decisions-so-far.
