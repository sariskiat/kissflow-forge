# Refuse the API-impossible at compile, don't best-effort

Four capabilities are unreachable through the API (role-scoped visibility, rich
text rendering, custom component upload, report creation). The forge refuses
them at compile/doctor — doctor fails role-scoped visibility, compile
rejects/skips the rest with a stated reason — rather than building best-effort
approximations. The rebuild simply lacks them; the judge's Known Exclusion
explains the absence. "Identical except exclusions" means the forge does not
attempt them, not that it attempts and degrades.

## Considered Options

- **Build best-effort, compare excludes the delta** — rejected: a partial build
  (plain text for rich text, step-scoped for role-scoped) makes "identical"
  fuzzy and hides whether a gap is the platform or the engine.
- **Refuse at compile/doctor** — chosen.
