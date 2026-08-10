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
