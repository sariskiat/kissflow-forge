# Pages are governed at compile; the plan carries content and behavior, not layout

The page layer routes through the same `AppSpec → compile → BuildPlan` path as
the workflow layer, and coverage is governed at **compile**: compile refuses an
unbuildable page shape before a plan is emitted, exactly as it refuses an
unbuildable flow shape. `forge_build_page` stays a primitive that the plan's
`build_page` op describes; it is not a second, ungoverned build surface.

The governed plan carries **content and behavior** — widgets, KPIs, actions,
popups, and events — because a button that opens a popup is structure, not
decoration, and structure must be refused-or-built, never silently dropped.
Layout geometry and exact styling are **not** in the plan: a built page takes
the platform's default look, and matching a specific mockup's pixels is an
eval-harness concern, never a build-correctness gate. #25's name-collision fix
keeps styling from crashing when a style *is* applied; it does not make
mockup-parity a build bar.

## Considered Options

- **Harden the standalone `pages_live` surface** — rejected: it rebuilds the
  exact ungoverned bypass that let workflow gaps go uncaught (the origin of
  #15/#29). Compile would keep emitting page ops nobody governs against a
  contract.
- **Carry the full container/style/popup/event tree in the spec** — rejected:
  it drags exact-layout parity into build correctness, the eval-parity trap
  under "the mockup is eval, not the target."
- **Content + behavior in the plan, layout/style defaulted** — chosen.

## Consequences

The page half of the coverage contract (`kfforge/coverage.py`) is what compile
consults; every page refusal names its row, same as the workflow refusals.
Reproducing a specific mockup's layout or colors belongs to the eval harness
(#16/#28), not the forge, and a shape the plan cannot carry (custom layout,
mockup-exact styling, report creation) is a `refuses-loudly` row, not a
best-effort build.
