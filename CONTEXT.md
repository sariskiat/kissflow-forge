# kissflow-forge

An MCP connector that designs and builds any Kissflow app from a plain business
document. Whether it really works is proven by rebuilding a known app
identically, not by test count.


## The proof

**Identical Rebuild**:
The forge's acceptance bar. A fresh agent, with no session memory and restricted
to the MCP tools, rebuilds a known app from a business document alone; the result
must be identical to the original within the Known Exclusions. Test count is not
this.
_Avoid_: passing tests, green build, shipping the surface

**Blindness**:
The forge carries zero traces of the target app — no ids, names, sample
content, or domain text. Enforced by a CI scan so the rebuild is double-blind:
the builder cannot have copied what it never saw.
_Avoid_: sanitized, cleaned, scrubbed

**Known Exclusion**:
A platform capability the forge cannot reproduce through the API (role-scoped
visibility, rich text rendering, custom components, report creation). Excluded
from the Identical Rebuild bar, and owned by the judge, not the builder.
_Avoid_: known issue, limitation, unsupported


## The build process

**Approval Gate**:
The checkpoint where a customer explicitly approves a design before any build.
Proves an approval call happened for this exact content. Does not prove a human
made it, and does not lock the build tools — enforcement is the post-hoc diff.
_Avoid_: confirmation, sign-off (those name the act, not the gate's honest ceiling)

**BuildPlan**:
The ordered, approved sequence of build operations compiled from an approved
spec. Refuses to compile without an Approval Gate token.
_Avoid_: build script, recipe, steps

**Confirmation Request**:
The artifact set shown to the customer for approval — workflow diagram,
data-schema diagram, and per-persona mockups, with approval questions.
_Avoid_: proposal, design review

## Routing behavior

**Fail-Open (branch)**:
A conditional branch routes by matching a field value to a literal; an item
matching no branch proceeds to the end. Intentional, platform-native.
_Avoid_: default path, fall-through

**Fail-Closed (loop)**:
A rework loop gates on a Boolean; an unticked gate keeps the item in the loop.
Intentional — a trapped item is visible and fixable; a silently skipped rework
round is neither.
_Avoid_: blocking, stuck


## Pages

**Governed Page Path**:
The sanctioned way a page reaches the tenant: `AppSpec → compile → BuildPlan`,
with compile refusing any unbuildable page shape before a plan is emitted.
`forge_build_page` is the primitive the plan's `build_page` op describes, not a
second build surface that skips the contract (ADR-0005).
_Avoid_: page builder, the pages API (those name the tool, not the governed path)

**Build-Correctness Bar (pages)**:
What a built page must get right: content and behavior — widgets, KPIs, actions,
popups, events. A missing or wrong one of these is a build defect.
_Avoid_: parity, fidelity (those name the eval bar)

**Eval-Parity (pages)**:
How close a built page's layout and styling match a specific mockup's pixels.
Owned by the eval harness, never a build gate — a built page takes the
platform's default look, and mockup-exact layout/color is graded in eval, not
refused or faked at build (ADR-0005).
_Avoid_: build correctness, identical (those name the build bar)

**Page Coverage Contract**:
The page rows of `kfforge/coverage.py` — every mockup element in exactly one
bucket (captured-live / buildable / refuses-loudly). Compile consults it; every
page refusal names its row. Same module and contract test as the workflow rows,
so the two cannot drift.
_Avoid_: page matrix, supported widgets list
