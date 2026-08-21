## Gate polarity

**Always gate a loop on a Boolean field, never on an optional Select.** The
two fail in opposite, and very differently dangerous, directions:

- A blank optional Select never equals the literal you're comparing it to, so
  the equality test is false — and false is what lets an item leave the loop,
  so the item **escapes the loop** unnoticed, having done none of the rework
  the loop existed for.
- The condition that actually gets evaluated lives on the `GotoTask`'s own
  `Activity::Expression`, and it gates **taking the backward jump**, not
  leaving the loop — condition true means "jump back," i.e. the item stays
  put. The proven live pattern is `<Boolean field> = false()` (a zero-arg
  `Function` literal, see Expressions): an unticked Boolean defaults to
  `false`, so `false = false()` evaluates true, the Goto fires, and the item
  **stays in the loop** — only once a human ticks the box does
  `true = false()` evaluate false, the Goto stops firing, and the item moves
  on.

**Fail closed.** A trapped item is visible on a dashboard and fixable by a
human. A silently-skipped rework round is invisible and unfixable after the
fact — nobody knows to go looking for it. When in doubt about which way a gate
should fail, make it the Boolean, and make the failure mode "stuck," not
"skipped."
