# Template cloning transplants the captured graph instead of recompiling it

To clone the source template process onto the dev tenant "exactly", the engine
writes the captured source graph verbatim — ids remapped, identities stripped,
tenant-only refs (assignee role, User/Reference sources) re-pointed — rather
than translating the capture into its own governed build ops.

The governed path was the obvious alternative and was rejected for a fidelity
reason: the capture carries 19 `Condition` + 16 `Criteria` nodes (conditional
visibility/styling) and 16 Field-owned `Expression` nodes (computed formulas),
and the build-op vocabulary cannot express the Condition/Criteria shapes at
all. Recompiling would silently drop them, which fails the "exactly like the
template" bar. The identity-shell clone (`from_template=True`, issue #59)
already proved transplant works live; this extends it to the full template.

Consequences: the vendored shape must be deidentified before it enters the
repo (raw capture stays in the eval harness), and quirks of the source are
kept verbatim — including its duplicate "Manager Approve" step. Computed
formulas transplant as shapes; their runtime evaluation is client/submit-side
and stays subject to the #48 open proof.
