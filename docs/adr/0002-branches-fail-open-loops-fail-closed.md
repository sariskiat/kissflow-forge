# Branches fail open, loops fail closed

Kissflow conditional branches route by matching a field value to a literal; an
item matching no branch proceeds to the end (fail-open). Rework loops gate on a
Boolean, and an unticked gate keeps the item in the loop (fail-closed). We keep
the asymmetry deliberately: fail-open on branches is platform-native (a no-match
reaching the end is Kissflow's behavior), while fail-closed on loops is ours
because a trapped item is visible and fixable and a silently skipped rework round
is neither.

## Consequences

Fail-closed on branches would fight the platform; fail-open on loops would
silently skip rework. The asymmetry is documented, not a bug — a doctor rule
may warn when a spec's branches don't cover all list options, but does not trap.

S4 (#35): the compile gate now refuses a split where a real value of the
deciding field is claimed by no branch (D8); runtime still fails open, and the
doctor still only warns — an intentional fall-through must be modeled as an
explicit branch claiming that value, not left implicit.
