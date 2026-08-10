# Confirmation gate is a lint, not a lock

The forge mints an HMAC approval token at the approve step and requires it to
compile a BuildPlan — but the LIVE build tools take raw params and no token, so
a builder could approve one design and build another. We accept that: the real
enforcement is the post-hoc identical-rebuild diff, not the token. The token
gate is a lint that forces an explicit approval; it does not lock execution. The
honest ceiling, stated in the gate's docstring: it proves one explicit approve
call bound to this exact content, never that a human made it.

## Considered Options

- **Token-gate the LIVE tools too** — rejected: forcing the fresh agent to thread
  a token through every build call buys little, because the diff catches
  divergence anyway and is the loop's actual signal.
- **Post-hoc diff as the real gate** — chosen.
