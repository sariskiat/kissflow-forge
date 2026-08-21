## Conditional routing

A `Parallel` gateway built by `build_workflow` is an unconditional and-fork on
its own — every branch always runs. **Conditional routing** (service-tier /
triage / approval-routing: "this branch runs when field X equals value Y") is
that gateway plus one `Expression` per branch, wired to the branch's own
`ProcessDef` (see Expressions' owner-key table). Node M (2026-08-07) is where
this became reachable from the tool surface — `expr.build_branch_condition`
existed since the branching AST work but had ZERO callers until then.

**The oracle shape** (a working app on this same tenant, read-only, months in
production): one `Parallel` Activity, N branch `ProcessDef`s each carrying
exactly one `ProcessDef`-owned `Expression` (`<field> = "<literal>"`, the same
AST as any other branch condition), and — on the branches that need rework —
its own `GotoTask` sitting **last within that branch's own
`ProcessDef::Activity`**, targeting an early step of the SAME branch. Never a
cross-branch or branch-to-root jump (see the Workflow section's
`branch_process_def_id` note). All fields tie together: the deciding field is
a plain `Select`, one distinct literal per branch, no branch left without a
condition (a genuine switch, not an if/else-if with an implicit "else").

⚠️ **Fail OPEN, not closed — a value matching no branch condition SKIPS THE
WHOLE PARALLEL and the item completes with no work done, silently.** Verified
live 2026-08-07 (node M's own negative control, independently reproduced, then
pinned as a permanent regression test — `tests/robot/forge_branching.robot`
test 11): walked with a deciding-field value that matched none of 3 branch
literals, the item never touched any branch step — the admin detail response
carries **NO `_current_step` key at all** (confirmed via `Dictionary Should
Not Contain Key`, not merely a null value under that key — a first draft of
this note said "came back null" from a paraphrase, and the live run corrected
it: code that does `detail["_current_step"]` would `KeyError` here, code that
does `detail.get("_current_step")` reads `None` either way — write it the
`.get()` way) and `_status` comes back `"Completed"` on the very next submit
past the step before the gateway. This is the SAME fail-open hazard Gate polarity already
names for a loop (a blank optional Select silently "escapes"), now confirmed
for a switch: an item that silently finishes is *worse* than one that gets
stuck, because a stuck item is visible on a dashboard and a finished one looks
identical to a real success — nobody ever goes looking for it. This is why
the oracle leaves NO branch without a condition (previous paragraph): every
value your users can actually pick needs a branch that claims it, or that
value quietly ends the case. `forge_set_branch_conditions`'s own result
carries an `uncovered` bucket for exactly this — every real Select option
(when the deciding field is one) that no branch on the gateway claims, across
the WHOLE gateway, not just the branches one call happened to touch.
`uncovered` is never folded into `isError` (a caller may genuinely want an
ending value) — it exists so the gap is stated, never discovered later.

**The tool**: `forge_set_branch_conditions(flow_id, field_name,
branch_literals, kind, publish)` — `branch_literals` maps a branch NAME to the
literal that selects it. Requires the flow to have **exactly one** `Parallel`
gateway (this engine can only build one anyway, via `build_workflow`'s single
`parallel` argument) — fails loud rather than guessing which one on a flow
with zero or more than one. Every literal is validated against the deciding
field's REAL live list options (fetched via its `ReferredList`) before any
write, same "never guess a literal — read it" discipline as everywhere else —
CLAUDE.md's own war story is a branch that silently never fired over one
mis-cased literal. Idempotent per branch in the SET sense: re-running with a
changed literal REPLACES that branch's condition (`expr.remove_condition`
strips the old Expression + AST subtree + back-refs first) rather than
accumulating a second one alongside the stale first; a branch not named in
`branch_literals` is left untouched. Pair with `forge_add_goto_gate`'s
`branch_name` parameter (see Workflow) for the per-branch loop half of the
shape.

⚠️ **A tenant-state limitation, not an engine limitation, logged rather than
silently worked around**: KF_APP's list inventory was EMPTY (0 lists) as of
2026-08-07 (same finding `forge_lifecycle.robot` already logged for its own
Select-field fallback) — no human has wired a Kissflow List into this app yet.
`build_branch_condition` also accepts a Text-typed deciding field (the same
plain-string wire shape as a Select's value — see `_BRANCH_FIELD_DATA_TYPE`),
so the live proof below used Text and got the real literal-validation-against-
options codepath exercised only by the OFFLINE tests (a fake list). The
Select-backed path is offline-proven and code-reviewable, but **its live
option-fetch-and-validate behavior remains unverified on THIS tenant** until a
human wires a real List — do not upgrade that to "proven" without re-running
against one.

⚠️ **A live-verified mechanic, worth recording because it is easy to guess
wrong**: crossing a conditional `Parallel` gateway needs **no separate
submit**. An item sitting on the step immediately before the `Parallel`
(`ProcessDef::Activity` order) that gets submitted lands **directly** on the
selected branch's own first step, in the SAME API call — the gateway itself
is never a `_current_step` a caller submits against, conditional or not (it
carries no Permissions either — see `NO_PERMISSION_NODETYPES`). Verified live
2026-08-07 (node M): two items, submitted past the same step with different
values of the deciding field, landed on `Handle Alpha` and `Handle Beta`
respectively after that ONE submit each — not on the `Parallel` itself, and
not requiring a second hop.

**Two-item divergence is the only real proof.** Every check up to and
including a clean `forge_doctor` can pass with a branch condition silently
inverted, missing a literal, or pointed at the wrong field — a branch that
never fires looks identical to one that works (THE RULE, restated for this
specific shape). The only oracle is walking two real items with different
values of the deciding field and reading back — directly, never an echo of
the plan — which concrete step each one actually landed on
(`tests/robot/forge_branching.robot`'s `Get Current Step` keyword; a plain
`_current_step` read via the item data plane — `Get Item Detail` is the
general-purpose sibling for a test that needs a field `Get Current Step`'s own
strictness would raise on, like test 11's legitimately-absent one). `tests/
robot/forge_branching.robot` is the permanent regression suite for this whole
section, including the fail-open negative control above — 11/11 live
against KF_APP as of 2026-08-07, artifact deleted and deletion verified via
the app-scoped flow-list route in its Suite Teardown.
