# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — already populated (Identical Rebuild, Blindness, Known Exclusion, Approval Gate, BuildPlan, Confirmation Request, Fail-Open/Fail-Closed).
- **`docs/adr/`** at the repo root — already has 4 ADRs:
  - `0001-confirmation-gate-is-lint-not-lock.md`
  - `0002-branches-fail-open-loops-fail-closed.md`
  - `0003-known-exclusions-are-judge-owned.md`
  - `0004-refuse-the-api-impossible-at-compile.md`

  Read whichever ADRs touch the area you're about to work in.

This repo is single-context — no `CONTEXT-MAP.md`. If that ever changes, re-run `/setup-matt-pocock-skills` to switch layouts.

## File structure

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-confirmation-gate-is-lint-not-lock.md
│   ├── 0002-branches-fail-open-loops-fail-closed.md
│   ├── 0003-known-exclusions-are-judge-owned.md
│   └── 0004-refuse-the-api-impossible-at-compile.md
├── kfforge/        # the typed core — types, graph, expr, nav, pages, verify, client, engine...
├── shapes/         # 57 captured JSON node shapes
└── tests/
```

## Use the glossary's vocabulary

When your output names a domain concept (issue title, refactor proposal, hypothesis, test name), use the term as defined in `CONTEXT.md` — e.g. say **Known Exclusion**, never "known issue" or "limitation"; say **Blindness**, never "sanitized" or "scrubbed". Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0002 (branches fail open, loops fail closed) — but worth reopening because…_
