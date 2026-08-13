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

## Blocking / dependencies — GitLab linked issues (native, first-class)

GitLab has native, UI-visible issue links with a **direction**, which is the canonical DAG edge —
better than GitHub's task-list hack:

- **At creation**: `glab issue create -t "child" --linked-issues <blocker-iid> --link-type blocks`.
  `--link-type` is one of `relates_to` (default), `blocks`, `is_blocked_by`.
- **After creation** (add an edge): `glab api --method POST \
  "projects/:id/issues/<child-iid>/links" -f target_project_id=<numeric-project-id> \
  -f target_issue_iid=<blocker-iid> -f link_type=is_blocked_by`. Get the numeric project id once
  with `glab api "projects/cjexpress%2Ftildi%2Finfra%2Fai-coe%2Fkissflow-forge" -F output=json`
  (`.id`).
- **Read edges**: `glab api "projects/:id/issues/<iid>/links"` returns the linked issues with their
  `link_type` and `state`. The blocker also carries `blocking_issues_count`. A ticket is unblocked
  when every `is_blocked_by` link points at a `closed` issue.

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
- **Blocking**: use the native linked-issue edges above — create the child with
  `--link-type is_blocked_by --linked-issues <blocker-iid>`, or add the edge with the `links` API.
  This is the live gate, UI-visible on the issue.
- **Frontier query**: `glab issue list --state opened -l wayfinder:task -O json` scoped to the
  map's children; drop any that still have an open `is_blocked_by` link (check
  `projects/:id/issues/<iid>/links`) or an assignee; first in map order wins.
- **Claim**: `glab issue update <n> --assignee @me` — the session's first write.
- **Resolve**: `glab issue note <n> -m "<answer>"`, then `glab issue close <n>`, then append a
  context pointer (snippet + link) to the map's Decisions-so-far.
